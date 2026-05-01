"""Tests for the IMAP IDLE listener."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from accountpilot.plugins.mail.imap.idle import IdleListener
from mailpilot.config import (
    AccountConfig,
    AuthConfig,
    FolderConfig,
    ImapConfig,
    SmtpConfig,
    SyncConfig,
)

# -------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------


@pytest.fixture
def sync_config() -> SyncConfig:
    """Return a SyncConfig with fast timeouts for testing."""
    return SyncConfig(
        idle_timeout=10,
        reconnect_base_delay=1,
        reconnect_max_delay=5,
        full_sync_interval=60,
    )


@pytest.fixture
def account_config() -> AccountConfig:
    """Return a minimal AccountConfig."""
    return AccountConfig(
        name="testacct",
        email="test@example.com",
        provider="custom",
        imap=ImapConfig(
            host="imap.example.com",
            port=993,
            encryption="tls",
            auth=AuthConfig(
                method="password",
                password_cmd="echo secret",
            ),
        ),
        smtp=SmtpConfig(
            host="smtp.example.com",
            port=587,
            encryption="starttls",
            auth=AuthConfig(
                method="password",
                password_cmd="echo secret",
            ),
        ),
        folders=FolderConfig(watch=["INBOX"]),
    )


@pytest.fixture
def mock_imap_client() -> AsyncMock:
    """Return a mock ImapClient."""
    client = AsyncMock()
    client.ensure_connected = AsyncMock()
    client.fetch_uids = AsyncMock(return_value=[1, 2, 3])
    client.disconnect = AsyncMock()
    client._connections = {}
    return client


@pytest.fixture
def mock_sync_engine() -> AsyncMock:
    """Return a mock SyncEngine."""
    engine = AsyncMock()
    engine.incremental_sync = AsyncMock(return_value=[])
    return engine


@pytest.fixture
def listener(
    mock_imap_client: AsyncMock,
    mock_sync_engine: AsyncMock,
    account_config: AccountConfig,
    sync_config: SyncConfig,
) -> IdleListener:
    """Return an IdleListener wired to mocks."""
    return IdleListener(
        imap_client=mock_imap_client,
        sync_engine=mock_sync_engine,
        account=account_config,
        folder="INBOX",
        config=sync_config,
    )


# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------


class TestIdleListener:
    """Unit tests for IdleListener."""

    def test_idle_is_running_default(
        self, listener: IdleListener
    ) -> None:
        """A freshly created listener must not be running."""
        assert listener.is_running is False

    @pytest.mark.asyncio
    async def test_idle_stop_clean(
        self, listener: IdleListener
    ) -> None:
        """Calling stop sets _running to False."""
        listener._running = True
        assert listener.is_running is True
        await listener.stop()
        assert listener.is_running is False

    def test_idle_callback_stored(
        self,
        mock_imap_client: AsyncMock,
        mock_sync_engine: AsyncMock,
        account_config: AccountConfig,
        sync_config: SyncConfig,
    ) -> None:
        """The on_new_mail callback is stored on the instance."""
        callback = MagicMock()
        idle = IdleListener(
            imap_client=mock_imap_client,
            sync_engine=mock_sync_engine,
            account=account_config,
            folder="INBOX",
            config=sync_config,
            on_new_mail=callback,
        )
        assert idle._on_new_mail is callback

    def test_idle_stores_folder(
        self, listener: IdleListener
    ) -> None:
        """The folder is stored correctly."""
        assert listener._folder == "INBOX"

    def test_idle_stores_account(
        self,
        listener: IdleListener,
        account_config: AccountConfig,
    ) -> None:
        """The account config is stored correctly."""
        assert listener._account is account_config

    @pytest.mark.asyncio
    async def test_idle_stop_disconnects_client(
        self,
        listener: IdleListener,
        mock_imap_client: AsyncMock,
    ) -> None:
        """Stop calls disconnect on the IMAP client."""
        listener._running = True
        await listener.stop()
        mock_imap_client.disconnect.assert_awaited_once_with(
            "INBOX"
        )
