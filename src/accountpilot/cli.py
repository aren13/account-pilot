"""AccountPilot CLI root."""

import click

from accountpilot.core.cli.accounts_cmds import accounts_group
from accountpilot.core.cli.db_cmds import db_group
from accountpilot.core.cli.people_cmds import people_group
from accountpilot.core.cli.search_cmd import search_cmd
from accountpilot.core.cli.setup_cmd import setup_cmd
from accountpilot.core.cli.status_cmd import status_cmd
from accountpilot.plugins.mail.cli import mail_group


@click.group()
@click.version_option()
def cli() -> None:
    """AccountPilot — unified account sync framework."""


cli.add_command(accounts_group)
cli.add_command(db_group)
cli.add_command(people_group)
cli.add_command(search_cmd)
cli.add_command(setup_cmd)
cli.add_command(status_cmd)
cli.add_command(mail_group)
