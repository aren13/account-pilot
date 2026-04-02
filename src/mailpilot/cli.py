"""MailPilot CLI — Click-based command-line interface."""

import click

from mailpilot import __version__


@click.group()
@click.version_option(version=__version__, prog_name="mailpilot")
def cli() -> None:
    """MailPilot — Real-time email engine for AI agents."""
