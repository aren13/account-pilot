"""Shared test fixtures for MailPilot."""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from mailpilot.config import MailPilotConfig, load_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def sample_config_yaml() -> str:
    """Return a valid minimal YAML config string."""
    return dedent("""\
        mailpilot:
          data_dir: "~/.mailpilot"
          log_level: "INFO"
          log_format: "json"

        accounts:
          - name: "test"
            email: "test@example.com"
            provider: "custom"

            imap:
              host: "imap.example.com"
              port: 993
              encryption: "tls"
              auth:
                method: "password"
                password_cmd: "echo test123"

            smtp:
              host: "smtp.example.com"
              port: 587
              encryption: "starttls"
              auth:
                method: "password"
                password_cmd: "echo test123"
    """)


@pytest.fixture
def tmp_config_dir(tmp_path: Path, sample_config_yaml: str) -> Path:
    """Create a temp directory with a valid config.yaml."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(sample_config_yaml, encoding="utf-8")
    return tmp_path


@pytest.fixture
def sample_config(tmp_config_dir: Path) -> MailPilotConfig:
    """Return a loaded MailPilotConfig from sample YAML."""
    return load_config(tmp_config_dir / "config.yaml")
