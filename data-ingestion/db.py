"""
Database helpers: connection, batched upserts, watermark management.

Upsert functions do NOT commit — the caller owns the transaction so a
mid-batch failure rolls back and the watermark stays put.
Watermark functions DO commit immediately (they are standalone bookkeeping ops).

Batched upserts use execute_values with ON CONFLICT ... WHERE row_hash differs,
so identical re-fetched rows are no-ops. RETURNING id lets us count actual
inserts/updates vs. skipped no-ops.
"""

import json
import logging
from datetime import datetime
from typing import Any

import psycopg2
import psycopg2.extras

from config import DATABASE_URL, SOURCE_CODE

logger = logging.getLogger(__name__)


def get_connection() -> psycopg2.extensions.connection:
    """Open and return a psycopg2 connection (autocommit=False)."""
    conn = psycopg2.connect(DATABASE_URL)
    psycopg2.extras.register_default_jsonb(conn)
    return conn


def get_source_id(conn: psycopg2.extensions.connection, code: str = SOURCE_CODE) -> int:
    """Look up the source_system.id for the given code. Raises if not found."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM source_system WHERE code = %s", (code,))
        row = cur.fetchone()
    if not row:
        raise ValueError(f"source_system row with code='{code}' not found — has the DB been seeded?")
    return row[0]


# ---------------------------------------------------------------------------
# Watermark helpers (each commits immediately)
# ---------------------------------------------------------------------------

def read_watermark(
    conn: psycopg2.extensions.connection,
    source_id: int,
    entity_type: str,
    facility_id: int,
) -> datetime | None:
    """Return last_synced_at for this (source, entity, facility), or None."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT last_synced_at FROM sync_watermark
            WHERE source_id = %s AND entity_type = %s AND facility_id = %s
            """,
            (source_id, entity_type, facility_id),
        )
        row = cur.fetchone()
    return row[0] if row else None


def set_watermark_running(
    conn: psycopg2.extensions.connection,
    source_id: int,
    entity_type: str,
    facility_id: int,
) -> None:
    """Mark a sync run as 'running'. Commits immediately."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sync_watermark
                (source_id, entity_type, facility_id, last_run_status, last_attempt_at, updated_at)
            VALUES (%s, %s, %s, 'running', NOW(), NOW())
            ON CONFLICT (source_id, entity_type, facility_id)
            DO UPDATE SET
                last_run_status = 'running',
                last_attempt_at = NOW(),
                updated_at = NOW()
            """,
            (source_id, entity_type, facility_id),
        )
    conn.commit()


def advance_watermark(
    conn: psycopg2.extensions.connection,
    source_id: int,
    entity_type: str,
    facility_id: int,
    new_synced_at: datetime,
    records_fetched: int,
) -> None:
    """Advance the watermark on success. Commits immediately."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sync_watermark
                (source_id, entity_type, facility_id, last_synced_at,
                 last_run_status, last_attempt_at, records_fetched, updated_at)
            VALUES (%s, %s, %s, %s, 'success', NOW(), %s, NOW())
            ON CONFLICT (source_id, entity_type, facility_id)
            DO UPDATE SET
                last_synced_at   = EXCLUDED.last_synced_at,
                last_run_status  = 'success',
                last_attempt_at  = NOW(),
                records_fetched  = EXCLUDED.records_fetched,
                updated_at       = NOW()
            """,
            (source_id, entity_type, facility_id, new_synced_at, records_fetched),
        )
    conn.commit()


def fail_watermark(
    conn: psycopg2.extensions.connection,
    source_id: int,
    entity_type: str,
    facility_id: int,
) -> None:
    """Mark a sync run as 'failed'. Does NOT advance last_synced_at. Commits immediately."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sync_watermark
                (source_id, entity_type, facility_id, last_run_status, last_attempt_at, updated_at)
            VALUES (%s, %s, %s, 'failed', NOW(), NOW())
            ON CONFLICT (source_id, entity_type, facility_id)
            DO UPDATE SET
                last_run_status = 'failed',
                last_attempt_at = NOW(),
                updated_at      = NOW()
            """,
            (source_id, entity_type, facility_id),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Batched upsert helpers (caller owns the transaction — no commit here)
# ---------------------------------------------------------------------------

def _extract_values(rows: list[dict[str, Any]], cols: list[str]) -> list[list[Any]]:
    return [[row[c] for c in cols] for row in rows]


def upsert_patients(conn: psycopg2.extensions.connection, rows: list[dict[str, Any]]) -> int:
    """
    Upsert raw_patient rows. Returns count of rows actually inserted or updated
    (excludes hash-match no-ops). Caller must commit.
    """
    if not rows:
        return 0
    cols = [
        "id", "source_id", "facility_id", "patient_id", "first_name", "last_name",
        "birth_date", "gender", "primary_payer_code", "is_new_admission",
        "source_last_modified_at", "fetched_at", "row_hash",
    ]
    update_cols = [c for c in cols if c != "id"]
    sql = f"""
        INSERT INTO raw_patient ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            {', '.join(f'{c} = EXCLUDED.{c}' for c in update_cols)}
        WHERE raw_patient.row_hash != EXCLUDED.row_hash
        RETURNING id
    """
    with conn.cursor() as cur:
        result = psycopg2.extras.execute_values(cur, sql, _extract_values(rows, cols), fetch=True)
    logger.debug("upsert_patients: %d/%d rows changed", len(result), len(rows))
    return len(result)


def upsert_diagnoses(conn: psycopg2.extensions.connection, rows: list[dict[str, Any]]) -> int:
    """Upsert raw_diagnosis rows. Conflict target: (source_id, patient_id, id)."""
    if not rows:
        return 0
    cols = [
        "id", "source_id", "patient_id", "icd10_code", "icd10_description",
        "clinical_status", "onset_date", "source_last_modified_at", "fetched_at", "row_hash",
    ]
    update_cols = [c for c in cols if c not in ("id", "source_id", "patient_id")]
    sql = f"""
        INSERT INTO raw_diagnosis ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (source_id, patient_id, id) DO UPDATE SET
            {', '.join(f'{c} = EXCLUDED.{c}' for c in update_cols)}
        WHERE raw_diagnosis.row_hash != EXCLUDED.row_hash
        RETURNING id
    """
    with conn.cursor() as cur:
        result = psycopg2.extras.execute_values(cur, sql, _extract_values(rows, cols), fetch=True)
    logger.debug("upsert_diagnoses: %d/%d rows changed", len(result), len(rows))
    return len(result)


def upsert_coverage(conn: psycopg2.extensions.connection, rows: list[dict[str, Any]]) -> int:
    """Upsert raw_coverage rows. Conflict target: (source_id, patient_id, id)."""
    if not rows:
        return 0
    cols = [
        "id", "source_id", "patient_id", "payer_name", "payer_code", "payer_type",
        "effective_from", "effective_to", "source_last_modified_at", "fetched_at", "row_hash",
    ]
    update_cols = [c for c in cols if c not in ("id", "source_id", "patient_id")]
    sql = f"""
        INSERT INTO raw_coverage ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (source_id, patient_id, id) DO UPDATE SET
            {', '.join(f'{c} = EXCLUDED.{c}' for c in update_cols)}
        WHERE raw_coverage.row_hash != EXCLUDED.row_hash
        RETURNING id
    """
    with conn.cursor() as cur:
        result = psycopg2.extras.execute_values(cur, sql, _extract_values(rows, cols), fetch=True)
    logger.debug("upsert_coverage: %d/%d rows changed", len(result), len(rows))
    return len(result)


def upsert_notes(conn: psycopg2.extensions.connection, rows: list[dict[str, Any]]) -> int:
    """Upsert raw_note rows. Conflict target: (id)."""
    if not rows:
        return 0
    cols = [
        "id", "source_id", "patient_id", "org_id", "pcc_note_id", "note_type",
        "effective_date", "note_text", "created_by", "note_label",
        "sync_version", "is_current", "fetched_at", "row_hash",
    ]
    update_cols = [c for c in cols if c != "id"]
    sql = f"""
        INSERT INTO raw_note ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            {', '.join(f'{c} = EXCLUDED.{c}' for c in update_cols)}
        WHERE raw_note.row_hash != EXCLUDED.row_hash
        RETURNING id
    """
    with conn.cursor() as cur:
        result = psycopg2.extras.execute_values(cur, sql, _extract_values(rows, cols), fetch=True)
    logger.debug("upsert_notes: %d/%d rows changed", len(result), len(rows))
    return len(result)


def upsert_assessments(conn: psycopg2.extensions.connection, rows: list[dict[str, Any]]) -> int:
    """
    Upsert raw_assessment rows. Conflict target: (id).
    raw_json is a JSON string; cast to jsonb via template.
    """
    if not rows:
        return 0
    cols = [
        "id", "source_id", "patient_id", "org_id", "pcc_assessment_id",
        "assessment_type", "status", "assessment_date", "completion_date",
        "template_id", "assessment_type_description", "raw_json",
        "sync_version", "is_current", "fetched_at", "row_hash",
    ]
    update_cols = [c for c in cols if c != "id"]

    # Cast raw_json (string) to jsonb in the template
    raw_json_idx = cols.index("raw_json") + 1  # 1-based position in VALUES tuple
    placeholders = ", ".join(
        f"%s::jsonb" if i + 1 == raw_json_idx else "%s"
        for i in range(len(cols))
    )
    template = f"({placeholders})"

    sql = f"""
        INSERT INTO raw_assessment ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            {', '.join(f'{c} = EXCLUDED.{c}' for c in update_cols)}
        WHERE raw_assessment.row_hash != EXCLUDED.row_hash
        RETURNING id
    """
    with conn.cursor() as cur:
        result = psycopg2.extras.execute_values(
            cur, sql, _extract_values(rows, cols), template=template, fetch=True
        )
    logger.debug("upsert_assessments: %d/%d rows changed", len(result), len(rows))
    return len(result)
