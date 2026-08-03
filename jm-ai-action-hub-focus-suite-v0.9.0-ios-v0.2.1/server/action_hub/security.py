from __future__ import annotations

import hmac
from collections.abc import Callable

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from .services.mobile_auth import MobileAuthError, MobilePrincipal, authenticate_mobile, mobile_signing_secret

ADMIN_API_KEY = APIKeyHeader(
    name="X-Action-Hub-Key",
    auto_error=False,
    scheme_name="ActionHubAdminKey",
    description="Administrative Action Hub API key. Never embed this key in the iOS app.",
)
MOBILE_BEARER = HTTPBearer(
    auto_error=False,
    scheme_name="ActionHubMobileBearer",
    description="Short-lived mobile access token issued after QR pairing.",
)


async def require_api_key(
    request: Request,
    x_action_hub_key: str | None = Security(ADMIN_API_KEY),
) -> None:
    settings = request.app.state.settings
    configured = settings.api_key or ""
    if not settings.api_key_is_secure:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key is not configured securely",
        )
    if not x_action_hub_key or not hmac.compare_digest(
        configured.encode("utf-8"), x_action_hub_key.encode("utf-8")
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def require_mobile_scope(scope: str) -> Callable[..., MobilePrincipal]:
    async def dependency(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Security(MOBILE_BEARER),
    ) -> MobilePrincipal:
        settings = request.app.state.settings
        if not settings.mobile_enabled:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Mobile API disabled")
        try:
            mobile_signing_secret(settings)
        except MobileAuthError as exc:
            if exc.code not in {"mobile_auth_not_configured", "mobile_secret_reuses_admin_key"}:
                raise
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer access token required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = credentials.credentials.strip()
        try:
            with request.app.state.database.session_factory() as db:
                principal = authenticate_mobile(db, token, settings)
        except MobileAuthError as exc:
            code = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if exc.code in {"mobile_auth_not_configured", "mobile_secret_reuses_admin_key"}
                else status.HTTP_401_UNAUTHORIZED
            )
            raise HTTPException(
                status_code=code,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"} if code == 401 else None,
            ) from exc
        if not principal.has_scope(scope):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing mobile scope: {scope}")
        return principal

    return dependency
