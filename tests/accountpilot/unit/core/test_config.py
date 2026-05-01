from __future__ import annotations

from pathlib import Path  # noqa: TC003 - used in test signatures

import pytest

from accountpilot.core.config import Config, load_config


def test_load_minimum_valid_config(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("""
version: 1
owners:
  - name: Aren
    surname: Eren
    identifiers:
      - { kind: email, value: aren@x.com }
plugins: {}
""")
    cfg = load_config(cfg_path)
    assert isinstance(cfg, Config)
    assert cfg.owners[0].name == "Aren"
    assert cfg.owners[0].identifiers[0].kind == "email"


def test_load_with_plugins(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("""
version: 1
owners:
  - name: Aren
    surname: null
    identifiers:
      - { kind: email, value: a@b.com }
plugins:
  mail:
    enabled: true
    accounts:
      - identifier: a@b.com
        owner: a@b.com
        provider: gmail
        credentials_ref: "op://x/y/z"
""")
    cfg = load_config(cfg_path)
    assert cfg.plugins["mail"].enabled is True
    assert cfg.plugins["mail"].accounts[0].provider == "gmail"


def test_invalid_version_rejected(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("version: 99\nowners: []\nplugins: {}\n")
    with pytest.raises(ValueError):
        load_config(cfg_path)


def test_unknown_identifier_kind_rejected(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("""
version: 1
owners:
  - name: A
    surname: null
    identifiers:
      - { kind: bogus, value: x }
plugins: {}
""")
    with pytest.raises(ValueError):
        load_config(cfg_path)
