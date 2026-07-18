"""Admin/introspection endpoints, gated behind a shared-secret token.

These expose internal runtime state (currently the in-process flag cache) and
are intended for operators, not general API consumers. Access requires the
``x-admin-token`` header to match ``Settings.admin_token``. When no token is
configured the endpoints are disabled and return 503, so they are never
reachable unauthenticated by default.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.cache import get_cache
from app.config import get_settings

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    """Authorize an admin request via the ``x-admin-token`` header."""
    configured = get_settings().admin_token
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin endpoints are disabled (no admin token configured)",
        )
    if not x_admin_token or x_admin_token != configured:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing admin token",
        )


@router.get("/cache", dependencies=[Depends(require_admin_token)])
async def cache_state() -> dict[str, Any]:
    """Return the current contents of the in-process flag cache.

    Note: the cache is process-local, so this reflects only the instance that
    served the request. With more than one instance, results vary per request.
    """
    return get_cache().describe()
