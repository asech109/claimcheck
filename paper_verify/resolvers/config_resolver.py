from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import yaml

from ..models import Claim, SourceAnchor

_CONFIG_EXTS = (".yaml", ".yml", ".json", ".toml", ".py")

# Hyperparam label -> candidate keys in config files.
_HP_ALIASES: dict[str, tuple[str, ...]] = {
    "learning_rate": ("learning_rate", "lr", "learningrate"),
    "batch_size": ("batch_size", "batchsize", "batch"),
    "weight_decay": ("weight_decay", "wd", "weightdecay"),
    "dropout": ("dropout", "dropout_rate", "drop_rate"),
    "hidden_dim": ("hidden_dim", "hidden_size", "d_model", "hidden"),
    "num_layers": ("num_layers", "n_layers", "depth", "num_hidden_layers"),
    "epochs": ("epochs", "num_epochs", "n_epochs", "max_epochs"),
    "warmup_steps": ("warmup_steps", "warmup", "n_warmup"),
    "temperature": ("temperature", "temp"),
    "gamma": ("gamma", "discount", "discount_factor"),
    "lambda_": ("lambda", "gae_lambda", "lambda_"),
    "seed": ("seed", "random_seed"),
}


def _iter_config_files(root: Path):
    if not root.exists():
        return
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    for p in root.rglob("*"):
        if any(part in skip_dirs for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() in _CONFIG_EXTS:
            yield p


def _search_yaml(path: Path, keys: tuple[str, ...]) -> tuple[Any, int] | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if data is None:
        return None
    val = _walk_for_key(data, keys)
    if val is None:
        return None
    line = _locate_yaml_key_line(text, keys)
    return val, line


def _walk_for_key(obj: Any, keys: tuple[str, ...]) -> Any | None:
    lowered = {k.lower() for k in keys}
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if isinstance(k, str) and k.lower() in lowered and isinstance(v, (int, float, str)):
                    if isinstance(v, str):
                        # Allow stringified scalars like "3e-4".
                        try:
                            return float(v) if "." in v or "e" in v.lower() else int(v)
                        except ValueError:
                            return v
                    return v
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def _locate_yaml_key_line(text: str, keys: tuple[str, ...]) -> int:
    lowered = [k.lower() for k in keys]
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.split("#", 1)[0].strip().lower()
        for k in lowered:
            if stripped.startswith(f"{k}:") or stripped.startswith(f"{k} ="):
                return i
    return 1


_PY_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*(?:#.*)?$")


def _search_python(path: Path, keys: tuple[str, ...]) -> tuple[Any, int] | None:
    """Look for module-level constants AND argparse defaults."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lowered = {k.lower() for k in keys}
    # Module-level assignment via AST.
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _search_python_regex(text, lowered)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.lower() in lowered:
                    try:
                        val = ast.literal_eval(node.value)
                        if isinstance(val, (int, float, str)):
                            return val, node.lineno
                    except (ValueError, SyntaxError):
                        pass
    # Argparse default=... fallback.
    return _search_argparse_defaults(tree, text, lowered)


def _search_argparse_defaults(tree: ast.AST, text: str, lowered: set[str]) -> tuple[Any, int] | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "add_argument":
                # First positional arg or 'dest' kwarg gives the name.
                name = None
                if node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        name = first.value.lstrip("-").replace("-", "_")
                for kw in node.keywords:
                    if kw.arg == "dest" and isinstance(kw.value, ast.Constant):
                        name = str(kw.value.value)
                if not name or name.lower() not in lowered:
                    continue
                for kw in node.keywords:
                    if kw.arg == "default":
                        try:
                            val = ast.literal_eval(kw.value)
                            if isinstance(val, (int, float, str)):
                                return val, node.lineno
                        except (ValueError, SyntaxError):
                            pass
    return None


def _search_python_regex(text: str, lowered: set[str]) -> tuple[Any, int] | None:
    for i, line in enumerate(text.splitlines(), start=1):
        m = _PY_ASSIGN_RE.match(line)
        if not m:
            continue
        if m.group(1).lower() in lowered:
            raw = m.group(2).rstrip(",").strip()
            try:
                val = ast.literal_eval(raw)
                if isinstance(val, (int, float, str)):
                    return val, i
            except (ValueError, SyntaxError):
                continue
    return None


def resolve_hyperparam(claim: Claim, code_root: Path) -> tuple[Any, SourceAnchor] | None:
    keys = _HP_ALIASES.get(claim.label, (claim.label,))
    for f in _iter_config_files(code_root):
        ext = f.suffix.lower()
        if ext in (".yaml", ".yml"):
            result = _search_yaml(f, keys)
        elif ext == ".json":
            result = _search_yaml(f, keys)  # yaml.safe_load handles JSON
        elif ext == ".py":
            result = _search_python(f, keys)
        else:
            result = None
        if result is not None:
            value, line = result
            return value, SourceAnchor(path=f, line=line)
    return None
