"""Normalize database URLs for the async engine.

Managed Postgres providers (e.g. DigitalOcean) hand out libpq-style URLs such as
``postgresql://user:pass@host:25060/defaultdb?sslmode=require``. Two things about
that URL are incompatible with SQLAlchemy's async engine:

1. The bare ``postgresql://`` scheme resolves to the *synchronous* psycopg driver.
   The async engine needs an async driver, i.e. ``postgresql+asyncpg://``.
2. ``sslmode`` (and friends like ``sslrootcert``) are libpq connection options.
   asyncpg does not accept them as keyword arguments and raises ``TypeError`` if
   they leak through. They must be translated into an ``ssl`` connect argument.

``normalize_database_url`` returns a cleaned SQLAlchemy URL plus the connect args
to hand to ``create_async_engine`` / ``async_engine_from_config``.
"""

from __future__ import annotations

import ssl
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_ASYNC_DRIVER = "postgresql+asyncpg"

# libpq-only query parameters that asyncpg rejects as keyword arguments.
_LIBPQ_SSL_PARAMS = {
    "sslmode",
    "sslrootcert",
    "sslcert",
    "sslkey",
    "sslpassword",
    "channel_binding",
}


def normalize_database_url(url: str) -> tuple[str, dict[str, Any]]:
    """Return an async-ready URL and connect args for the given database URL.

    Non-Postgres URLs (e.g. ``sqlite+aiosqlite``) are returned unchanged with no
    connect args, so this is safe to call unconditionally.
    """
    parts = urlsplit(url)
    if not parts.scheme.startswith("postgres"):
        return url, {}

    scheme = _ASYNC_DRIVER if parts.scheme in ("postgres", "postgresql") else parts.scheme

    sslmode: str | None = None
    sslrootcert: str | None = None
    remaining: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered == "sslmode":
            sslmode = value.lower()
        elif lowered == "sslrootcert":
            sslrootcert = value
        elif lowered in _LIBPQ_SSL_PARAMS:
            continue  # drop other libpq-only params asyncpg can't consume
        else:
            remaining.append((key, value))

    connect_args: dict[str, Any] = {}
    ssl_option = _ssl_for_sslmode(sslmode, sslrootcert)
    if ssl_option is not None:
        connect_args["ssl"] = ssl_option

    cleaned = parts._replace(scheme=scheme, query=urlencode(remaining))
    return urlunsplit(cleaned), connect_args


def _ssl_for_sslmode(sslmode: str | None, sslrootcert: str | None) -> bool | ssl.SSLContext | None:
    """Translate a libpq ``sslmode`` into an asyncpg ``ssl`` connect argument."""
    if sslmode is None:
        return None
    if sslmode == "disable":
        return False

    context = ssl.create_default_context(cafile=sslrootcert or None)
    if sslmode in ("allow", "prefer", "require"):
        # Encrypt the connection but do not verify the server certificate,
        # matching libpq's `require` semantics.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    elif sslmode == "verify-ca":
        context.check_hostname = False
    # "verify-full" keeps the default context (verify certificate + hostname).
    return context
