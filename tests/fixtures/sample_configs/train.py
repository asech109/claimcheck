"""Tiny stand-in for a training script — only PPO is actually implemented.

The paper claims PPO + GAE; this file deliberately omits GAE so the
method-drift detection has something to find.
"""

from torch import nn


class PPOAgent:
    """Proximal Policy Optimization agent (no GAE)."""

    def __init__(self):
        self.policy = nn.Sequential(
            nn.Linear(64, 128),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.ReLU(),
            nn.Linear(128, 4),
        )
