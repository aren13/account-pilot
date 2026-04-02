"""Tests for the MailPilot IMAP client provider layer."""

from __future__ import annotations

from mailpilot.providers import Provider, get_provider
from mailpilot.providers.gmail import GmailProvider
from mailpilot.providers.outlook import OutlookProvider


class TestGetProvider:
    """Test the get_provider factory function."""

    def test_get_provider_gmail(self) -> None:
        provider = get_provider("gmail")
        assert isinstance(provider, GmailProvider)

    def test_get_provider_outlook(self) -> None:
        provider = get_provider("outlook")
        assert isinstance(provider, OutlookProvider)

    def test_get_provider_custom(self) -> None:
        provider = get_provider("custom")
        assert isinstance(provider, Provider)
        # Should NOT be a subclass instance
        assert type(provider) is Provider


class TestGmailFolderAliases:
    """Test Gmail provider folder aliases resolve correctly."""

    def test_gmail_sent_folder(self) -> None:
        provider = get_provider("gmail")
        assert provider.sent_folder == "[Gmail]/Sent Mail"

    def test_gmail_trash_folder(self) -> None:
        provider = get_provider("gmail")
        assert provider.trash_folder == "[Gmail]/Trash"

    def test_gmail_drafts_alias(self) -> None:
        provider = get_provider("gmail")
        assert provider.folder_alias("drafts") == "[Gmail]/Drafts"

    def test_gmail_spam_alias(self) -> None:
        provider = get_provider("gmail")
        assert provider.folder_alias("spam") == "[Gmail]/Spam"

    def test_gmail_archive_alias(self) -> None:
        provider = get_provider("gmail")
        assert provider.folder_alias("archive") == "[Gmail]/All Mail"

    def test_gmail_unknown_folder_passthrough(self) -> None:
        provider = get_provider("gmail")
        assert provider.folder_alias("INBOX") == "INBOX"


class TestOutlookFolderAliases:
    """Test Outlook provider folder aliases resolve correctly."""

    def test_outlook_sent_folder(self) -> None:
        provider = get_provider("outlook")
        assert provider.sent_folder == "Sent Items"

    def test_outlook_trash_folder(self) -> None:
        provider = get_provider("outlook")
        assert provider.trash_folder == "Deleted Items"

    def test_outlook_drafts_alias(self) -> None:
        provider = get_provider("outlook")
        assert provider.folder_alias("drafts") == "Drafts"

    def test_outlook_spam_alias(self) -> None:
        provider = get_provider("outlook")
        assert provider.folder_alias("spam") == "Junk Email"

    def test_outlook_archive_alias(self) -> None:
        provider = get_provider("outlook")
        assert provider.folder_alias("archive") == "Archive"

    def test_outlook_unknown_folder_passthrough(self) -> None:
        provider = get_provider("outlook")
        assert provider.folder_alias("INBOX") == "INBOX"


class TestCustomProviderPassthrough:
    """Test custom provider returns folder names unchanged."""

    def test_custom_sent_passthrough(self) -> None:
        provider = get_provider("custom")
        assert provider.folder_alias("sent") == "sent"

    def test_custom_trash_passthrough(self) -> None:
        provider = get_provider("custom")
        assert provider.folder_alias("trash") == "trash"

    def test_custom_arbitrary_passthrough(self) -> None:
        provider = get_provider("custom")
        assert provider.folder_alias("MyCustomFolder") == "MyCustomFolder"

    def test_custom_case_insensitive_lookup(self) -> None:
        provider = get_provider("custom")
        assert provider.folder_alias("SENT") == "SENT"

    def test_custom_inbox_passthrough(self) -> None:
        provider = get_provider("custom")
        assert provider.folder_alias("INBOX") == "INBOX"
