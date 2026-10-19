"""
vision_scoring.py — Azure AI Vision defect scoring for inspection images
========================================================================
Analyses inspection photographs fetched from Fulcrum (field survey app)
to detect and quantify visual defects: oil stains, bushing cracks,
corrosion, discolouration, and structural damage.

Pipeline:
  1. Fetch image bytes from Fulcrum (via BFF proxy — API key server-side)
  2. Laplacian sharpness pre-filter — reject blurry images before API call
  3. Send to Azure AI Vision (Analyze Image v4.0) with visual features:
       dense captions, objects, tags, smart crops
  4. Map returned tags/captions to domain-specific defect categories
  5. Return normalised defect score (0.0–1.0) + detected defects list

Azure AI Vision (not Azure OpenAI) is used for classification/detection
tasks; GPT-4 Vision is reserved for the RAG chat interpretation layer.
"""

import os
import cv2
import httpx
import numpy as np
from typing import Optional
from dataclasses import dataclass, field


# ── Config ────────────────────────────────────────────────────────────────────

VISION_ENDPOINT = os.environ["AZURE_VISION_ENDPOINT"]   # e.g. https://<name>.cognitiveservices.azure.com
VISION_KEY      = os.environ["AZURE_VISION_KEY"]
VISION_API_VER  = "2024-02-01"

SHARPNESS_THRESHOLD = 100.0    # Laplacian variance below this → reject image
FULCRUM_API_KEY     = os.environ["FULCRUM_API_KEY"]
FULCRUM_BASE_URL    = "https://api.fulcrumapp.com/api/v2"


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class DetectedDefect:
    category: str          # e.g. "oil_stain", "corrosion", "bushing_crack"
    confidence: float      # 0.0–1.0
    description: str       # Raw caption or tag text from Vision API


@dataclass
class VisionScoreResult:
    asset_id: str
    record_id: str
    defect_score: float                     # 0.0 (no defects) – 1.0 (severe)
    defects: list[DetectedDefect] = field(default_factory=list)
    image_rejected: bool = False
    rejection_reason: Optional[str] = None
    sharpness_score: Optional[float] = None
    raw_tags: list[str] = field(default_factory=list)


# ── Defect taxonomy ───────────────────────────────────────────────────────────

# Maps Vision API tags/caption keywords → defect category + severity weight
DEFECT_KEYWORDS: dict[str, tuple[str, float]] = {
    # Category:                  (internal_name,     severity_weight)
    "oil":                       ("oil_stain",         0.7),
    "leak":                      ("oil_stain",         0.8),
    "stain":                     ("oil_stain",         0.6),
    "rust":                      ("corrosion",         0.6),
    "corrosion":                 ("corrosion",         0.8),
    "oxidation":                 ("corrosion",         0.5),
    "crack":                     ("bushing_crack",     0.9),
    "fracture":                  ("bushing_crack",     1.0),
    "discolouration":            ("thermal_discolour", 0.6),
    "discoloration":             ("thermal_discolour", 0.6),
    "burn":                      ("thermal_discolour", 0.9),
    "charring":                  ("thermal_discolour", 0.95),
    "damage":                    ("structural_damage", 0.7),
    "deformation":               ("structural_damage", 0.8),
    "broken":                    ("structural_damage", 0.9),
    "debris":                    ("foreign_object",    0.5),
    "bird nest":                 ("foreign_object",    0.6),
    "vegetation":                ("vegetation_growth", 0.4),
    "overgrowth":                ("vegetation_growth", 0.5),
}


# ── Step 1: Fulcrum image fetch ───────────────────────────────────────────────

def fetch_inspection_image(record_id: str, photo_index: int = 0) -> bytes:
    """
    Fulcrum two-step fetch (matching the BFF pattern in backend/endpoints/photo.py).
    Step 1: GET record metadata → extract photos[photo_index].large URL
    Step 2: GET image bytes from that URL

    This pipeline function calls Fulcrum directly (server-to-server);
    the frontend BFF proxy is for browser access only.
    """
    headers = {
        "X-ApiToken": FULCRUM_API_KEY,
        "Accept": "application/json",
    }
    with httpx.Client(timeout=30) as client:
        # Step 1: Metadata
        meta_resp = client.get(
            f"{FULCRUM_BASE_URL}/records/{record_id}.json",
            headers=headers,
        )
        meta_resp.raise_for_status()
        record = meta_resp.json()

        photos = record.get("record", {}).get("photos", [])
        if not photos:
            raise ValueError(f"No photos attached to Fulcrum record {record_id}")

        large_url = photos[photo_index].get("large")
        if not large_url:
            raise ValueError(f"Photo {photo_index} has no large URL in record {record_id}")

        # Step 2: Image bytes
        img_resp = client.get(large_url, headers=headers)
        img_resp.raise_for_status()
        return img_resp.content


# ── Step 2: Laplacian sharpness filter ───────────────────────────────────────

