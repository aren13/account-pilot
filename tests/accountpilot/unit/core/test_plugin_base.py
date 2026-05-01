from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import ClassVar

import pytest

from accountpilot.core.auth import Secrets
from accountpilot.core.plugin import AccountPilotPlugin


class _Dummy(AccountPilotPlugin):
    name: ClassVar[str] = "dummy"
    setup_called = False

    async def setup(self) -> None:
        type(self).setup_called = True

    async def backfill(self, account_id: int, *, since: datetime | None = None) -> None:
        return None

    async def sync_once(self, account_id: int) -> None:
        return None

    async def daemon(self, account_id: int) -> None:
        return None

    async def teardown(self) -> None:
        return None


async def test_plugin_subclass_with_all_hooks_instantiable() -> None:
    p = _Dummy(config={}, storage=None, secrets=Secrets({}))
    await p.setup()
    assert _Dummy.setup_called is True


def test_plugin_must_implement_all_abstract_methods() -> None:
    class _Incomplete(AccountPilotPlugin):
        name = "incomplete"

    with pytest.raises(TypeError):
        _Incomplete(config={}, storage=None, secrets=Secrets({}))  # type: ignore[abstract]


def test_secrets_get_returns_none_when_missing() -> None:
    s = Secrets({"a": "b"})
    assert s.get("a") == "b"
    assert s.get("missing") is None
