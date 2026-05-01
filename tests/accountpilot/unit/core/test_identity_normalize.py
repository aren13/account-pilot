from __future__ import annotations

import pytest

from accountpilot.core.identity import (
    normalize_email,
    normalize_handle,
    normalize_phone,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Foo@Bar.COM", "foo@bar.com"),
        ("  foo@bar.com  ", "foo@bar.com"),
        ("mailto:foo@bar.com", "foo@bar.com"),
        ("MAILTO:Foo@Bar.com", "foo@bar.com"),
    ],
)
def test_normalize_email(raw: str, expected: str) -> None:
    assert normalize_email(raw) == expected


@pytest.mark.parametrize(
    "raw, default_region, expected",
    [
        ("+90 505 249 01 39", None, "+905052490139"),
        ("905052490139", "TR", "+905052490139"),
        ("05052490139", "TR", "+905052490139"),
        ("+1 (555) 123-4567", None, "+15551234567"),
    ],
)
def test_normalize_phone_e164(
    raw: str, default_region: str | None, expected: str
) -> None:
    assert normalize_phone(raw, default_region=default_region) == expected


def test_normalize_phone_returns_raw_when_unparseable() -> None:
    assert normalize_phone("nonsense") == "nonsense"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("+15551234567", "+15551234567"),
        ("Foo@Bar.com", "foo@bar.com"),
        (" Foo  ", "foo"),
    ],
)
def test_normalize_handle_dispatches(raw: str, expected: str) -> None:
    assert normalize_handle(raw) == expected
