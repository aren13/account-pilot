from __future__ import annotations

import pytest
from pydantic import ValidationError

from accountpilot.plugins.mail.config import (
    MailAccountConfig,
    MailPluginConfig,
)


def test_account_minimum_fields() -> None:
    a = MailAccountConfig(
        identifier="aren@example.com",
        owner="aren@example.com",
        provider="gmail",
        credentials_ref="password_cmd:op read op://Personal/gmail/password",
    )
    assert a.identifier == "aren@example.com"
    assert a.provider == "gmail"
    assert a.auth_method == "password"


def test_account_oauth_method() -> None:
    a = MailAccountConfig(
        identifier="aren@outlook.com",
        owner="aren@outlook.com",
        provider="outlook",
        auth_method="oauth",
        credentials_ref=None,
    )
    assert a.auth_method == "oauth"


def test_account_rejects_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        MailAccountConfig(
            identifier="x@y", owner="x@y",
            provider="aol",  # type: ignore[arg-type]
            credentials_ref=None,
        )


def test_plugin_default_idle_timeout() -> None:
    cfg = MailPluginConfig(accounts=[])
    assert cfg.idle_timeout_seconds == 1740
    assert cfg.batch_size == 100


def test_plugin_overrides() -> None:
    cfg = MailPluginConfig(
        accounts=[],
        idle_timeout_seconds=600,
        batch_size=50,
    )
    assert cfg.idle_timeout_seconds == 600
    assert cfg.batch_size == 50
