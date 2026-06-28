"""
Patient sync: pulls patients for all three facilities and upserts raw_patient.

Returns the full list of patient objects fetched (carrying both id types) so
sync_clinical can fan out without re-fetching. A per-facility failure marks
that facility's watermark as 'failed' and continues with others.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2.extensions

from api_client import RateLimitExhausted, get_patients
from config import FACILITIES, WATERMARK_BUFFER_SECONDS
from db import (
    advance_watermark,
    fail_watermark,
    read_watermark,
    set_watermark_running,
    upsert_patients,
)
from transform import api_patient_to_row

logger = logging.getLogger(__name__)


def _parse_iso(s: str) -> datetime:
    """Parse ISO 8601 string (including Z suffix) to a timezone-aware datetime."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def sync_patients(
    conn: psycopg2.extensions.connection,
    source_id: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """
    Sync patients from all facilities.

    Returns:
        (all_patients, counts) where all_patients carries both `id` (int) and
        `patient_id` (str) so downstream syncs can use the right identifier,
        and counts = {"raw_patient": N} of actually upserted rows.
    """
    all_patients: list[dict[str, Any]] = []
    total_upserted = 0

    for facility_id in FACILITIES:
        entity_type = "patient"
        since = read_watermark(conn, source_id, entity_type, facility_id)
        set_watermark_running(conn, source_id, entity_type, facility_id)

        logger.info(
            "Syncing patients facility=%d since=%s", facility_id, since or "beginning"
        )

        try:
            patients = get_patients(facility_id, since=since)
        except RateLimitExhausted as exc:
            logger.error("Rate limit exhausted fetching patients facility=%d: %s", facility_id, exc)
            fail_watermark(conn, source_id, entity_type, facility_id)
            continue

        logger.info("Fetched %d patients for facility %d", len(patients), facility_id)

        fetched_at = datetime.now(timezone.utc)
        rows = [api_patient_to_row(p, source_id, fetched_at) for p in patients]

        try:
            upserted = upsert_patients(conn, rows)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            logger.error("DB error upserting patients facility=%d: %s", facility_id, exc)
            fail_watermark(conn, source_id, entity_type, facility_id)
            continue

        # Advance watermark to MAX(source_last_modified_at) minus safety buffer.
        # If no records were returned, advance to now minus buffer so next run
        # starts from a known-clean point.
        modified_vals = [
            r["source_last_modified_at"]
            for r in rows
            if r.get("source_last_modified_at")
        ]
        if modified_vals:
            max_modified = max(
                _parse_iso(v) if isinstance(v, str) else v for v in modified_vals
            )
            new_synced_at = max_modified - timedelta(seconds=WATERMARK_BUFFER_SECONDS)
        else:
            new_synced_at = fetched_at - timedelta(seconds=WATERMARK_BUFFER_SECONDS)

        advance_watermark(conn, source_id, entity_type, facility_id, new_synced_at, len(patients))
        total_upserted += upserted
        all_patients.extend(patients)

        logger.info(
            "Facility %d patients: %d fetched, %d upserted, watermark -> %s",
            facility_id, len(patients), upserted, new_synced_at.isoformat(),
        )

    return all_patients, {"raw_patient": total_upserted}
