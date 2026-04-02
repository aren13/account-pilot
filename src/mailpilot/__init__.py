"""MailPilot — Real-time email engine for AI agents."""

__version__ = "0.1.0"


class MailPilot:
    """Main MailPilot application class.

    Provides a unified interface for email operations including
    IMAP sync, search, send, and management.
    """

    def __init__(self) -> None:
        self.version = __version__