def compute_sharpness(image_bytes: bytes) -> float:
    """
    Laplacian variance — fast proxy for image sharpness.
    Low variance = blurry image. Threshold defined by SHARPNESS_THRESHOLD.

    Returns:
        Laplacian variance (float). Higher = sharper.
    """
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    laplacian = cv2.Laplacian(img, cv2.CV_64F)
    return float(laplacian.var())


# ── Step 3: Azure AI Vision analysis ─────────────────────────────────────────

def analyse_with_vision(image_bytes: bytes) -> dict:
    """
    Send image bytes to Azure AI Vision Analyze API.
    Features: denseCaptions, objects, tags, smartCrops.

    Returns:
        Parsed JSON response dict from the Vision API.

    Raises:
        httpx.HTTPStatusError: on 4xx/5xx from Vision API.
    """
    url = (
        f"{VISION_ENDPOINT}/computervision/imageanalysis:analyze"
        f"?api-version={VISION_API_VER}"
        f"&features=denseCaptions,objects,tags"
    )
    headers = {
        "Ocp-Apim-Subscription-Key": VISION_KEY,
        "Content-Type": "application/octet-stream",
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, content=image_bytes, headers=headers)
        resp.raise_for_status()
        return resp.json()


# ── Step 4 & 5: Defect extraction + scoring ──────────────────────────────────

def extract_defects(vision_response: dict) -> tuple[list[DetectedDefect], list[str]]:
    """
    Map Vision API response to domain defect categories.

    Checks:
      - tags (name + confidence)
      - denseCaptions (text)

    Returns:
        (defects list, raw_tags list)
    """
    defects: list[DetectedDefect] = []
    seen_categories: set[str] = set()
    raw_tags: list[str] = []

    # Tags
    for tag in vision_response.get("tagsResult", {}).get("values", []):
        name = tag.get("name", "").lower()
        conf = float(tag.get("confidence", 0.0))
        raw_tags.append(f"{name} ({conf:.2f})")

        if conf < 0.5:
            continue
        for keyword, (category, weight) in DEFECT_KEYWORDS.items():
            if keyword in name and category not in seen_categories:
                defects.append(DetectedDefect(
                    category=category,
                    confidence=conf * weight,
                    description=name,
                ))
                seen_categories.add(category)

    # Dense captions (lower confidence, but richer context)
    for cap in vision_response.get("denseCaptionsResult", {}).get("values", []):
        text = cap.get("text", "").lower()
        conf = float(cap.get("confidence", 0.0))
        if conf < 0.4:
            continue
        for keyword, (category, weight) in DEFECT_KEYWORDS.items():
            if keyword in text and category not in seen_categories:
                defects.append(DetectedDefect(
                    category=category,
                    confidence=conf * weight,
                    description=text[:80],
                ))
                seen_categories.add(category)

    return defects, raw_tags


def score_defects(defects: list[DetectedDefect]) -> float:
    """
    Aggregate defect confidence into a single normalised score [0, 1].
    Uses max-pooling over categories to avoid double-counting.
    """
    if not defects:
        return 0.0
    # Take the max confidence per category, then average those
    by_category: dict[str, float] = {}
    for d in defects:
        by_category[d.category] = max(by_category.get(d.category, 0.0), d.confidence)
    return min(sum(by_category.values()) / len(by_category), 1.0)


# ── Main pipeline function ────────────────────────────────────────────────────

def score_inspection_image(asset_id: str, record_id: str) -> VisionScoreResult:
    """
    Full vision scoring pipeline for one transformer inspection record.

    Designed to be called from the nightly batch pipeline for assets that
    have new Fulcrum inspection records since the last scoring run.

    Args:
        asset_id:  Transformer asset ID (for attribution in result).
        record_id: Fulcrum record ID for the inspection record.

    Returns:
        VisionScoreResult with defect_score, defects list, and metadata.
    """
    try:
        image_bytes = fetch_inspection_image(record_id)
    except Exception as exc:
        return VisionScoreResult(
            asset_id=asset_id, record_id=record_id,
            defect_score=0.0,
            image_rejected=True,
            rejection_reason=f"Image fetch failed: {exc}",
        )

    sharpness = compute_sharpness(image_bytes)
    if sharpness < SHARPNESS_THRESHOLD:
        return VisionScoreResult(
            asset_id=asset_id, record_id=record_id,
            defect_score=0.0,
            image_rejected=True,
            rejection_reason=f"Image too blurry (Laplacian={sharpness:.1f} < {SHARPNESS_THRESHOLD})",
            sharpness_score=sharpness,
        )

    try:
        vision_resp = analyse_with_vision(image_bytes)
    except Exception as exc:
        return VisionScoreResult(
            asset_id=asset_id, record_id=record_id,
            defect_score=0.0,
            image_rejected=True,
            rejection_reason=f"Vision API error: {exc}",
            sharpness_score=sharpness,
        )

    defects, raw_tags = extract_defects(vision_resp)
    defect_score = score_defects(defects)

    return VisionScoreResult(
        asset_id=asset_id,
        record_id=record_id,
        defect_score=defect_score,
        defects=defects,
        sharpness_score=sharpness,
        raw_tags=raw_tags,
    )
