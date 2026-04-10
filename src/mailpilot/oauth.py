"""OAuth2 token management for Microsoft 365 IMAP/SMTP (XOAUTH2).

Supports the device code flow for interactive CLI authorization and
automatic token refresh using MSAL's persistent token cache.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import msal

if TYPE_CHECKING:
    from mailpilot.config import AuthConfig

logger = logging.getLogger(__name__)

# Microsoft identity platform endpoints.
_AUTHORITY_TEMPLATE = "https://login.microsoftonline.com/{tenant}"

# Scopes required for IMAP + SMTP access (delegated / user).
IMAP_SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All"
SMTP_SCOPE = "https://outlook.office.com/SMTP.Send"
DEFAULT_SCOPES = [IMAP_SCOPE, SMTP_SCOPE, "offline_access"]


def _cache_path(data_dir: str, account_name: str) -> Path:
    """Return the path for the MSAL token cache file."""
    return Path(data_dir) / f"oauth-{account_name}.json"


def _build_app(
    auth: AuthConfig,
    cache_path: Path,
) -> msal.PublicClientApplication:
    """Build an MSAL PublicClientApplication with persistent cache."""
    if not auth.client_id:
        raise ValueError("client_id is required for OAuth2")
    if not auth.tenant_id:
        raise ValueError("tenant_id is required for OAuth2")

    authority = _AUTHORITY_TEMPLATE.format(tenant=auth.tenant_id)

    cache = msal.SerializableTokenCache()
    if cache_path.exists():
        cache.deserialize(cache_path.read_text(encoding="utf-8"))

    app = msal.PublicClientApplication(
        client_id=auth.client_id,
        authority=authority,
        token_cache=cache,
    )
    return app


def _save_cache(
    app: msal.PublicClientApplication, cache_path: Path
) -> None:
    """Persist the MSAL token cache to disk if it changed."""
    cache = app.token_cache
    if isinstance(cache, msal.SerializableTokenCache) and cache.has_state_changed:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(cache.serialize(), encoding="utf-8")
        logger.debug("Token cache saved to %s", cache_path)


def acquire_token_interactive(
    auth: AuthConfig,
    data_dir: str,
    account_name: str,
    email: str,
) -> str:
    """Run the device code flow and return an access token.

    Prints the device code message so the user can authorize in a browser.

    Args:
        auth: AuthConfig with client_id and tenant_id.
        data_dir: MailPilot data directory for token cache storage.
        account_name: Account name (used for cache file naming).
        email: User email (used as login_hint).

    Returns:
        The access token string.

    Raises:
        RuntimeError: If the device code flow fails.
    """
    cache_path = _cache_path(data_dir, account_name)
    app = _build_app(auth, cache_path)

    scopes = [IMAP_SCOPE, SMTP_SCOPE]

    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        raise RuntimeError(
            f"Device code flow failed: {json.dumps(flow, indent=2)}"
        )

    # Print the authorization message for the user.
    print(flow["message"])

    result = app.acquire_token_by_device_flow(flow)
    _save_cache(app, cache_path)

    if "access_token" in result:
        logger.info("OAuth2 token acquired for %s", email)
        return result["access_token"]

    error = result.get("error_description", result.get("error", "unknown"))
    raise RuntimeError(f"Token acquisition failed: {error}")


def get_access_token(
    auth: AuthConfig,
    data_dir: str,
    account_name: str,
    email: str,
) -> str:
    """Get a valid access token, refreshing silently if possible.

    Tries the MSAL token cache first (silent acquisition with refresh
    token). If no cached token is available, raises RuntimeError
    instructing the user to run ``mailpilot account auth``.

    Args:
        auth: AuthConfig with client_id and tenant_id.
        data_dir: MailPilot data directory.
        account_name: Account name for cache file.
        email: User email address.

    Returns:
        A valid access token string.

    Raises:
        RuntimeError: If no cached token and silent acquisition fails.
    """
    cache_path = _cache_path(data_dir, account_name)
    app = _build_app(auth, cache_path)

    scopes = [IMAP_SCOPE, SMTP_SCOPE]

    accounts = app.get_accounts(username=email)
    if not accounts:
        raise RuntimeError(
            f"No cached OAuth2 token for {email}. "
            f"Run: mailpilot account auth {account_name}"
        )

    result = app.acquire_token_silent(scopes, account=accounts[0])
    _save_cache(app, cache_path)

    if result and "access_token" in result:
        logger.debug("OAuth2 token refreshed silently for %s", email)
        return result["access_token"]

    raise RuntimeError(
        f"OAuth2 token refresh failed for {email}. "
        f"Run: mailpilot account auth {account_name}"
    )
