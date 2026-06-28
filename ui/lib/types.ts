export type RoutingDecision = "auto_accept" | "flag_for_review" | "reject";

export interface EligibilityResult {
  id: number;
  raw_patient_id: number;
  patient_external_id: string | null;
  patient_display_name: string | null;
  facility_id: number | null;
  wound_type: string | null;
  wound_stage: string | null;
  location: string | null;
  length_cm: number | null;
  width_cm: number | null;
  depth_cm: number | null;
  drainage_amount: string | null;
  has_active_wound: boolean | null;
  has_active_mcb: boolean | null;
  qualifying_payer_code: string | null;
  routing_decision: RoutingDecision;
  decision_reason: string | null;
  extraction_confidence: number | null;
  computed_at: string;
}

export interface SummaryCounts {
  auto_accept: number;
  flag_for_review: number;
  reject: number;
}
