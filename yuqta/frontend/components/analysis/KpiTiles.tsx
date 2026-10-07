import type { KPI } from "@/lib/api";
import { formatNumber, formatPct, formatUsd } from "@/lib/format";

// For every KPI shown here, a decrease is bad news (revenue, order volume).
function Delta({ kpi, previousLabel }: { kpi: KPI; previousLabel: string }) {
  if (kpi.change === null || kpi.change === 0) return null;
  const down = kpi.change < 0;
  const amount = kpi.unit === "usd" ? formatUsd(kpi.change, true) : `${formatNumber(kpi.change, true)} units`;
  return (
    <p className={`mt-2 text-sm font-medium ${down ? "text-rose-700 dark:text-rose-400" : "text-emerald-700 dark:text-emerald-400"}`}>
      <span aria-hidden>{down ? "▼" : "▲"}</span> {amount} ({formatPct(kpi.change_pct)})
      <span className="font-normal text-muted"> vs {previousLabel}</span>
    </p>
  );
}

function Tile({ kpi, previousLabel }: { kpi: KPI; previousLabel: string }) {
  if (kpi.unit === "status") {
    const overdue = kpi.value === "overdue";
    return (
      <div className="rounded-lg border border-line bg-surface p-4">
        <p className="text-sm text-muted">{kpi.label}</p>
        <p className="mt-1 flex items-center gap-2 text-2xl font-semibold capitalize">
          {overdue && (
            <span aria-hidden className="text-amber-600 dark:text-amber-400">
              ⚠
            </span>
          )}
          {String(kpi.value)}
        </p>
        {kpi.current !== null && <p className="mt-2 text-sm text-muted">{formatUsd(kpi.current)} contract</p>}
      </div>
    );
  }
  const value = typeof kpi.value === "number" ? kpi.value : Number(kpi.value);
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <p className="text-sm text-muted">{kpi.label}</p>
      <p className="mt-1 text-2xl font-semibold">
        {kpi.unit === "usd" ? formatUsd(value) : kpi.unit === "count" ? formatNumber(value) : `${formatNumber(value)} units`}
      </p>
      <Delta kpi={kpi} previousLabel={previousLabel} />
    </div>
  );
}

export function KpiTiles({ kpis, previousLabel }: { kpis: KPI[]; previousLabel: string }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {kpis.map((kpi) => (
        <Tile key={kpi.key} kpi={kpi} previousLabel={previousLabel} />
      ))}
    </div>
  );
}
