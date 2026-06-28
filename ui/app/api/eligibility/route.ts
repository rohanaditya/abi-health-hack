import { NextRequest, NextResponse } from "next/server";
import { getPool } from "@/lib/db";
import type { EligibilityResult, SummaryCounts } from "@/lib/types";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const routing = searchParams.get("routing");
  const facility = searchParams.get("facility");
  const search = searchParams.get("search");
  const mcb = searchParams.get("mcb");

  const pool = getPool();

  const conditions: string[] = [];
  const params: (string | number | boolean)[] = [];
  let idx = 1;

  if (routing && routing !== "all") {
    conditions.push(`routing_decision = $${idx++}`);
    params.push(routing);
  }
  if (facility && facility !== "all") {
    conditions.push(`facility_id = $${idx++}`);
    params.push(Number(facility));
  }
  if (search) {
    conditions.push(
      `(patient_display_name ILIKE $${idx} OR patient_external_id ILIKE $${idx})`
    );
    params.push(`%${search}%`);
    idx++;
  }
  if (mcb === "true") {
    conditions.push(`has_active_mcb = true`);
  }

  const where = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";

  const [rowsRes, countsRes, facilitiesRes] = await Promise.all([
    pool.query<EligibilityResult>(
      `SELECT * FROM eligibility_result ${where} ORDER BY computed_at DESC`,
      params
    ),
    pool.query<{ routing_decision: string; count: string }>(
      `SELECT routing_decision, COUNT(*) as count FROM eligibility_result GROUP BY routing_decision`
    ),
    pool.query<{ facility_id: number }>(
      `SELECT DISTINCT facility_id FROM eligibility_result WHERE facility_id IS NOT NULL ORDER BY facility_id`
    ),
  ]);

  const counts: SummaryCounts = {
    auto_accept: 0,
    flag_for_review: 0,
    reject: 0,
  };
  for (const row of countsRes.rows) {
    const key = row.routing_decision as keyof SummaryCounts;
    if (key in counts) counts[key] = Number(row.count);
  }

  return NextResponse.json({
    results: rowsRes.rows,
    counts,
    facilities: facilitiesRes.rows.map((r) => r.facility_id),
  });
}
