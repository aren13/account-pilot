"""Tests for the MailPilot daemon orchestrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mailpilot.config import (
    AccountConfig,
    AuthConfig,
    FolderConfig,
    ImapConfig,
    MailPilotConfig,
    MailPilotGlobalConfig,
    SmtpConfig,
    SyncConfig,
)
from mailpilot.daemon import MailPilotDaemon

# -------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------


@pytest.fixture
def daemon_config(tmp_path: Path) -> MailPilotConfig:
    """Return a MailPilotConfig pointing at a temp data dir."""
    return MailPilotConfig(
        mailpilot=MailPilotGlobalConfig(
            data_dir=str(tmp_path / "mailpilot"),
            log_level="DEBUG",
        ),
        accounts=[
            AccountConfig(
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
                folders=FolderConfig(
                    watch=["INBOX"],
                    sync=["INBOX"],
                ),
            ),
        ],
        sync=SyncConfig(
            idle_timeout=10,
            reconnect_base_delay=1,
            reconnect_max_delay=5,
            full_sync_interval=60,
        ),
    )


# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------


class TestMailPilotDaemon:
    """Unit tests for MailPilotDaemon."""

    def test_daemon_init(
        self, daemon_config: MailPilotConfig
    ) -> None:
        """Verify the config is stored and initial state is empty."""
        daemon = MailPilotDaemon(daemon_config)
        assert daemon.config is daemon_config
        assert daemon._db is None
        assert daemon._clients == {}
        assert daemon._listeners == {}

    @pytest.mark.asyncio
    async def test_daemon_status_structure(
        self, daemon_config: MailPilotConfig
    ) -> None:
        """Status dict has the expected keys before start."""
        daemon = MailPilotDaemon(daemon_config)
        st = await daemon.status()
        assert "accounts" in st
        assert "listeners" in st
        assert "uptime_seconds" in st
        assert "database_ready" in st
        assert st["database_ready"] is False
        assert st["uptime_seconds"] == 0.0

    def test_daemon_config_accounts(
        self, daemon_config: MailPilotConfig
    ) -> None:
        """Daemon exposes the account list from config."""
        daemon = MailPilotDaemon(daemon_config)
        names = [a.name for a in daemon.config.accounts]
        assert names == ["testacct"]

    @pytest.mark.asyncio
    async def test_daemon_start_and_stop(
        self,
        daemon_config: MailPilotConfig,
        tmp_path: Path,
    ) -> None:
        """Start and stop with mocked IMAP; verify lifecycle."""
        daemon = MailPilotDaemon(daemon_config)

        mock_engine = AsyncMock()
        mock_engine.sync_account = AsyncMock()

        with (
            patch(
                "mailpilot.daemon.ImapClient",
                return_value=AsyncMock(),
            ),
            patch(
                "mailpilot.daemon.SyncEngine",
                return_value=mock_engine,
            ),
            patch(
                "mailpilot.daemon.IdleListener",
            ) as mock_idle_cls,
        ):
            mock_listener = AsyncMock()
            mock_listener.run = AsyncMock()
            mock_listener.stop = AsyncMock()
            mock_listener.is_running = True
            mock_idle_cls.return_value = mock_listener

            await daemon.start()

            # Database should be initialized
            assert daemon._db is not None

            # PID file written
            pid_path = (
                Path(daemon_config.mailpilot.data_dir)
                / "daemon.pid"
            )
            assert pid_path.exists()

            st = await daemon.status()
            assert st["database_ready"] is True
            assert st["uptime_seconds"] >= 0

            await daemon.stop()

            assert daemon._db is None
            assert daemon._clients == {}

    @pytest.mark.asyncio
    async def test_daemon_stop_removes_pid(
        self,
        daemon_config: MailPilotConfig,
        tmp_path: Path,
    ) -> None:
        """After stop, the PID file is removed."""
        daemon = MailPilotDaemon(daemon_config)

        mock_engine = AsyncMock()
        mock_engine.sync_account = AsyncMock()

        with (
            patch(
                "mailpilot.daemon.ImapClient",
                return_value=AsyncMock(),
            ),
            patch(
                "mailpilot.daemon.SyncEngine",
                return_value=mock_engine,
            ),
            patch(
                "mailpilot.daemon.IdleListener",
            ) as mock_idle_cls,
        ):
            mock_listener = AsyncMock()
            mock_listener.run = AsyncMock()
            mock_listener.stop = AsyncMock()
            mock_listener.is_running = False
            mock_idle_cls.return_value = mock_listener

            await daemon.start()
            pid_path = (
                Path(daemon_config.mailpilot.data_dir)
                / "daemon.pid"
            )
            assert pid_path.exists()

            await daemon.stop()
            assert not pid_path.exists()
