"""Synthetic test plugin: emits one canned email and one canned iMessage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from accountpilot.core.auth import Secrets  # noqa: TC001
from accountpilot.core.models import (
    AttachmentBlob,
    EmailMessage,
    IMessageMessage,
)
from accountpilot.core.plugin import AccountPilotPlugin


class SyntheticPlugin(AccountPilotPlugin):
    name: ClassVar[str] = "synthetic"

    def __init__(
        self,
        *,
        config: dict[str, Any],
        storage: Any,
        secrets: Secrets,
        mail_account_id: int,
        imessage_account_id: int,
    ) -> None:
        super().__init__(config=config, storage=storage, secrets=secrets)
        self._mail_account_id = mail_account_id
        self._imessage_account_id = imessage_account_id

    async def setup(self) -> None:
        return None

    async def backfill(self, account_id: int, *, since: datetime | None = None) -> None:
        await self.sync_once(account_id)

    async def sync_once(self, account_id: int) -> None:
        if account_id == self._mail_account_id:
            await self.storage.save_email(EmailMessage(
                account_id=account_id,
                external_id="<synthetic-1@example.com>",
                sent_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
                received_at=datetime(2026, 5, 1, 12, 0, 5, tzinfo=UTC),
                direction="inbound",
                from_address="Synthetic Sender <synth@example.com>",
                to_addresses=["aren@x.com"],
                cc_addresses=[],
                bcc_addresses=[],
                subject="Synthetic Subject",
                body_text="this is a synthetic message body",
                body_html=None,
                in_reply_to=None,
                references=[],
                imap_uid=1,
                mailbox="INBOX",
                gmail_thread_id=None,
                labels=["INBOX"],
                raw_headers={"Subject": "Synthetic Subject"},
                attachments=[
                    AttachmentBlob(
                        filename="attached.txt",
                        content=b"synthetic attachment bytes",
                        mime_type="text/plain",
                    )
                ],
            ))
        elif account_id == self._imessage_account_id:
            await self.storage.save_imessage(IMessageMessage(
                account_id=account_id,
                external_id="GUID-SYNTH-1",
                sent_at=datetime(2026, 5, 1, 13, 0, tzinfo=UTC),
                direction="inbound",
                sender_handle="+15559876543",
                chat_guid="chat-synth",
                participants=["+15551234567", "+15559876543"],
                body_text="synthetic imessage body",
                service="iMessage",
                is_read=True,
                date_read=None,
                attachments=[],
            ))

    async def daemon(self, account_id: int) -> None:
        return None

    async def teardown(self) -> None:
        return None
