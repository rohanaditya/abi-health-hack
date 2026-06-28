"""
PCC API client with retry logic.

All requests go through request_with_retry(), which handles 429 (rate limit)
and 5xx errors with exponential backoff + jitter. Raises RateLimitExhausted
when MAX_RETRIES attempts are exhausted so callers can mark a run as failed.

CRITICAL: Two patient ID types exist — do NOT mix them.
  - patient_id (str, e.g. "FA-001")  -> /diagnoses, /coverage
  - id         (int, e.g. 1)         -> /notes, /assessments
"""

import logging
import random
import time
from datetime import datetime
from typing import Any

import requests

from config import API_BASE_URL, MAX_RETRIES

logger = logging.getLogger(__name__)


class RateLimitExhausted(Exception):
    """Raised when all retry attempts are exhausted for a request."""


def request_with_retry(method: str, url: str, params: dict | None = None) -> Any:
    """
    Make an HTTP request, retrying on 429 and 5xx until MAX_RETRIES is reached.

    Honors the Retry-After header on 429. Falls back to exponential backoff
    with jitter for 5xx and network errors.
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, params=params, timeout=30)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 2))
                logger.warning(
                    "429 rate-limited [%s] attempt %d/%d — sleeping %ds",
                    url, attempt, MAX_RETRIES, retry_after,
                )
                time.sleep(retry_after)
                continue

            if resp.status_code >= 500:
                wait = min(2 ** attempt, 60) + random.uniform(0, 1)
                logger.warning(
                    "%d server error [%s] attempt %d/%d — sleeping %.1fs",
                    resp.status_code, url, attempt, MAX_RETRIES, wait,
                )
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()

        except requests.RequestException as exc:
            last_exc = exc
            wait = min(2 ** attempt, 60) + random.uniform(0, 1)
            logger.warning(
                "Request error [%s] attempt %d/%d: %s — sleeping %.1fs",
                url, attempt, MAX_RETRIES, exc, wait,
            )
            time.sleep(wait)

    raise RateLimitExhausted(
        f"Exhausted {MAX_RETRIES} retries for {url}"
    ) from last_exc


# ---------------------------------------------------------------------------
# Endpoint wrappers
# ---------------------------------------------------------------------------

def get_health() -> dict:
    """Check API health endpoint."""
    return request_with_retry("GET", f"{API_BASE_URL}/health")


def get_patients(facility_id: int, since: datetime | None = None) -> list[dict]:
    """
    Fetch patients for a facility.
    `since` filters by last_modified_at (ISO 8601).
    """
    params: dict = {"facility_id": facility_id}
    if since is not None:
        params["since"] = since.isoformat()
    return request_with_retry("GET", f"{API_BASE_URL}/pcc/patients", params=params)


def get_diagnoses(patient_id: str) -> list[dict]:
    """Fetch diagnoses using STRING patient_id (e.g. 'FA-001'). No since param."""
    return request_with_retry(
        "GET", f"{API_BASE_URL}/pcc/diagnoses", params={"patient_id": patient_id}
    )


def get_coverage(patient_id: str) -> list[dict]:
    """Fetch coverage using STRING patient_id (e.g. 'FA-001'). No since param."""
    return request_with_retry(
        "GET", f"{API_BASE_URL}/pcc/coverage", params={"patient_id": patient_id}
    )


def get_notes(patient_id: int, since: datetime | None = None) -> list[dict]:
    """
    Fetch notes using INTEGER patient id (e.g. 1).
    `since` filters by effective_date.
    """
    params: dict = {"patient_id": patient_id}
    if since is not None:
        params["since"] = since.isoformat()
    return request_with_retry("GET", f"{API_BASE_URL}/pcc/notes", params=params)


def get_assessments(patient_id: int, since: datetime | None = None) -> list[dict]:
    """
    Fetch assessments using INTEGER patient id (e.g. 1).
    `since` filters by assessment_date.
    """
    params: dict = {"patient_id": patient_id}
    if since is not None:
        params["since"] = since.isoformat()
    return request_with_retry("GET", f"{API_BASE_URL}/pcc/assessments", params=params)
