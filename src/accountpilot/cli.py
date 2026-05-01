"""AccountPilot CLI root.

Subcommands are registered in this module. Plugin-contributed subcommands are
registered after entry-point discovery in core.plugin.load_plugins().
"""

import click


@click.group()
@click.version_option()
def cli() -> None:
    """AccountPilot — unified account sync framework."""


# Subcommand registrations are added in later tasks (db, people, accounts,
# setup, status, search).
