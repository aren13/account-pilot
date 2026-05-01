"""AccountPilot CLI root."""

import click

from accountpilot.core.cli.db_cmds import db_group


@click.group()
@click.version_option()
def cli() -> None:
    """AccountPilot — unified account sync framework."""


cli.add_command(db_group)
