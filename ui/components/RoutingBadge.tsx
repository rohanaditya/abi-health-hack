"use client";

import type { RoutingDecision } from "@/lib/types";

const CONFIG: Record<RoutingDecision, { label: string; className: string }> = {
  auto_accept: {
    label: "Auto-Accept",
    className: "bg-green-100 text-green-800 border border-green-300",
  },
  flag_for_review: {
    label: "Review",
    className: "bg-amber-100 text-amber-800 border border-amber-300",
  },
  reject: {
    label: "Reject",
    className: "bg-red-100 text-red-700 border border-red-300",
  },
};

export default function RoutingBadge({ decision }: { decision: RoutingDecision }) {
  const { label, className } = CONFIG[decision];
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${className}`}>
      {label}
    </span>
  );
}
