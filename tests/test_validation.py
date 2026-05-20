"""Tests for input validation."""

import pytest

from homelab_infra_mcp.utils.validation import (
    ValidationError,
    validate_domain,
    validate_port,
)


def test_validate_domain_ok():
    assert validate_domain("app.example.com") == "app.example.com"


def test_validate_domain_rejects_invalid():
    with pytest.raises(ValidationError):
        validate_domain("not a domain")


def test_validate_port_range():
    validate_port(443)
    with pytest.raises(ValidationError):
        validate_port(0)
