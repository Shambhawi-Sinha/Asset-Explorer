"""
endpoints/photo.py — GET /api/photo?record_id=<fulcrum_record_id>

BFF (Backend-for-Frontend) proxy for Fulcrum inspection images.

Security: Fulcrum API key NEVER reaches the React frontend.
React calls this endpoint; this endpoint calls Fulcrum with server-side key.

Two-step Fulcrum fetch pattern:
  Step 1: GET /api/2/records/<record_id>.json
          → parse response → extract photos[].large URL

  Step 2: GET <large_url> with auth header
          → stream image bytes back to React as image/jpeg

This pattern is required because Fulcrum doesn't allow unauthenticated
direct image access — all image URLs require the same API key.

Error handling:
  - 404 if record_id starts with "mock-" (mock mode records have no real images)
  - 502 if Fulcrum API is unreachable
  - 404 if record has no photos
"""

import os
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
import requests
import urllib3

logger = logging.getLogger(__name__)

router = APIRouter(tags=["photo"])

MOCK_MODE      = os.getenv("MOCK_MODE", "false").lower() == "true"
FULCRUM_KEY    = os.getenv("FULCRUM_API_KEY", "")
FULCRUM_BASE   = os.getenv("FULCRUM_BASE_URL", "https://api.fulcrumapp.com")
VERIFY_SSL     = os.getenv("VERIFY_SSL", "true").lower() == "true"

if not VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_SESSION = requests.Session()
_SESSION.headers.update({"X-ApiToken": FULCRUM_KEY})


@router.get("/photo")
def get_photo(record_id: Optional[str] = Query(None)):
    """
    Proxy inspection image from Fulcrum via two-step fetch.

    The Fulcrum API key never leaves this server process.
    React receives raw image bytes — no credential exposure.
    """
    if not record_id:
        raise HTTPException(status_code=400, detail="record_id is required")

    if MOCK_MODE or record_id.startswith("mock-"):
        raise HTTPException(
            status_code=404,
            detail="Mock mode — no real inspection images available. "
                   "In production, this proxies Fulcrum images via API key."
        )

    if not FULCRUM_KEY:
        raise HTTPException(status_code=500, detail="FULCRUM_API_KEY not configured")

    # Step 1: Fetch record metadata to get photo URL
    meta_url = f"{FULCRUM_BASE}/api/2/records/{record_id}.json"
    try:
        meta_resp = _SESSION.get(meta_url, timeout=10, verify=VERIFY_SSL)
        meta_resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error(f"Fulcrum metadata fetch failed: {exc}")
        raise HTTPException(status_code=502, detail=f"Fulcrum API unreachable: {exc}")

    meta = meta_resp.json()
    photos = (meta.get("record", {}) or {}).get("photos", [])
    if not photos:
        raise HTTPException(status_code=404, detail="No photos attached to this record")

    large_url = photos[0].get("large")
    if not large_url:
        raise HTTPException(status_code=404, detail="No large photo URL in record")

    # Step 2: Fetch image bytes
    try:
        img_resp = _SESSION.get(large_url, timeout=20, verify=VERIFY_SSL, stream=True)
        img_resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error(f"Fulcrum image fetch failed: {exc}")
        raise HTTPException(status_code=502, detail=f"Image fetch failed: {exc}")

    content_type = img_resp.headers.get("Content-Type", "image/jpeg")
    return Response(content=img_resp.content, media_type=content_type)
