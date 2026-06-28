"use client";

import { useState } from "react";
import type { EligibilityResult, RoutingDecision } from "@/lib/types";
import RoutingBadge from "./RoutingBadge";

interface Props {
  patient: EligibilityResult;
  onClose: () => void;
  onMove: (id: number, decision: RoutingDecision) => Promise<void>;
}

const FACILITY_NAMES: Record<number, string> = {
  101: "Sunrise Care Center",
  102: "Riverside SNF",
  103: "Maplewood Health",
};

export default function PatientDetailModal({ patient, onClose, onMove }: Props) {
  const [moving, setMoving] = useState<RoutingDecision | null>(null);

  const facilityName = patient.facility_id
    ? FACILITY_NAMES[patient.facility_id] ?? `Facility ${patient.facility_id}`
    : "—";

  const measureStr =
    patient.length_cm != null && patient.width_cm != null
      ? `${patient.length_cm} × ${patient.width_cm}${patient.depth_cm != null ? ` × ${patient.depth_cm}` : ""} cm`
      : "—";

  async function handleMove(decision: RoutingDecision) {
    setMoving(decision);
    try {
      await onMove(patient.id, decision);
      onClose();
    } finally {
      setMoving(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-2xl mx-4 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="bg-[#1A4D2E] px-6 py-4 flex items-start justify-between">
          <div>
            <h2 className="text-white text-lg font-semibold">
              {patient.patient_display_name ?? "Unknown Patient"}
            </h2>
            <p className="text-green-200 text-sm mt-0.5">
              {patient.patient_external_id ?? "—"} · {facilityName}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <RoutingBadge decision={patient.routing_decision} />
            <button
              onClick={onClose}
              className="text-white/70 hover:text-white text-xl leading-none"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="px-6 py-5 grid grid-cols-2 gap-x-8 gap-y-4 text-sm">
          <Field label="Wound Type" value={patient.wound_type} />
          <Field label="Stage" value={patient.wound_stage} />
          <Field label="Location" value={patient.location} />
          <Field label="Measurements" value={measureStr} />
          <Field label="Drainage" value={patient.drainage_amount} />
          <Field label="Active Wound" value={patient.has_active_wound != null ? (patient.has_active_wound ? "Yes" : "No") : null} />
          <Field label="Active MCB" value={patient.has_active_mcb != null ? (patient.has_active_mcb ? "Yes" : "No") : null} />
          <Field label="Payer Code" value={patient.qualifying_payer_code} />
          <Field
            label="Confidence"
            value={patient.extraction_confidence != null ? `${Math.round(patient.extraction_confidence * 100)}%` : null}
          />
          <Field
            label="Computed At"
            value={new Date(patient.computed_at).toLocaleString()}
          />
          <div className="col-span-2">
            <Field label="Decision Reason" value={patient.decision_reason} />
          </div>
        </div>

        {/* Actions — only shown for flag_for_review */}
        {patient.routing_decision === "flag_for_review" && (
          <div className="px-6 py-4 border-t border-gray-100 bg-amber-50 flex items-center gap-3">
            <span className="text-xs text-amber-700 font-medium mr-auto">
              Move this patient to:
            </span>
            <button
              disabled={!!moving}
              onClick={() => handleMove("auto_accept")}
              className="px-4 py-1.5 rounded-lg bg-green-700 hover:bg-green-800 text-white text-sm font-medium disabled:opacity-50 transition-colors"
            >
              {moving === "auto_accept" ? "Moving…" : "Auto-Accept"}
            </button>
            <button
              disabled={!!moving}
              onClick={() => handleMove("reject")}
              className="px-4 py-1.5 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-medium disabled:opacity-50 transition-colors"
            >
              {moving === "reject" ? "Moving…" : "Reject"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div>
      <dt className="text-xs font-semibold text-gray-400 uppercase tracking-wide">{label}</dt>
      <dd className="mt-0.5 text-gray-800">{value ?? "—"}</dd>
    </div>
  );
}
