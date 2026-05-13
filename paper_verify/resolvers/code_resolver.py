from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

from ..extractors.method_parser import MethodFingerprint, parse_method_description
from ..models import SourceAnchor

_CODE_EXTS = (".py", ".ipynb", ".js", ".ts", ".rs", ".go", ".cpp", ".java")


def _iter_code_files(root: Path):
    if not root.exists():
        return
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "site-packages"}
    for p in root.rglob("*"):
        if any(part in skip_dirs for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() in _CODE_EXTS:
            yield p


_C_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_C_LINE_COMMENT = re.compile(r"//[^\n]*")


def _strip_python_noncode(text: str) -> str:
    """Return text with docstrings, string literals, and comments removed.

    Why: a comment like '# proximal policy optimization (no GAE)' must not
    cause GAE to count as 'implemented in code'. AST gives us a structural
    way to drop strings; tokenize drops comments."""
    # Drop strings via AST. Replace each ast.Constant string with whitespace
    # of the same length so subsequent line tracking is preserved.
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # Fallback: regex-strip C-style comments, then strip Python comments.
        return _strip_pyish_regex(text)
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            start = _ast_offset(text, node.lineno, node.col_offset)
            end_line = getattr(node, "end_lineno", node.lineno)
            end_col = getattr(node, "end_col_offset", node.col_offset)
            end = _ast_offset(text, end_line, end_col)
            if start is not None and end is not None and end > start:
                spans.append((start, end))
    # Remove overlapping spans by collapsing strings to spaces (preserve newlines).
    out = list(text)
    for s, e in spans:
        for i in range(s, e):
            if out[i] != "\n":
                out[i] = " "
    stripped = "".join(out)
    # Strip Python '#' comments.
    try:
        tok_stream = list(tokenize.generate_tokens(io.StringIO(stripped).readline))
    except tokenize.TokenizeError:
        return stripped
    out2 = list(stripped)
    for tok in tok_stream:
        if tok.type == tokenize.COMMENT:
            sr, sc = tok.start
            er, ec = tok.end
            s = _ast_offset(stripped, sr, sc)
            e = _ast_offset(stripped, er, ec)
            if s is not None and e is not None:
                for i in range(s, e):
                    if out2[i] != "\n":
                        out2[i] = " "
    return "".join(out2)


def _strip_pyish_regex(text: str) -> str:
    """Last-resort comment/string stripper for files that don't parse."""
    text = _C_BLOCK_COMMENT.sub(lambda m: " " * len(m.group(0)), text)
    text = _C_LINE_COMMENT.sub(lambda m: " " * len(m.group(0)), text)
    # Strip Python-style comments.
    text = re.sub(r"#[^\n]*", lambda m: " " * len(m.group(0)), text)
    return text


def _ast_offset(text: str, line: int, col: int) -> int | None:
    """Convert (1-indexed line, 0-indexed col) to absolute char offset."""
    if line < 1:
        return None
    offset = 0
    cur_line = 1
    for ch in text:
        if cur_line == line:
            return offset + col
        if ch == "\n":
            cur_line += 1
        offset += 1
    if cur_line == line:
        return offset + col
    return None


def build_code_fingerprint(code_root: Path) -> tuple[MethodFingerprint, dict[str, SourceAnchor]]:
    """Walk code files, collect tokens that match algorithm vocabulary.

    Returns (fingerprint, anchors) where anchors maps each token to the first
    file:line it appeared on, so the reporter can cite provenance."""
    fp = MethodFingerprint()
    anchors: dict[str, SourceAnchor] = {}
    if not code_root.exists():
        return fp, anchors

    for f in _iter_code_files(code_root):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if f.suffix.lower() == ".py":
            text = _strip_python_noncode(text)
        else:
            # Best-effort for non-Python: strip C-style and '#' comments only.
            text = _strip_pyish_regex(text)
        partial = parse_method_description(text)
        for algo in partial.algorithms:
            if algo not in anchors:
                line = _find_first_line(text, algo)
                anchors[algo] = SourceAnchor(path=f, line=line)
                fp.algorithms.add(algo)
        for arch in partial.architecture:
            if arch not in fp.architecture:
                fp.architecture.append(arch)
                key = f"arch:{arch[0]}-{arch[1]}-{arch[2]}"
                if key not in anchors:
                    anchors[key] = SourceAnchor(path=f, line=_find_first_line(text, arch[2]))
    return fp, anchors


def _find_first_line(text: str, needle: str) -> int:
    lowered_needle = needle.lower()
    for i, line in enumerate(text.splitlines(), start=1):
        if lowered_needle in line.lower():
            return i
    return 1
