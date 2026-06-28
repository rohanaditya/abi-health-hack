"""
Pure functions: API JSON -> DB column dicts.

Each function adds source_id, fetched_at, and row_hash (hash of the original
API payload). Field renames (e.g. last_modified_at -> source_last_modified_at)
are handled here. Nulls and missing optional keys are tolerated via .get().

CRITICAL ID types:
  - raw_patient/raw_note/raw_assessment.patient_id  = INTEGER (patient["id"])
  - raw_diagnosis/raw_coverage.patient_id           = STRING  (patient["patient_id"])
"""

import json
from datetime import datetime
from typing import Any

from hashing import row_hash


def api_patient_to_row(patient: dict[str, Any], source_id: int, fetched_at: datetime) -> dict[str, Any]:
    """Map /pcc/patients item to raw_patient columns."""
    return {
        "id": patient["id"],
        "source_id": source_id,
        "facility_id": patient.get("facility_id"),
        "patient_id": patient.get("patient_id"),
        "first_name": patient.get("first_name"),
        "last_name": patient.get("last_name"),
        "birth_date": patient.get("birth_date"),
        "gender": patient.get("gender"),
        "primary_payer_code": patient.get("primary_payer_code"),
        "is_new_admission": patient.get("is_new_admission"),
        "source_last_modified_at": patient.get("last_modified_at"),
        "fetched_at": fetched_at,
        "row_hash": row_hash(patient),
    }


def api_diagnosis_to_row(diagnosis: dict[str, Any], source_id: int, fetched_at: datetime) -> dict[str, Any]:
    """Map /pcc/diagnoses item to raw_diagnosis columns."""
    return {
        "id": diagnosis["id"],
        "source_id": source_id,
        "patient_id": diagnosis.get("patient_id"),  # STRING e.g. FA-001
        "icd10_code": diagnosis.get("icd10_code"),
        "icd10_description": diagnosis.get("icd10_description"),
        "clinical_status": diagnosis.get("clinical_status"),
        "onset_date": diagnosis.get("onset_date"),
        "source_last_modified_at": diagnosis.get("last_modified_at"),
        "fetched_at": fetched_at,
        "row_hash": row_hash(diagnosis),
    }


def api_coverage_to_row(coverage: dict[str, Any], source_id: int, fetched_at: datetime) -> dict[str, Any]:
    """Map /pcc/coverage item to raw_coverage columns."""
    return {
        "id": coverage["id"],
        "source_id": source_id,
        "patient_id": coverage.get("patient_id"),  # STRING e.g. FA-001
        "payer_name": coverage.get("payer_name"),
        "payer_code": coverage.get("payer_code"),
        "payer_type": coverage.get("payer_type"),
        "effective_from": coverage.get("effective_from"),
        "effective_to": coverage.get("effective_to"),
        "source_last_modified_at": coverage.get("last_modified_at"),
        "fetched_at": fetched_at,
        "row_hash": row_hash(coverage),
    }


def api_note_to_row(note: dict[str, Any], source_id: int, fetched_at: datetime) -> dict[str, Any]:
    """Map /pcc/notes item to raw_note columns."""
    return {
        "id": note["id"],
        "source_id": source_id,
        "patient_id": note.get("patient_id"),  # INTEGER
        "org_id": note.get("org_id"),
        "pcc_note_id": note.get("pcc_note_id"),
        "note_type": note.get("note_type"),
        "effective_date": note.get("effective_date"),
        "note_text": note.get("note_text"),
        "created_by": note.get("created_by"),
        "note_label": note.get("note_label"),
        "sync_version": note.get("sync_version"),
        "is_current": note.get("is_current"),
        "fetched_at": fetched_at,
        "row_hash": row_hash(note),
    }


def api_assessment_to_row(assessment: dict[str, Any], source_id: int, fetched_at: datetime) -> dict[str, Any]:
    """Map /pcc/assessments item to raw_assessment columns."""
    raw_json = assessment.get("raw_json")
    # Normalize to JSON string so db.py can wrap it in Json() for psycopg2 jsonb
    if isinstance(raw_json, dict):
        raw_json = json.dumps(raw_json)
    elif raw_json is not None and not isinstance(raw_json, str):
        raw_json = json.dumps(raw_json)

    return {
        "id": assessment["id"],
        "source_id": source_id,
        "patient_id": assessment.get("patient_id"),  # INTEGER
        "org_id": assessment.get("org_id"),
        "pcc_assessment_id": assessment.get("pcc_assessment_id"),
        "assessment_type": assessment.get("assessment_type"),
        "status": assessment.get("status"),
        "assessment_date": assessment.get("assessment_date"),
        "completion_date": assessment.get("completion_date"),
        "template_id": assessment.get("template_id"),
        "assessment_type_description": assessment.get("assessment_type_description"),
        "raw_json": raw_json,
        "sync_version": assessment.get("sync_version"),
        "is_current": assessment.get("is_current"),
        "fetched_at": fetched_at,
        "row_hash": row_hash(assessment),
    }
