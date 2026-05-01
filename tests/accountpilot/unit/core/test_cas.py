from __future__ import annotations

import hashlib
from pathlib import Path  # noqa: TC003 (used at runtime in fixture signatures)

from accountpilot.core.cas import CASStore


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_write_returns_hash_and_relative_path(tmp_runtime: Path) -> None:
    cas = CASStore(tmp_runtime / "attachments")
    content = b"hello world"
    h, rel = cas.write(content)
    assert h == _sha256(content)
    assert rel == f"{h[:2]}/{h[2:4]}/{h}.bin"
    assert (tmp_runtime / "attachments" / rel).read_bytes() == content


def test_write_is_idempotent(tmp_runtime: Path) -> None:
    cas = CASStore(tmp_runtime / "attachments")
    content = b"abc"
    h1, rel1 = cas.write(content)
    h2, rel2 = cas.write(content)
    assert h1 == h2
    assert rel1 == rel2
    assert (tmp_runtime / "attachments" / rel1).read_bytes() == content


def test_write_uses_atomic_rename(tmp_runtime: Path) -> None:
    cas = CASStore(tmp_runtime / "attachments")
    cas.write(b"x")
    leftover = list((tmp_runtime / "attachments").rglob("*.tmp"))
    assert leftover == []


def test_path_returns_absolute_path(tmp_runtime: Path) -> None:
    cas = CASStore(tmp_runtime / "attachments")
    h, rel = cas.write(b"y")
    assert cas.path(rel) == (tmp_runtime / "attachments" / rel).resolve()
