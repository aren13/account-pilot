"""YAML config loader with Pydantic validation."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - used in load_config signature and body
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from accountpilot.core.models import (
    IdentifierKind,  # noqa: TC001 - used for Pydantic validation
)


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentifierEntry(_StrictBase):
    kind: IdentifierKind
    value: str


class OwnerEntry(_StrictBase):
    name: str
    surname: str | None = None
    identifiers: list[IdentifierEntry]


class AccountEntry(_StrictBase):
    identifier: str
    owner: str
    provider: Literal["gmail", "outlook", "imap-generic"] | None = None
    credentials_ref: str | None = None
    chat_db_path: str | None = None  # iMessage-specific


class PluginConfig(_StrictBase):
    enabled: bool = True
    accounts: list[AccountEntry] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class Config(_StrictBase):
    version: Literal[1]
    owners: list[OwnerEntry]
    plugins: dict[str, PluginConfig] = Field(default_factory=dict)


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text())
    try:
        return Config.model_validate(raw)
    except ValidationError as e:
        raise ValueError(f"invalid config at {path}: {e}") from e
