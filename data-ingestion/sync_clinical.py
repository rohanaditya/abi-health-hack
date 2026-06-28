"""
Clinical data sync: diagnoses, coverage, notes, and assessments.

sync_diagnoses_and_coverage  — uses STRING patient_id; no since param.
sync_notes_and_assessments   — uses INTEGER patient id; since from per-facility watermark.

API calls run in parallel (bounded by MAX_CONCURRENT_REQUESTS); DB writes stay on the
main thread because psycopg2 connections are not thread-safe.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2.extensions

from api_client import RateLimitExhausted, get_assessments, get_coverage, get_diagnoses, get_notes
from config import MAX_CONCURRENT_REQUESTS, WATERMARK_BUFFER_SECONDS
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


def _parse_date_field(val: Any) -> datetime | None:
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


def _fetch_diagnoses_and_coverage(patient_id_str: str) -> tuple[list[dict], list[dict]]:
    return get_diagnoses(patient_id_str), get_coverage(patient_id_str)


def _fetch_notes(patient_int_id: int, since: datetime | None) -> list[dict]:
    return get_notes(patient_int_id, since=since)


def _fetch_assessments(patient_int_id: int, since: datetime | None) -> list[dict]:
    return get_assessments(patient_int_id, since=since)


def sync_diagnoses_and_coverage(
    conn: psycopg2.extensions.connection,
    source_id: int,
    patients: list[dict[str, Any]],
) -> dict[str, int]:
    """
    Fetch and upsert diagnoses and coverage for each patient using STRING patient_id.
    Returns {"raw_diagnosis": N, "raw_coverage": N}.
    """
    diag_total = 0
    cov_total = 0
    fetched_at = datetime.now(timezone.utc)

    eligible = [
        p for p in patients
        if p.get("patient_id")
    ]
    skipped = len(patients) - len(eligible)
    if skipped:
        logger.warning("%d patients missing string patient_id — skipping", skipped)

    if not eligible:
        return {"raw_diagnosis": 0, "raw_coverage": 0}

    logger.info(
        "Fetching diagnoses/coverage for %d patients (%d workers)",
        len(eligible), MAX_CONCURRENT_REQUESTS,
    )

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as pool:
        futures = {
            pool.submit(_fetch_diagnoses_and_coverage, p["patient_id"]): p
            for p in eligible
        }

        for future in as_completed(futures):
            patient = futures[future]
            patient_id_str: str = patient["patient_id"]

            try:
                diagnoses, coverage = future.result()
            except RateLimitExhausted as exc:
                logger.error("Rate limit exhausted diagnoses/coverage patient=%s: %s", patient_id_str, exc)
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
        "Diagnoses/coverage sync: %d diagnoses, %d coverage upserted across %d patients",
        diag_total, cov_total, len(patients),
    )
    return {"raw_diagnosis": diag_total, "raw_coverage": cov_total}


def sync_notes_and_assessments(
    conn: psycopg2.extensions.connection,
    source_id: int,
    patients: list[dict[str, Any]],
) -> dict[str, int]:
    """
    Fetch and upsert notes and assessments per patient using INTEGER id.
    Uses per-facility watermark with since parameter.
    Returns {"raw_note": N, "raw_assessment": N}.
    """
    by_facility: dict[int, list[dict[str, Any]]] = {}
    for p in patients:
        fid = p.get("facility_id")
        if fid is not None:
            by_facility.setdefault(int(fid), []).append(p)

    note_total = 0
    assessment_total = 0

    for facility_id, fac_patients in by_facility.items():
        for entity_type in ("note", "assessment"):
            since = read_watermark(conn, source_id, entity_type, facility_id)
            set_watermark_running(conn, source_id, entity_type, facility_id)

            eligible = [p for p in fac_patients if p.get("id") is not None]

            logger.info(
                "Syncing %ss facility=%d (%d patients, %d workers) since=%s",
                entity_type, facility_id, len(eligible), MAX_CONCURRENT_REQUESTS,
                since or "beginning",
            )

            all_date_vals: list[datetime] = []
            entity_upserted = 0
            failed = False
            fetched_at = datetime.now(timezone.utc)
            date_field = "effective_date" if entity_type == "note" else "assessment_date"

            if not eligible:
                advance_watermark(
                    conn, source_id, entity_type, facility_id,
                    fetched_at - timedelta(seconds=WATERMARK_BUFFER_SECONDS), 0,
                )
                continue

            fetch_fn = _fetch_notes if entity_type == "note" else _fetch_assessments
            to_row = api_note_to_row if entity_type == "note" else api_assessment_to_row
            upsert_fn = upsert_notes if entity_type == "note" else upsert_assessments

            with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as pool:
                futures = {
                    pool.submit(fetch_fn, p["id"], since): p
                    for p in eligible
                }

                for future in as_completed(futures):
                    patient = futures[future]
                    patient_int_id: int = patient["id"]

                    try:
                        records = future.result()
                        rows = [to_row(r, source_id, fetched_at) for r in records]
                    except RateLimitExhausted as exc:
                        logger.error(
                            "Rate limit exhausted %s patient_id=%s: %s",
                            entity_type, patient_int_id, exc,
                        )
                        failed = True
                        break
                    except Exception as exc:
                        logger.error(
                            "Error fetching %ss patient_id=%s: %s",
                            entity_type, patient_int_id, exc,
                        )
                        continue

                    try:
                        if rows:
                            upserted = upsert_fn(conn, rows)
                            conn.commit()
                            entity_upserted += upserted
                            for r in rows:
                                parsed = _parse_date_field(r.get(date_field))
                                if parsed:
                                    all_date_vals.append(parsed)
                    except Exception as exc:
                        conn.rollback()
                        logger.error(
                            "DB error upserting %ss patient_id=%s: %s",
                            entity_type, patient_int_id, exc,
                        )

            if failed:
                fail_watermark(conn, source_id, entity_type, facility_id)
            else:
                if all_date_vals:
                    new_synced_at = max(all_date_vals) - timedelta(seconds=WATERMARK_BUFFER_SECONDS)
                else:
                    new_synced_at = fetched_at - timedelta(seconds=WATERMARK_BUFFER_SECONDS)
                    if since and since > new_synced_at:
                        new_synced_at = since

                advance_watermark(conn, source_id, entity_type, facility_id, new_synced_at, entity_upserted)
                if entity_type == "note":
                    note_total += entity_upserted
                else:
                    assessment_total += entity_upserted

                logger.info(
                    "Facility %d %ss: %d rows upserted, watermark -> %s",
                    facility_id, entity_type, entity_upserted, new_synced_at.isoformat(),
                )

    return {"raw_note": note_total, "raw_assessment": assessment_total}
