"""
Ingestion orchestrator: health check -> patients -> clinical data -> summary.

Run with:
    python3 main.py
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from api_client import RateLimitExhausted, get_health
from db import get_connection, get_source_id
from sync_clinical import sync_diagnoses_and_coverage, sync_notes_and_assessments
from sync_patients import sync_patients

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def _merge_counts(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    result = dict(a)
    for k, v in b.items():
        result[k] = result.get(k, 0) + v
    return result


def main() -> None:
    logger.info("=== PCC ingestion run starting ===")

    try:
        health = get_health()
        logger.info("API health OK: %s", health)
    except RateLimitExhausted as exc:
        logger.error("API health check exhausted retries: %s", exc)
        sys.exit(1)
    except Exception as exc:
        logger.error("API health check failed: %s", exc)
        sys.exit(1)

    conn = get_connection()
    try:
        source_id = get_source_id(conn)
        logger.info("source_system id=%d", source_id)

        total_counts: dict[str, int] = {}

        # 1. Patients
        patients: list[dict[str, Any]] = []
        try:
            patients, patient_counts = sync_patients(conn, source_id)
            total_counts = _merge_counts(total_counts, patient_counts)
            logger.info(
                "Patient sync complete: %d fetched, %d upserted",
                len(patients), patient_counts.get("raw_patient", 0),
            )
        except Exception as exc:
            logger.error("Patient sync failed: %s", exc)

        # 2. Diagnoses + coverage
        if patients:
            try:
                dc_counts = sync_diagnoses_and_coverage(conn, source_id, patients)
                total_counts = _merge_counts(total_counts, dc_counts)
            except Exception as exc:
                logger.error("Diagnoses/coverage sync failed: %s", exc)

            # 3. Notes + assessments
            try:
                na_counts = sync_notes_and_assessments(conn, source_id, patients)
                total_counts = _merge_counts(total_counts, na_counts)
            except Exception as exc:
                logger.error("Notes/assessments sync failed: %s", exc)
        else:
            logger.info("No patients fetched — skipping clinical sync")

        total_upserted = sum(total_counts.values())
        if total_upserted == 0:
            print("No new data to add. Database already up to date.")
        else:
            print(f"Sync complete — {total_upserted} rows upserted:")
            for table, count in sorted(total_counts.items()):
                if count > 0:
                    print(f"  {table}: {count}")

    finally:
        conn.close()

    logger.info("=== PCC ingestion run finished ===")


if __name__ == "__main__":
    main()
