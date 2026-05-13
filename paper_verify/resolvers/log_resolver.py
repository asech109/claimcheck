from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ..models import Claim, SourceAnchor

# Search file extensions in priority order.
_LOG_EXTS = (".json", ".jsonl", ".csv", ".tsv")

# How label tokens map to the keys a metrics log might use.
_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "accuracy": ("accuracy", "acc", "eval_accuracy", "test_accuracy"),
    "loss": ("loss", "train_loss", "eval_loss", "val_loss"),
    "f1": ("f1", "f1_score"),
    "auc": ("auc", "roc_auc"),
    "precision": ("precision",),
    "recall": ("recall",),
    "bleu": ("bleu", "bleu_score"),
    "rouge": ("rouge", "rougeL", "rouge_l"),
    "perplexity": ("perplexity", "ppl"),
    "reward": ("reward", "mean_reward", "eval_reward"),
    "win_rate": ("win_rate", "winrate"),
    "success_rate": ("success_rate", "success"),
    "transitions": ("transitions", "n_transitions", "num_transitions"),
    "episodes": ("episodes", "n_episodes", "num_episodes"),
    "steps": ("steps", "n_steps", "num_steps", "total_steps"),
    "samples": ("samples", "n_samples", "num_samples"),
    "examples": ("examples", "n_examples"),
    "tokens": ("tokens", "n_tokens", "num_tokens"),
    "parameters": ("parameters", "n_parameters", "num_parameters", "param_count"),
    "environments": ("environments", "n_envs", "num_envs"),
    "tasks": ("tasks", "n_tasks", "num_tasks"),
}


def _iter_log_files(root: Path):
    if not root.exists():
        return
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in _LOG_EXTS:
            yield p


def _search_json_obj(obj: Any, keys: tuple[str, ...]) -> Any | None:
    """Depth-first search for first matching key (case-insensitive)."""
    lowered = {k.lower() for k in keys}
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if isinstance(k, str) and k.lower() in lowered and isinstance(v, (int, float)):
                    return v
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def _scan_json(path: Path, keys: tuple[str, ...]) -> tuple[Any, int] | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    # Try whole-file JSON first.
    try:
        data = json.loads(text)
        val = _search_json_obj(data, keys)
        if val is not None:
            line = _locate_key_line(text, keys)
            return val, line
    except json.JSONDecodeError:
        pass
    # Fallback: JSONL — iterate line by line.
    for i, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        val = _search_json_obj(data, keys)
        if val is not None:
            return val, i
    return None


def _locate_key_line(text: str, keys: tuple[str, ...]) -> int:
    lowered = [k.lower() for k in keys]
    for i, line in enumerate(text.splitlines(), start=1):
        line_lower = line.lower()
        for k in lowered:
            if f'"{k}"' in line_lower:
                return i
    return 1


def _scan_csv(path: Path, keys: tuple[str, ...]) -> tuple[Any, int] | None:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        delim = "\t" if path.suffix.lower() == ".tsv" else ","
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=delim + ",;\t")
            reader = csv.DictReader(f, dialect=dialect)
        except csv.Error:
            f.seek(0)
            reader = csv.DictReader(f, delimiter=delim)
        if not reader.fieldnames:
            return None
        lowered_fields = {fn.lower(): fn for fn in reader.fieldnames if fn}
        target = None
        for k in keys:
            if k.lower() in lowered_fields:
                target = lowered_fields[k.lower()]
                break
        if target is None:
            return None
        last_val: float | None = None
        last_row_line: int = 1
        for i, row in enumerate(reader, start=2):  # header is line 1
            raw = row.get(target, "")
            try:
                last_val = float(raw)
                last_row_line = i
            except (TypeError, ValueError):
                continue
        if last_val is None:
            return None
        return last_val, last_row_line


def resolve_numeric_or_count(claim: Claim, log_root: Path) -> tuple[Any, SourceAnchor] | None:
    """Search log_root for a key matching claim.label. Returns (value, anchor) or None."""
    keys = _LABEL_ALIASES.get(claim.label, (claim.label,))
    for f in _iter_log_files(log_root):
        if f.suffix.lower() in (".json", ".jsonl"):
            result = _scan_json(f, keys)
        else:
            result = _scan_csv(f, keys)
        if result is not None:
            value, line = result
            return value, SourceAnchor(path=f, line=line)
    return None
