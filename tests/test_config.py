"""Tests for the MailPilot config system."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from mailpilot.config import (
    AuthConfig,
    ConfigError,
    MailPilotConfig,
    load_config,
    resolve_password,
)


class TestLoadValidConfig:
    """Test loading a valid configuration file."""

    def test_load_valid_config(self, tmp_path: Path) -> None:
        """Load config.example.yaml with mocked password_cmd and assert all fields."""
        example = Path(__file__).parent.parent / "config.example.yaml"
        config = load_config(example)

        assert len(config.accounts) == 2
        assert config.accounts[0].name == "personal"
        assert config.accounts[0].email == "you@gmail.com"
        assert config.accounts[0].display_name == "Your Name"
        assert config.accounts[0].provider == "gmail"

        # IMAP
        assert config.accounts[0].imap.host == "imap.gmail.com"
        assert config.accounts[0].imap.port == 993
        assert config.accounts[0].imap.encryption == "tls"
        assert config.accounts[0].imap.auth.method == "password"
        assert config.accounts[0].imap.auth.password_cmd is not None

        # SMTP
        assert config.accounts[0].smtp.host == "smtp.gmail.com"
        assert config.accounts[0].smtp.port == 587
        assert config.accounts[0].smtp.encryption == "starttls"

        # Folders
        assert "INBOX" in config.accounts[0].folders.watch
        assert "INBOX" in config.accounts[0].folders.sync
        assert config.accounts[0].folders.aliases["sent"] == "[Gmail]/Sent Mail"

        # Second account (OAuth2)
        assert config.accounts[1].name == "work"
        assert config.accounts[1].imap.auth.method == "oauth2"
        assert config.accounts[1].imap.auth.client_id == "your-client-id"

        # Search
        assert config.search.stemming == "english"
        assert config.search.spelling is True
        assert config.search.snippet_length == 200
        assert config.search.default_limit == 20

        # Sync
        assert config.sync.idle_timeout == 1680
        assert config.sync.reconnect_base_delay == 5
        assert config.sync.reconnect_max_delay == 300
        assert config.sync.full_sync_interval == 3600
        assert config.sync.max_message_size == 52428800

        # Rules
        assert len(config.rules) == 2
        assert config.rules[0].name == "tag-github"
        assert config.rules[0].match == "from:notifications@github.com"
        assert config.rules[0].actions[0].tag == "+github"


class TestDefaultValues:
    """Test default values with a minimal configuration."""

    def test_default_values(self, sample_config: MailPilotConfig) -> None:
        """Minimal config with one account should use defaults for search, sync, etc."""
        assert sample_config.search.stemming == "english"
        assert sample_config.search.spelling is True
        assert sample_config.search.snippet_length == 200
        assert sample_config.search.default_limit == 20

        assert sample_config.sync.idle_timeout == 1680
        assert sample_config.sync.reconnect_base_delay == 5
        assert sample_config.sync.reconnect_max_delay == 300
        assert sample_config.sync.full_sync_interval == 3600
        assert sample_config.sync.max_message_size == 52428800

        assert sample_config.rules == []

        # Account folder defaults
        assert sample_config.accounts[0].folders.watch == ["INBOX"]
        assert sample_config.accounts[0].folders.sync == ["INBOX"]
        assert sample_config.accounts[0].folders.aliases == {}

        assert sample_config.accounts[0].webhook_url is None
        assert sample_config.accounts[0].display_name is None

    def test_default_global_config(self, sample_config: MailPilotConfig) -> None:
        """Global config defaults should be applied."""
        assert sample_config.mailpilot.log_level == "INFO"
        assert sample_config.mailpilot.log_format == "json"
        assert sample_config.mailpilot.log_file is None


class TestValidationErrors:
    """Test that invalid configurations raise appropriate errors."""

    def test_missing_required_fields(self, tmp_path: Path) -> None:
        """Config without accounts raises ValidationError."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            dedent("""\
                mailpilot:
                  data_dir: "~/.mailpilot"
            """),
            encoding="utf-8",
        )

        with pytest.raises(ValidationError, match="accounts"):
            load_config(config_file)

    def test_invalid_provider(self, tmp_path: Path) -> None:
        """Provider 'yahoo' raises ValidationError (not in Literal)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            dedent("""\
                accounts:
                  - name: "bad"
                    email: "bad@example.com"
                    provider: "yahoo"
                    imap:
                      host: "imap.example.com"
                      auth:
                        method: "password"
                    smtp:
                      host: "smtp.example.com"
                      auth:
                        method: "password"
            """),
            encoding="utf-8",
        )

        with pytest.raises(ValidationError, match="provider"):
            load_config(config_file)

    def test_extra_fields_rejected(self, tmp_path: Path) -> None:
        """Config with unknown fields raises ValidationError."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            dedent("""\
                accounts:
                  - name: "test"
                    email: "test@example.com"
                    imap:
                      host: "imap.example.com"
                      auth:
                        method: "password"
                    smtp:
                      host: "smtp.example.com"
                      auth:
                        method: "password"
                    unknown_field: "should fail"
            """),
            encoding="utf-8",
        )

        with pytest.raises(ValidationError, match="unknown_field"):
            load_config(config_file)


class TestPasswordResolution:
    """Test password_cmd resolution."""

    def test_password_cmd_resolution(self) -> None:
        """Mock subprocess, verify password resolved correctly."""
        auth = AuthConfig(method="password", password_cmd="echo test123")
        password = resolve_password(auth)
        assert password == "test123"

    def test_password_cmd_failure(self) -> None:
        """Mock subprocess returning error, verify ConfigError raised."""
        auth = AuthConfig(method="password", password_cmd="false")

        with pytest.raises(ConfigError, match="password_cmd failed"):
            resolve_password(auth)

    def test_password_cmd_empty_output(self) -> None:
        """password_cmd returning empty output raises ConfigError."""
        auth = AuthConfig(method="password", password_cmd="printf ''")

        with pytest.raises(ConfigError, match="password_cmd returned empty"):
            resolve_password(auth)

    def test_password_cmd_not_set(self) -> None:
        """password_cmd not set raises ConfigError."""
        auth = AuthConfig(method="password")

        with pytest.raises(ConfigError, match="password_cmd is not set"):
            resolve_password(auth)

    def test_resolve_password_wrong_method(self) -> None:
        """Calling resolve_password with oauth2 method raises ConfigError."""
        auth = AuthConfig(method="oauth2")

        with pytest.raises(ConfigError, match="not 'password'"):
            resolve_password(auth)


class TestPathExpansion:
    """Test ~ expansion in paths."""

    def test_path_expansion(self, tmp_path: Path) -> None:
        """Verify ~ in data_dir expands to home directory."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            dedent("""\
                mailpilot:
                  data_dir: "~/mailpilot-data"
                  log_file: "~/logs/mailpilot.log"
                accounts:
                  - name: "test"
                    email: "test@example.com"
                    imap:
                      host: "imap.example.com"
                      auth:
                        method: "password"
                    smtp:
                      host: "smtp.example.com"
                      auth:
                        method: "password"
            """),
            encoding="utf-8",
        )

        config = load_config(config_file)
        home = str(Path.home())

        assert config.mailpilot.data_dir.startswith(home)
        assert "~" not in config.mailpilot.data_dir
        assert config.mailpilot.log_file is not None
        assert config.mailpilot.log_file.startswith(home)
        assert "~" not in config.mailpilot.log_file


class TestConfigFileErrors:
    """Test error handling for config file loading."""

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Loading a non-existent config file raises ConfigError."""
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        """Loading invalid YAML raises ConfigError."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(":\n  :\n  - [invalid", encoding="utf-8")

        with pytest.raises(ConfigError, match="Invalid YAML"):
            load_config(config_file)
