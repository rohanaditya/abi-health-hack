"""
Clinical data sync: diagnoses, coverage, notes, and assessments.

sync_diagnoses_and_coverage  — uses STRING patient_id; no since param; per patient.
sync_notes_and_assessments   — uses INTEGER patient id;  since from per-facility
                               watermark; per patient fan-out.

A per-patient failure on diagnoses/coverage is logged and skipped so one bad
patient doesn't abort the whole batch. A rate-limit exhaustion on notes or
assessments for a facility marks that entity's watermark failed and stops
further patients in that facility+entity to avoid partial state.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2.extensions

from api_client import RateLimitExhausted, get_assessments, get_coverage, get_diagnoses, get_notes
from config import WATERMARK_BUFFER_SECONDS
from db import (
    advance_watermark,
    fail_watermark,
    read_watermark,
    set_watermark_running,
    upsert_assessments,
    upsert_coverage,
    upsert_diagnoses,
    upsert_notes,
)
from transform import (
    api_assessment_to_row,
    api_coverage_to_row,
    api_diagnosis_to_row,
    api_note_to_row,
)

logger = logging.getLogger(__name__)


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _parse_date_field(val: Any) -> datetime | None:
    """Coerce a date string or datetime to a timezone-aware datetime, or None."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def sync_diagnoses_and_coverage(
    conn: psycopg2.extensions.connection,
    source_id: int,
    patients: list[dict[str, Any]],
) -> dict[str, int]:
    """
    Fetch and upsert diagnoses and coverage for each patient using STRING patient_id.
    No since parameter — always fetches all records for changed patients.

    Returns counts dict: {"raw_diagnosis": N, "raw_coverage": N}.
    """
    diag_total = 0
    cov_total = 0
    fetched_at = datetime.now(timezone.utc)

    for patient in patients:
        patient_id_str: str | None = patient.get("patient_id")
        if not patient_id_str:
            logger.warning(
                "Patient int_id=%s has no string patient_id — skipping diagnoses/coverage",
                patient.get("id"),
            )
            continue

        try:
            diagnoses = get_diagnoses(patient_id_str)
            coverage = get_coverage(patient_id_str)
        except RateLimitExhausted as exc:
            logger.error(
                "Rate limit exhausted for diagnoses/coverage patient=%s: %s", patient_id_str, exc
            )
            continue
        except Exception as exc:
            logger.error("Error fetching diagnoses/coverage patient=%s: %s", patient_id_str, exc)
            continue

        diag_rows = [api_diagnosis_to_row(d, source_id, fetched_at) for d in diagnoses]
        cov_rows = [api_coverage_to_row(c, source_id, fetched_at) for c in coverage]

        try:
            if diag_rows:
                diag_total += upsert_diagnoses(conn, diag_rows)
            if cov_rows:
                cov_total += upsert_coverage(conn, cov_rows)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            logger.error("DB error upserting diagnoses/coverage patient=%s: %s", patient_id_str, exc)

    logger.info(
        "Diagnoses/coverage sync: %d diagnoses upserted, %d coverage upserted across %d patients",
        diag_total, cov_total, len(patients),
    )
    return {"raw_diagnosis": diag_total, "raw_coverage": cov_total}


def sync_notes_and_assessments(
    conn: psycopg2.extensions.connection,
    source_id: int,
    patients: list[dict[str, Any]],
) -> dict[str, int]:
    """
    Fetch and upsert notes and assessments for each patient using INTEGER id.
    Uses a per-facility watermark with since parameter.

    Returns counts dict: {"raw_note": N, "raw_assessment": N}.
    """
    # Group patients by facility so we can apply facility-level watermarks
    by_facility: dict[int, list[dict[str, Any]]] = {}
    for p in patients:
        fid = p.get("facility_id")
        if fid is not None:
            by_facility.setdefault(int(fid), []).append(p)
        else:
            logger.warning("Patient id=%s has no facility_id — skipping notes/assessments", p.get("id"))

    note_total = 0
    assessment_total = 0

    for facility_id, fac_patients in by_facility.items():
        for entity_type in ("note", "assessment"):
            since = read_watermark(conn, source_id, entity_type, facility_id)
            set_watermark_running(conn, source_id, entity_type, facility_id)

            logger.info(
                "Syncing %ss facility=%d (%d patients) since=%s",
                entity_type, facility_id, len(fac_patients), since or "beginning",
            )

            all_date_vals: list[datetime] = []
            entity_upserted = 0
            failed = False
            fetched_at = datetime.now(timezone.utc)

            for patient in fac_patients:
                patient_int_id: int | None = patient.get("id")
                if patient_int_id is None:
                    continue

                try:
                    if entity_type == "note":
                        records = get_notes(patient_int_id, since=since)
                        rows = [api_note_to_row(r, source_id, fetched_at) for r in records]
                        date_field = "effective_date"
                    else:
                        records = get_assessments(patient_int_id, since=since)
                        rows = [api_assessment_to_row(r, source_id, fetched_at) for r in records]
                        date_field = "assessment_date"

                except RateLimitExhausted as exc:
                    logger.error(
                        "Rate limit exhausted for %s patient_int_id=%s: %s",
                        entity_type, patient_int_id, exc,
                    )
                    failed = True
                    break  # stop this entity/facility; mark failed below
                except Exception as exc:
                    logger.error(
                        "Error fetching %ss patient_int_id=%s: %s",
                        entity_type, patient_int_id, exc,
                    )
                    continue

                try:
                    if rows:
                        if entity_type == "note":
                            upserted = upsert_notes(conn, rows)
                        else:
                            upserted = upsert_assessments(conn, rows)
                        conn.commit()
                        entity_upserted += upserted

                        for r in rows:
                            parsed = _parse_date_field(r.get(date_field))
                            if parsed:
                                all_date_vals.append(parsed)
                except Exception as exc:
                    conn.rollback()
                    logger.error(
                        "DB error upserting %ss patient_int_id=%s: %s",
                        entity_type, patient_int_id, exc,
                    )

            if failed:
                fail_watermark(conn, source_id, entity_type, facility_id)
            else:
                if all_date_vals:
                    max_date = max(all_date_vals)
                    new_synced_at = max_date - timedelta(seconds=WATERMARK_BUFFER_SECONDS)
                else:
                    # No new records; advance to now minus buffer
                    new_synced_at = fetched_at - timedelta(seconds=WATERMARK_BUFFER_SECONDS)
                    if since and since > new_synced_at:
                        new_synced_at = since  # never go backwards

                advance_watermark(
                    conn, source_id, entity_type, facility_id, new_synced_at, entity_upserted
                )
                if entity_type == "note":
                    note_total += entity_upserted
                else:
                    assessment_total += entity_upserted

                logger.info(
                    "Facility %d %ss: %d rows upserted, watermark -> %s",
                    facility_id, entity_type, entity_upserted, new_synced_at.isoformat(),
                )

    return {"raw_note": note_total, "raw_assessment": assessment_total}
