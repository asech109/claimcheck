from __future__ import annotations

import re
from dataclasses import dataclass, field

# Known algorithm / technique tokens. Match is case-insensitive.
_KNOWN_ALGORITHMS = {
    "ppo", "dqn", "a2c", "a3c", "sac", "td3", "ddpg", "trpo", "reinforce",
    "gae", "mcts", "alphazero", "muzero",
    "transformer", "bert", "gpt", "llama", "lstm", "gru", "rnn", "cnn", "mlp",
    "resnet", "vit", "unet", "vae", "gan",
    "adam", "adamw", "sgd", "rmsprop", "lion",
    "lora", "qlora", "rlhf", "dpo", "kto",
    "softmax", "relu", "gelu", "silu", "swiglu", "layernorm", "batchnorm",
    "cross-entropy", "mse", "kl-divergence",
}

# Architecture descriptors like "3-layer MLP", "12-head transformer".
_ARCH_RE = re.compile(
    r"(\d+)[\s-]+(layer|head|block|hidden|dim|filter)\w*\s+([A-Za-z][A-Za-z0-9\-]+)",
    re.IGNORECASE,
)


@dataclass
class MethodFingerprint:
    algorithms: set[str] = field(default_factory=set)
    architecture: list[tuple[int, str, str]] = field(default_factory=list)  # (count, unit, type)
    raw_tokens: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {
            "algorithms": sorted(self.algorithms),
            "architecture": [list(a) for a in self.architecture],
        }


def parse_method_description(text: str) -> MethodFingerprint:
    """Extract structured fingerprint from a natural-language method description.

    Returns sets of algorithm tokens + architecture descriptors. Anything not
    matched falls into raw_tokens and is ignored for drift detection (we do not
    fabricate semantic matches)."""
    fp = MethodFingerprint()
    lowered = text.lower()
    # Algorithm hits — word-boundary search so "gae" doesn't match "page".
    for algo in _KNOWN_ALGORITHMS:
        pattern = re.escape(algo)
        if re.search(rf"(?<![A-Za-z]){pattern}(?![A-Za-z])", lowered):
            fp.algorithms.add(algo)
    # Architecture descriptors.
    for m in _ARCH_RE.finditer(text):
        count = int(m.group(1))
        unit = m.group(2).lower()
        kind = m.group(3).lower()
        fp.architecture.append((count, unit, kind))
    return fp


def diff_fingerprints(
    paper_fp: MethodFingerprint, code_fp: MethodFingerprint
) -> dict[str, list]:
    """Return components present in paper but missing from code, and vice versa.

    Only reports differences for fields populated on both sides; an empty
    code_fp means we couldn't extract anything from code and yields
    unverifiable rather than drift."""
    missing_in_code = sorted(paper_fp.algorithms - code_fp.algorithms)
    extra_in_code = sorted(code_fp.algorithms - paper_fp.algorithms)
    arch_diff_paper = [a for a in paper_fp.architecture if a not in code_fp.architecture]
    arch_diff_code = [a for a in code_fp.architecture if a not in paper_fp.architecture]
    return {
        "algorithms_in_paper_not_code": missing_in_code,
        "algorithms_in_code_not_paper": extra_in_code,
        "architecture_in_paper_not_code": arch_diff_paper,
        "architecture_in_code_not_paper": arch_diff_code,
    }
