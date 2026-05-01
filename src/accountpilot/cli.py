"""AccountPilot CLI root.

Plugin-contributed subcommands are registered by iterating
`accountpilot.plugins` entry points and asking each plugin module for
its `<plugin_name>_group` Click group — no hard import needed here.

If a plugin's class is importable but its module doesn't expose a
`<name>_group`, the plugin loads for daemon/sync use but contributes
no CLI subcommand.
"""

from __future__ import annotations

import click

from accountpilot.core.cli.accounts_cmds import accounts_group
from accountpilot.core.cli.db_cmds import db_group
from accountpilot.core.cli.people_cmds import people_group
from accountpilot.core.cli.search_cmd import search_cmd
from accountpilot.core.cli.setup_cmd import setup_cmd
from accountpilot.core.cli.status_cmd import status_cmd
from accountpilot.core.plugin import discover_plugins


@click.group()
@click.version_option()
def cli() -> None:
    """AccountPilot — unified account sync framework."""


cli.add_command(db_group)
cli.add_command(search_cmd)
cli.add_command(status_cmd)
cli.add_command(people_group)
cli.add_command(accounts_group)
cli.add_command(setup_cmd)


def _register_plugin_clis() -> None:
    """Iterate accountpilot.plugins entry points and register each plugin's
    `<name>_group` Click group from its package's `.cli` module."""
    for _ep_name, plugin_cls in discover_plugins().items():
        try:
            # Plugin convention: package_path is plugin_cls.__module__.rsplit(".", 1)[0]
            # and the CLI lives at package_path + ".cli", exporting `<name>_group`.
            pkg = plugin_cls.__module__.rsplit(".", 1)[0]
            cli_module_name = f"{pkg}.cli"
            group_name = f"{plugin_cls.name}_group"
            cli_module = __import__(cli_module_name, fromlist=[group_name])
            grp = getattr(cli_module, group_name, None)
            if grp is not None:
                cli.add_command(grp)
        except (ImportError, AttributeError):
            # Plugin loads but contributes no CLI — that's allowed.
            pass


_register_plugin_clis()
