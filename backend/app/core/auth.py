"""
app/core/auth.py — SAML/SSO authentication and JWT middleware

Implements the shared platform authentication layer:

  /api/saml/login  — Redirects user to Identity Provider (e.g. Azure AD)
                     with a SAML AuthnRequest. Stores return_to path.

  /api/saml/acs    — Assertion Consumer Service. Receives signed SAML XML
                     Response POST from IdP. Validates signature, extracts
                     identity attributes, issues 8-hour JWT.

  jwt_middleware   — FastAPI middleware. Validates Bearer JWT on every
                     protected /api/* route. Bypassed on /health and /saml/*.

Security:
  - JWT signed with HS256 using JWT_SECRET (set in OCI Vault → env)
  - SAML XML signature validated before any attribute extraction
  - JWT removed from URL immediately after frontend receives it
    (frontend uses history.replaceState — prevents JWT appearing in
     browser history or server access logs)
  - When SAML_ENABLED=false (local dev), middleware bypasses auth checks

Authorization:
  JWT payload contains access booleans:
    { "sub": "user@company.com", "name": "...",
      "access_transformer": true,
      "access_generation": false,
      "exp": <8 hours from now> }
"""

import os
import time
import logging
from typing import Optional
from fastapi import Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)

SAML_ENABLED    = os.getenv("SAML_ENABLED", "false").lower() == "true"
JWT_SECRET      = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_EXPIRY_HRS  = int(os.getenv("JWT_EXPIRY_HOURS", "8"))
IDP_SSO_URL     = os.getenv("IDP_SSO_URL", "")
SP_ENTITY_ID    = os.getenv("SP_ENTITY_ID", "asset-explorer")
ACS_URL         = os.getenv("ACS_URL", "http://localhost:8000/api/saml/acs")

# Routes that bypass JWT auth
AUTH_EXEMPT_PREFIXES = ["/health", "/api/saml/", "/api/docs", "/openapi.json"]

MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

async def jwt_middleware(request: Request, call_next) -> Response:
    """
    Validate Bearer JWT on every /api/* route.
    Exempt: /health, /api/saml/*, /api/docs

    In mock mode or when SAML_ENABLED=false, bypasses all auth checks.
    """
    path = request.url.path

    # Skip auth for exempt paths
    if not SAML_ENABLED or MOCK_MODE:
        return await call_next(request)

    for prefix in AUTH_EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return await call_next(request)

    # Validate Bearer token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or invalid Authorization header"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[len("Bearer "):]
    payload = _verify_jwt(token)
    if payload is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Token invalid or expired"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Attach user info to request state for endpoint use
    request.state.user = payload
    return await call_next(request)


# ---------------------------------------------------------------------------
# SAML endpoints (registered as plain functions, mounted in main.py)
# ---------------------------------------------------------------------------

from fastapi import APIRouter

router = APIRouter(tags=["auth"])


@router.get("/saml/login")
def saml_login(return_to: str = "/"):
    """
    Step 1: Redirect browser to Identity Provider with SAML AuthnRequest.

    return_to: path the frontend was on when auth was needed — stored so
               the browser lands back there after login completes.
    """
    if not SAML_ENABLED:
        return JSONResponse({"detail": "SAML not enabled"}, status_code=400)

    try:
        import onelogin.saml2.auth as saml_lib
        saml_auth = _build_saml_auth({"get_data": {"return_to": return_to}})
        redirect_url = saml_auth.login()
        return RedirectResponse(url=redirect_url)
    except ImportError:
        logger.error("python3-saml not installed — add to requirements.txt")
        return JSONResponse({"detail": "SAML library not available"}, status_code=500)


