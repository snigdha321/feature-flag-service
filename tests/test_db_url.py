"""Tests for database URL normalization (async driver + SSL handling)."""

from __future__ import annotations

import ssl

import pytest

from app.db_url import normalize_database_url


def test_digitalocean_style_url_is_made_async_and_ssl_translated() -> None:
    url = (
        "postgresql://doadmin:secret@db-do-user-0.k.db.ondigitalocean.com:25060"
        "/defaultdb?sslmode=require"
    )
    normalized, connect_args = normalize_database_url(url)

    assert normalized.startswith("postgresql+asyncpg://")
    # libpq-only sslmode must not survive in the query string.
    assert "sslmode" not in normalized
    # It becomes an asyncpg SSL context instead.
    ssl_ctx = connect_args["ssl"]
    assert isinstance(ssl_ctx, ssl.SSLContext)
    assert ssl_ctx.check_hostname is False
    assert ssl_ctx.verify_mode == ssl.CERT_NONE


def test_bare_postgres_scheme_gets_async_driver() -> None:
    normalized, connect_args = normalize_database_url("postgres://u:p@host:5432/db")
    assert normalized == "postgresql+asyncpg://u:p@host:5432/db"
    assert connect_args == {}


def test_existing_async_driver_is_preserved() -> None:
    url = "postgresql+asyncpg://flags:flags@localhost:5432/flags"
    normalized, connect_args = normalize_database_url(url)
    assert normalized == url
    assert connect_args == {}


def test_sqlite_url_is_untouched() -> None:
    url = "sqlite+aiosqlite:///tmp/test.db"
    normalized, connect_args = normalize_database_url(url)
    assert normalized == url
    assert connect_args == {}


def test_sslmode_disable_turns_ssl_off() -> None:
    _, connect_args = normalize_database_url("postgresql://u:p@host/db?sslmode=disable")
    assert connect_args["ssl"] is False


def test_sslmode_verify_full_keeps_verification() -> None:
    _, connect_args = normalize_database_url("postgresql://u:p@host/db?sslmode=verify-full")
    ssl_ctx = connect_args["ssl"]
    assert isinstance(ssl_ctx, ssl.SSLContext)
    assert ssl_ctx.check_hostname is True
    assert ssl_ctx.verify_mode == ssl.CERT_REQUIRED


@pytest.mark.parametrize("libpq_param", ["sslrootcert=/x.crt", "channel_binding=require"])
def test_other_libpq_ssl_params_are_dropped(libpq_param: str) -> None:
    normalized, _ = normalize_database_url(f"postgresql://u:p@host/db?{libpq_param}")
    assert "sslrootcert" not in normalized
    assert "channel_binding" not in normalized


def test_non_ssl_query_params_are_preserved() -> None:
    normalized, _ = normalize_database_url(
        "postgresql://u:p@host/db?application_name=flags&sslmode=require"
    )
    assert "application_name=flags" in normalized
