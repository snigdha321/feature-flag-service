"""Normalize database URLs for the async (asyncpg) driver.

Managed Postgres providers (e.g. DigitalOcean) hand out libpq-style URLs like
``postgresql://user:pass@host:25060/db?sslmode=require``. Two adjustments are
needed before SQLAlchemy's asyncpg dialect can use them:

1. The scheme must select the async driver (``postgresql+asyncpg``).
2. ``sslmode`` is a libpq concept that asyncpg does not accept as a URL query
   argument; it must be translated into an ``ssl`` connect argument.
"""

from __future__ import annotations

import ssl
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_ASYNC_SCHEME = "postgresql+asyncpg"
_SYNC_SCHEMES = {"postgres", "postgresql", "postgresql+psycopg2", "postgresql+psycopg"}
# libpq sslmode values that mean "encrypt but do not verify the server cert".
_UNVERIFIED_MODES = {"require", "prefer", "allow", "true", "1", "on"}
_DISABLED_MODES = {"disable", "false", "0", "off"}


def normalize_database_url(url: str) -> tuple[str, dict]:
    """Return an asyncpg-compatible URL and matching connect_args.

    Non-Postgres URLs (e.g. ``sqlite+aiosqlite``) are returned unchanged with
    empty connect_args.
    """
    parts = urlsplit(url)
    scheme = parts.scheme

    if scheme not in _SYNC_SCHEMES and scheme != _ASYNC_SCHEME:
        # Not a Postgres URL (e.g. sqlite) - leave it alone.
        return url, {}

    if scheme in _SYNC_SCHEMES:
        scheme = _ASYNC_SCHEME

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    # asyncpg understands neither `sslmode` nor a plain `ssl` string here.
    mode = query.pop("sslmode", None) or query.pop("ssl", None)

    connect_args: dict = {}
    if mode is not None:
        mode = mode.strip().lower()
        if mode in _DISABLED_MODES:
            connect_args["ssl"] = False
        else:
            ctx = ssl.create_default_context()
            if mode in _UNVERIFIED_MODES:
                # Mirror libpq `require`: encrypt without CA/hostname checks.
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            # verify-ca / verify-full keep the default verifying context.
            connect_args["ssl"] = ctx

    normalized = urlunsplit(
        (scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )
    return normalized, connect_args
