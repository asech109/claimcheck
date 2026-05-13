from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ClaimType(str, Enum):
    NUMERIC = "numeric"
    HYPERPARAM = "hyperparam"
    COUNT = "count"
    METHOD = "method"


class Status(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNVERIFIABLE = "unverifiable"
    WAIVED = "waived"
    METHOD_DRIFT = "method-drift"


@dataclass(frozen=True)
class SourceAnchor:
    path: Path
    line: int = -1

    def render(self, base: Path | None = None) -> str:
        p = self.path
        if base is not None:
            try:
                p = self.path.relative_to(base)
            except ValueError:
                pass
        if self.line > 0:
            return f"{p}:{self.line}"
        return str(p)


@dataclass
class Claim:
    type: ClaimType
    raw_value: str
    parsed_value: Any
    tex_anchor: SourceAnchor
    context_snippet: str = ""
    label: str = ""  # semantic tag, e.g. "accuracy", "learning rate"
    truth_value: Any | None = None
    truth_anchor: SourceAnchor | None = None
    status: Status = Status.UNVERIFIABLE
    detail: str = ""
    id: str = field(init=False)

    def __post_init__(self) -> None:
        key = f"{self.type.value}|{self.raw_value}|{self.tex_anchor.render()}|{self.label}"
        self.id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]

    def fingerprint(self) -> str:
        """Stable hash of the claim's source-side content (anchor + raw value).
        Used by the pre-commit hook to detect whether a claim changed."""
        key = f"{self.type.value}|{self.raw_value}|{self.label}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
