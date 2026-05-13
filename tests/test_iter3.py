"""Tests for iter3 UX additions: --version, status command, waive --list,
friendly path errors."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from paper_verify.cli import build_parser, main

FIX = Path(__file__).parent / "fixtures"


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "claimcheck" in out
    assert "0.1.0" in out


def test_status_command_returns_one_when_drift(tmp_path, capsys):
    code = main([
        "status",
        str(FIX / "sample.tex"),
        "--code-root", str(FIX / "sample_configs"),
        "--logs", str(FIX / "sample_logs"),
    ])
    out = capsys.readouterr().out
    assert "claims" in out
    assert code == 1  # there is a known mismatch in the fixture


def test_waive_list_empty(tmp_path, capsys):
    code = main(["waive", "--list", "--repo", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "no waivers" in out


def test_waive_list_shows_active(tmp_path, capsys):
    main(["waive", "abc123", "--reason", "demo", "--ttl", "5", "--repo", str(tmp_path)])
    capsys.readouterr()  # discard add output
    main(["waive", "--list", "--repo", str(tmp_path)])
    out = capsys.readouterr().out
    assert "abc123" in out
    assert "demo" in out
    assert "active" in out


def test_friendly_error_when_logs_path_missing(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main([
            "scan",
            str(FIX / "sample.tex"),
            "--code-root", str(FIX / "sample_configs"),
            "--logs", str(tmp_path / "does-not-exist"),
        ])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--logs" in err
    assert "does not exist" in err
