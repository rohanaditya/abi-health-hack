"use client";

import { useState, useCallback, useEffect } from "react";
import type { EligibilityResult, RoutingDecision, SummaryCounts } from "@/lib/types";
import RoutingBadge from "./RoutingBadge";
import PatientDetailModal from "./PatientDetailModal";

const FACILITY_NAMES: Record<number, string> = {
  101: "Sunrise Care Center",
  102: "Riverside SNF",
  103: "Maplewood Health",
};

function facilityLabel(id: number | null) {
  if (id == null) return "—";
  return FACILITY_NAMES[id] ?? `Facility ${id}`;
}

const ROUTING_TABS: { value: RoutingDecision | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "auto_accept", label: "Auto-Accept" },
  { value: "flag_for_review", label: "Flag for Review" },
  { value: "reject", label: "Reject" },
];

export default function Dashboard() {
  const [results, setResults] = useState<EligibilityResult[]>([]);
  const [counts, setCounts] = useState<SummaryCounts>({ auto_accept: 0, flag_for_review: 0, reject: 0 });
  const [facilities, setFacilities] = useState<number[]>([]);
  const [routing, setRouting] = useState<RoutingDecision | "all">("all");
  const [facility, setFacility] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [mcb, setMcb] = useState(false);
  const [selected, setSelected] = useState<EligibilityResult | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (routing !== "all") params.set("routing", routing);
    if (facility !== "all") params.set("facility", facility);
    if (search) params.set("search", search);
    if (mcb) params.set("mcb", "true");

    const res = await fetch(`/api/eligibility?${params}`);
    const data = await res.json();
    setResults(data.results ?? []);
    setCounts(data.counts ?? { auto_accept: 0, flag_for_review: 0, reject: 0 });
    setFacilities(data.facilities ?? []);
    setLoading(false);
  }, [routing, facility, search, mcb]);

  useEffect(() => { fetchData(); }, [fetchData]);

  async function handleMove(id: number, decision: RoutingDecision) {
    await fetch(`/api/eligibility/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ routing_decision: decision }),
    });
    await fetchData();
  }

  return (
    <div className="min-h-screen bg-gray-50 font-[Inter,system-ui,sans-serif]">
      {/* Top Bar */}
      <header className="bg-[#1A4D2E] text-white px-6 py-4 flex items-center justify-between shadow-md">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-green-300 flex items-center justify-center text-[#1A4D2E] font-bold text-sm">W</div>
          <span className="text-lg font-semibold tracking-tight">WoundBill Worklist</span>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <CountChip label="Auto-Accept" value={counts.auto_accept} color="text-green-300" />
          <span className="text-green-700">·</span>
          <CountChip label="Review" value={counts.flag_for_review} color="text-amber-300" />
          <span className="text-green-700">·</span>
          <CountChip label="Reject" value={counts.reject} color="text-red-300" />
        </div>
      </header>

      {/* Filter Row */}
      <div className="bg-white border-b border-gray-200 px-6 py-3 flex flex-wrap items-center gap-4">
        {/* Routing Tabs */}
        <div className="flex bg-gray-100 rounded-lg p-0.5 text-sm">
          {ROUTING_TABS.map((tab) => (
            <button
              key={tab.value}
              onClick={() => setRouting(tab.value)}
              className={`px-3 py-1.5 rounded-md font-medium transition-colors ${
                routing === tab.value
                  ? "bg-white text-[#1A4D2E] shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Facility */}
        <select
          value={facility}
          onChange={(e) => setFacility(e.target.value)}
          className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#1A4D2E]/30"
        >
          <option value="all">All Facilities</option>
          {facilities.map((fid) => (
            <option key={fid} value={fid}>
              {facilityLabel(fid)}
            </option>
          ))}
        </select>

        {/* MCB Toggle */}
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none">
          <div
            onClick={() => setMcb((v) => !v)}
            className={`w-10 h-5 rounded-full transition-colors relative ${mcb ? "bg-[#1A4D2E]" : "bg-gray-300"}`}
          >
            <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${mcb ? "translate-x-5" : ""}`} />
          </div>
          Medicare Part B only
        </label>

        {/* Search */}
        <div className="flex-1 min-w-48 max-w-sm">
          <input
            type="search"
            placeholder="Search by name or patient ID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#1A4D2E]/30"
          />
        </div>

        <span className="ml-auto text-xs text-gray-400">
          {loading ? "Loading…" : `${results.length} patient${results.length !== 1 ? "s" : ""}`}
        </span>
      </div>

      {/* Table */}
      <main className="px-6 py-4">
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-xs text-gray-500 uppercase tracking-wide">
                <Th>Patient</Th>
                <Th>Facility</Th>
                <Th>Wound Type</Th>
                <Th>Measurements</Th>
                <Th>Payer / MCB</Th>
                <Th>Decision</Th>
                <Th>Reason</Th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-gray-400 text-sm">
                    Loading patients…
                  </td>
                </tr>
              ) : results.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-gray-400 text-sm">
                    No patients match the current filters.
                  </td>
                </tr>
              ) : (
                results.map((row) => (
                  <PatientRow
                    key={row.id}
                    row={row}
                    onClick={() => setSelected(row)}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      </main>

      {/* Modal */}
      {selected && (
        <PatientDetailModal
          patient={selected}
          onClose={() => setSelected(null)}
          onMove={handleMove}
        />
      )}
    </div>
  );
}

function CountChip({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className={`font-bold text-base ${color}`}>{value}</span>
      <span className="text-green-200 text-xs">{label}</span>
    </span>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="text-left px-4 py-2.5 font-semibold">{children}</th>;
}

function PatientRow({ row, onClick }: { row: EligibilityResult; onClick: () => void }) {
  const measureStr =
    row.length_cm != null && row.width_cm != null
      ? `${row.length_cm}×${row.width_cm}${row.depth_cm != null ? `×${row.depth_cm}` : ""} cm`
      : "—";

  const mcbLabel = row.has_active_mcb === true ? "MCB" : row.qualifying_payer_code ?? "—";

  return (
    <tr
      onClick={onClick}
      className="border-b border-gray-100 hover:bg-green-50 cursor-pointer transition-colors last:border-b-0 group"
    >
      <td className="px-4 py-3">
        <div className="font-medium text-gray-900 group-hover:text-[#1A4D2E]">
          {row.patient_display_name ?? "—"}
        </div>
        <div className="text-xs text-gray-400 mt-0.5">{row.patient_external_id ?? "—"}</div>
      </td>
      <td className="px-4 py-3 text-gray-600">
        {row.facility_id ? FACILITY_NAMES[row.facility_id] ?? `Fac ${row.facility_id}` : "—"}
      </td>
      <td className="px-4 py-3 text-gray-600">
        <div>{row.wound_type ?? "—"}</div>
        {row.wound_stage && <div className="text-xs text-gray-400">{row.wound_stage}</div>}
      </td>
      <td className="px-4 py-3 text-gray-600 font-mono text-xs">{measureStr}</td>
      <td className="px-4 py-3">
        <span className={`text-xs font-medium ${row.has_active_mcb ? "text-blue-700" : "text-gray-500"}`}>
          {mcbLabel}
        </span>
      </td>
      <td className="px-4 py-3">
        <RoutingBadge decision={row.routing_decision} />
      </td>
      <td className="px-4 py-3 text-gray-500 max-w-xs">
        <span className="line-clamp-2 text-xs">{row.decision_reason ?? "—"}</span>
      </td>
    </tr>
  );
}
