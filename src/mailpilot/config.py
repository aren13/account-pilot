"""MailPilot configuration system — Pydantic v2 models and YAML loader."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ConfigError(Exception):
    """Raised when configuration is invalid or password resolution fails."""


class AuthConfig(BaseModel):
    """Authentication configuration for IMAP/SMTP connections."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["password", "oauth2"] = "password"
    password_cmd: str | None = None
    client_id: str | None = None
    client_secret: str | None = None


class ImapConfig(BaseModel):
    """IMAP server configuration."""

    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = 993
    encryption: Literal["tls", "starttls", "none"] = "tls"
    auth: AuthConfig


class SmtpConfig(BaseModel):
    """SMTP server configuration."""

    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = 587
    encryption: Literal["tls", "starttls", "none"] = "starttls"
    auth: AuthConfig


class FolderConfig(BaseModel):
    """Folder watch and sync configuration."""

    model_config = ConfigDict(extra="forbid")

    watch: list[str] = Field(default_factory=lambda: ["INBOX"])
    sync: list[str] = Field(default_factory=lambda: ["INBOX"])
    aliases: dict[str, str] = Field(default_factory=dict)


class AccountConfig(BaseModel):
    """Configuration for a single email account."""

    model_config = ConfigDict(extra="forbid")

    name: str
    email: str
    display_name: str | None = None
    provider: Literal["gmail", "outlook", "custom"] = "custom"
    imap: ImapConfig
    smtp: SmtpConfig
    folders: FolderConfig = Field(default_factory=FolderConfig)
    webhook_url: str | None = None


class SearchConfig(BaseModel):
    """Xapian search engine configuration."""

    model_config = ConfigDict(extra="forbid")

    stemming: str = "english"
    spelling: bool = True
    snippet_length: int = 200
    default_limit: int = 20


class SyncConfig(BaseModel):
    """IMAP sync and IDLE configuration."""

    model_config = ConfigDict(extra="forbid")

    idle_timeout: int = 1680
    reconnect_base_delay: int = 5
    reconnect_max_delay: int = 300
    full_sync_interval: int = 3600
    max_message_size: int = 52428800


class RuleAction(BaseModel):
    """Action to apply when a rule matches (e.g., '+tag' or '-tag')."""

    model_config = ConfigDict(extra="forbid")

    tag: str


class RuleConfig(BaseModel):
    """Auto-tagging rule configuration."""

    model_config = ConfigDict(extra="forbid")

    name: str
    match: str
    actions: list[RuleAction]


class MailPilotGlobalConfig(BaseModel):
    """Global MailPilot settings."""

    model_config = ConfigDict(extra="forbid")

    data_dir: str = "~/.mailpilot"
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    log_file: str | None = None


class MailPilotConfig(BaseModel):
    """Root configuration model for MailPilot."""

    model_config = ConfigDict(extra="forbid")

    mailpilot: MailPilotGlobalConfig = Field(
        default_factory=MailPilotGlobalConfig
    )
    accounts: list[AccountConfig]
    search: SearchConfig = Field(default_factory=SearchConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    rules: list[RuleConfig] = Field(default_factory=list)


def _expand_paths(config: MailPilotConfig) -> MailPilotConfig:
    """Expand ~ in all path fields."""
    config.mailpilot.data_dir = str(
        Path(config.mailpilot.data_dir).expanduser()
    )
    if config.mailpilot.log_file is not None:
        config.mailpilot.log_file = str(
            Path(config.mailpilot.log_file).expanduser()
        )
    return config


def load_config(path: Path | None = None) -> MailPilotConfig:
    """Load and validate MailPilot configuration from a YAML file.

    Args:
        path: Path to config file. Defaults to ~/.mailpilot/config.yaml.

    Returns:
        Validated MailPilotConfig instance with expanded paths.

    Raises:
        ConfigError: If the file cannot be read or parsed.
        pydantic.ValidationError: If the config fails validation.
    """
    if path is None:
        path = Path("~/.mailpilot/config.yaml").expanduser()

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read config file: {path}: {exc}") from exc

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(data, dict):
        actual = type(data).__name__
        raise ConfigError(
            f"Config file must contain a YAML mapping, got {actual}"
        )

    config = MailPilotConfig.model_validate(data)
    return _expand_paths(config)


def resolve_password(auth: AuthConfig) -> str:
    """Resolve password from password_cmd.

    Runs the shell command specified in auth.password_cmd and returns
    the stripped stdout. Never stores the result on the config object.

    Args:
        auth: AuthConfig with password_cmd set.

    Returns:
        The resolved password string.

    Raises:
        ConfigError: If method is not 'password', password_cmd is not set,
            the command fails, or it returns empty output.
    """
    if auth.method != "password":
        raise ConfigError(
            f"Cannot resolve password: auth method is '{auth.method}', not 'password'"
        )

    if not auth.password_cmd:
        raise ConfigError("password_cmd is not set in auth config")

    result = subprocess.run(
        auth.password_cmd,
        shell=True,  # noqa: S602
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise ConfigError(
            f"password_cmd failed (exit {result.returncode}): {stderr}"
        )

    password = result.stdout.strip()
    if not password:
        raise ConfigError("password_cmd returned empty output")

    return password
