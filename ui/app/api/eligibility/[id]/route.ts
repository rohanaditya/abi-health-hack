import { NextRequest, NextResponse } from "next/server";
import { getPool } from "@/lib/db";
import type { RoutingDecision } from "@/lib/types";

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await req.json();
  const newDecision: RoutingDecision = body.routing_decision;

  const allowed: RoutingDecision[] = ["auto_accept", "flag_for_review", "reject"];
  if (!allowed.includes(newDecision)) {
    return NextResponse.json({ error: "Invalid routing_decision" }, { status: 400 });
  }

  const pool = getPool();
  const result = await pool.query(
    `UPDATE eligibility_result SET routing_decision = $1 WHERE id = $2 RETURNING *`,
    [newDecision, Number(id)]
  );

  if (result.rowCount === 0) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  return NextResponse.json({ result: result.rows[0] });
}
