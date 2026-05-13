import datetime as dt
from pathlib import Path

from paper_verify.waivers import (
    Waiver,
    active_waivers,
    add_waiver,
    load_waivers,
    save_waivers,
    waiver_path,
)


def test_add_and_load_roundtrip(tmp_path: Path):
    w = add_waiver(tmp_path, claim_id="abc123", reason="log delayed", ttl_days=7)
    assert w.is_active()
    assert waiver_path(tmp_path).exists()

    loaded = load_waivers(tmp_path)
    assert "abc123" in loaded
    assert loaded["abc123"].reason == "log delayed"


def test_expired_waiver_not_active(tmp_path: Path):
    expired = Waiver(claim_id="zz", reason="old", expires=dt.date.today() - dt.timedelta(days=1))
    save_waivers(tmp_path, {"zz": expired})
    assert "zz" not in active_waivers(tmp_path)


def test_active_waiver_listed(tmp_path: Path):
    fresh = Waiver(claim_id="ok", reason="pending", expires=dt.date.today() + dt.timedelta(days=5))
    save_waivers(tmp_path, {"ok": fresh})
    assert "ok" in active_waivers(tmp_path)
