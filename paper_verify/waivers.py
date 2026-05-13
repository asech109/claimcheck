from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_TTL_DAYS = 30
WAIVER_FILENAME = "claims_waived.yaml"


@dataclass
class Waiver:
    claim_id: str
    reason: str
    expires: _dt.date

    def is_active(self, today: _dt.date | None = None) -> bool:
        today = today or _dt.date.today()
        return today <= self.expires

    def to_dict(self) -> dict:
        return {"claim_id": self.claim_id, "reason": self.reason, "expires": self.expires.isoformat()}


def waiver_path(repo_root: Path) -> Path:
    return repo_root / ".paper-verify" / WAIVER_FILENAME


def load_waivers(repo_root: Path) -> dict[str, Waiver]:
    path = waiver_path(repo_root)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    waivers: dict[str, Waiver] = {}
    for entry in data.get("waivers", []):
        try:
            expires = _dt.date.fromisoformat(str(entry["expires"]))
        except (KeyError, ValueError):
            continue
        cid = str(entry.get("claim_id", "")).strip()
        if not cid:
            continue
        waivers[cid] = Waiver(claim_id=cid, reason=str(entry.get("reason", "")), expires=expires)
    return waivers


def save_waivers(repo_root: Path, waivers: dict[str, Waiver]) -> Path:
    path = waiver_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"waivers": [w.to_dict() for w in waivers.values()]}
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def add_waiver(repo_root: Path, claim_id: str, reason: str, ttl_days: int = DEFAULT_TTL_DAYS) -> Waiver:
    waivers = load_waivers(repo_root)
    expires = _dt.date.today() + _dt.timedelta(days=ttl_days)
    w = Waiver(claim_id=claim_id, reason=reason, expires=expires)
    waivers[claim_id] = w
    save_waivers(repo_root, waivers)
    return w


def active_waivers(repo_root: Path) -> set[str]:
    return {cid for cid, w in load_waivers(repo_root).items() if w.is_active()}