@router.post("/saml/acs")
async def saml_acs(request: Request):
    """
    Step 2 — Assertion Consumer Service.

    IdP POSTs signed SAML XML here after user authenticates.

    Process:
      1. Parse + validate XML signature
      2. Extract identity attributes (email, display name)
      3. Check is_user_authorized()
      4. Issue 8-hour JWT
      5. Redirect frontend with ?token= query param
         (frontend stores in localStorage, removes from URL immediately)
    """
    if not SAML_ENABLED:
        return JSONResponse({"detail": "SAML not enabled"}, status_code=400)

    form_data = await request.form()
    post_data = dict(form_data)

    try:
        import onelogin.saml2.auth as saml_lib
        saml_auth = _build_saml_auth({"post_data": post_data})
        saml_auth.process_response()
        errors = saml_auth.get_errors()
        if errors:
            logger.error(f"SAML validation errors: {errors}")
            return JSONResponse({"detail": "SAML assertion invalid"}, status_code=401)

        attributes = saml_auth.get_attributes()
        name_id    = saml_auth.get_nameid()
        user_email = name_id or ""
        user_name  = _extract_attr(attributes, ["displayName", "name", "cn"], user_email)

        if not is_user_authorized(user_email, attributes):
            return JSONResponse({"detail": "Access denied"}, status_code=403)

        token = _issue_jwt(user_email, user_name, attributes)
        relay_state = post_data.get("RelayState", "/")

        # Redirect to frontend with token in query param
        frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
        redirect_url = f"{frontend_origin}{relay_state}?token={token}"
        return RedirectResponse(url=redirect_url, status_code=303)

    except Exception as exc:
        logger.exception("SAML ACS processing failed")
        return JSONResponse({"detail": f"Auth error: {exc}"}, status_code=500)


# ---------------------------------------------------------------------------
# Authorization logic
# ---------------------------------------------------------------------------

def is_user_authorized(email: str, attributes: dict) -> bool:
    """
    Check whether the authenticated user should have any app access.
    Extend with group-based claims from your IdP as needed.
    """
    if not email:
        return False
    # Example: block external domains
    # allowed_domain = os.getenv("ALLOWED_DOMAIN", "")
    # if allowed_domain and not email.endswith(f"@{allowed_domain}"):
    #     return False
    return True


def _get_access_claims(email: str, attributes: dict) -> dict:
    """
    Derive per-module access flags from IdP attributes or email domain.
    Stored in JWT payload — frontend reads these to show/hide modules.
    """
    groups = attributes.get("groups", [])
    return {
        "access_transformer": True,   # Replace with real group check
        "access_generation":  True,
    }


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _issue_jwt(email: str, name: str, attributes: dict) -> str:
    """Sign and return an 8-hour JWT."""
    import hmac, hashlib, base64, json

    header  = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({
        "sub":  email,
        "name": name,
        "iat":  int(time.time()),
        "exp":  int(time.time()) + JWT_EXPIRY_HRS * 3600,
        **_get_access_claims(email, attributes),
    }).encode())

    signing_input = f"{header}.{payload}"
    sig = hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(sig)}"


def _verify_jwt(token: str) -> Optional[dict]:
    """Verify JWT signature and expiry. Returns payload dict or None."""
    import hmac, hashlib, json

    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        header, payload_b64, sig_b64 = parts
        signing_input = f"{header}.{payload_b64}"
        expected_sig = hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
        actual_sig   = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        payload = json.loads(_b64url_decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def _b64url(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    import base64
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


def _extract_attr(attrs: dict, keys: list, default: str = "") -> str:
    for k in keys:
        if k in attrs and attrs[k]:
            v = attrs[k]
            return v[0] if isinstance(v, list) else v
    return default


def _build_saml_auth(request_data: dict):
    """Build python3-saml Auth object from environment config."""
    import onelogin.saml2.auth as saml_lib
    settings = {
        "sp": {
            "entityId": SP_ENTITY_ID,
            "assertionConsumerService": {
                "url":     ACS_URL,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
        },
        "idp": {
            "entityId":           os.getenv("IDP_ENTITY_ID", ""),
            "singleSignOnService": {
                "url":     IDP_SSO_URL,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": os.getenv("IDP_X509_CERT", ""),
        },
        "security": {
            "wantAssertionsSigned": True,
            "wantMessagesSigned":   False,
        },
    }
    return saml_lib.OneLogin_Saml2_Auth(request_data, settings)
