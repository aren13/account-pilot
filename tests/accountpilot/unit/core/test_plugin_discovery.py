from __future__ import annotations

from accountpilot.core.plugin import AccountPilotPlugin, discover_plugins


def test_mail_plugin_is_discoverable() -> None:
    plugins = discover_plugins()
    assert "mail" in plugins
    cls = plugins["mail"]
    assert issubclass(cls, AccountPilotPlugin)
    assert cls.name == "mail"
