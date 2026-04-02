"""MailPilot event system — types and emitter."""

from __future__ import annotations

from mailpilot.events.emitter import EventEmitter
from mailpilot.events.types import EventType

__all__ = ["EventEmitter", "EventType"]
