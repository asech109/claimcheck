from __future__ import annotations

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
