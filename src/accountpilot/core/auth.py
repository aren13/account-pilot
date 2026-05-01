"""Credential resolution.

Two-layer model:
- `Secrets(values)` holds an in-memory key→value registry; `get(key, default)`
  matches `dict.get` semantics.
- `Secrets.resolve(uri)` recognizes the `password_cmd:<shell cmd>` scheme by
  running the command and returning its stripped stdout. Anything else is
  passed through as-is (literal credential).

SP3 will extend `resolve` to recognize `op://...` 1Password URIs natively;
for SP1, callers wrap that as `password_cmd:op read op://...` so a single
resolution path handles everything.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

_CMD_SCHEME = "password_cmd:"


@dataclass(frozen=True)
class Secrets:
    """In-memory credential registry plus a static URI resolver."""

    values: dict[str, str]

    def get(self, key: str, default: str | None = None) -> str | None:
        """Return the value registered for `key`, or `default` if absent."""
        return self.values.get(key, default)

    @staticmethod
    def resolve(uri: str) -> str:
        """Resolve a credential URI to its plaintext value.

        - `password_cmd:<shell cmd>`: run the command via the shell, return
          stripped stdout. Non-zero exit raises RuntimeError with stderr.
        - anything else: return unchanged (treated as a literal credential).
        """
        if not uri.startswith(_CMD_SCHEME):
            return uri
        cmd = uri[len(_CMD_SCHEME):]
        try:
            result = subprocess.run(  # noqa: S602 — intentional shell exec
                cmd,
                shell=True,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"password_cmd timed out after 30s: {shlex.quote(cmd)}"
            ) from e
        if result.returncode != 0:
            raise RuntimeError(
                f"password_cmd exit {result.returncode}: "
                f"{shlex.quote(cmd)}\nstderr: {result.stderr.strip()}"
            )
        return result.stdout.strip()
