import type { CorrelatedSignal } from "@/lib/api";

const kindLabels: Record<CorrelatedSignal["kind"], string> = {
  metric_change: "Metric",
  order_change: "Orders",
  renewal_risk: "Renewal",
  action_item: "Action",
};

const checkStyles: Record<CorrelatedSignal["data_check"]["status"], { icon: string; label: string; className: string }> = {
  confirmed: { icon: "✓", label: "Confirmed by data", className: "text-emerald-700 dark:text-emerald-400" },
  contradicted: { icon: "✕", label: "Contradicted by data", className: "text-rose-700 dark:text-rose-400" },
  no_data: { icon: "?", label: "No data to check", className: "text-muted" },
};

export function SignalList({ signals }: { signals: CorrelatedSignal[] }) {
  if (signals.length === 0) {
    return <p className="text-sm text-muted">No business signals were found in this transcript.</p>;
  }
  return (
    <ol className="space-y-3">
      {signals.map((signal, index) => {
        const check = checkStyles[signal.data_check.status];
        return (
          <li key={index} className="rounded-lg border border-line bg-surface p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded bg-background px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide text-muted">
                {kindLabels[signal.kind]}
              </span>
              <p className="font-semibold">{signal.summary}</p>
            </div>
            <blockquote className="mt-2 border-l-2 border-line pl-3 text-sm text-muted">
              “{signal.evidence.quote}” — {signal.evidence.speaker}
            </blockquote>
            <p className={`mt-2 text-sm ${check.className}`}>
              <span aria-hidden className="font-bold">
                {check.icon}
              </span>{" "}
              <span className="font-medium">{check.label}:</span>{" "}
              <span className="text-foreground">{signal.data_check.detail}</span>
            </p>
          </li>
        );
      })}
    </ol>
  );
}
