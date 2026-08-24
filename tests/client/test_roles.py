"""Client-side role helpers: normalization and minimum-role comparisons."""

from __future__ import annotations


def test_role_at_least_and_normalize_role() -> None:
    """normalize_role lowercases and trims; role_at_least respects the role hierarchy"""
    from riskapp_client.utils.roles import (
        is_known_role,
        normalize_role,
        role_at_least,
    )

    # normalize_role
    assert normalize_role(" Admin ") == "admin"
    assert normalize_role("MEMBER") == "member"
    assert normalize_role(None) == ""
    assert normalize_role("") == ""

    # is_known_role
    assert is_known_role("manager") is True
    assert is_known_role(" Viewer ") is True
    assert is_known_role("super") is False
    assert is_known_role(None) is False

    # role_at_least: hierarchy is viewer < member < manager < admin
    assert role_at_least("manager", "member") is True
    assert role_at_least("admin", "admin") is True
    assert role_at_least("viewer", "member") is False
    assert role_at_least("member", "manager") is False

    # Unknown roles never satisfy the minimum.
    assert role_at_least("super", "viewer") is False
    assert role_at_least("admin", "super") is False
    assert role_at_least(None, "viewer") is False
