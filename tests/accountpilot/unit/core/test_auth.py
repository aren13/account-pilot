from __future__ import annotations

import pytest

from accountpilot.core.auth import Secrets


def test_get_returns_literal_value() -> None:
    s = Secrets({"a": "literal"})
    assert s.get("a") == "literal"


def test_get_returns_none_for_missing_key() -> None:
    s = Secrets({})
    assert s.get("missing") is None


def test_get_with_default_returns_default() -> None:
    s = Secrets({})
    assert s.get("missing", "fallback") == "fallback"


def test_resolve_literal_passes_through() -> None:
    assert Secrets.resolve("plain-string") == "plain-string"


def test_resolve_password_cmd_runs_shell_and_returns_stripped_stdout() -> None:
    assert Secrets.resolve("password_cmd:echo hello") == "hello"


def test_resolve_password_cmd_strips_trailing_newline() -> None:
    assert Secrets.resolve("password_cmd:printf 'abc\\n'") == "abc"


def test_resolve_password_cmd_propagates_nonzero_exit() -> None:
    with pytest.raises(RuntimeError) as exc:
        Secrets.resolve("password_cmd:false")
    assert "exit" in str(exc.value).lower()
