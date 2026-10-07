import type { Recommendation } from "@/lib/api";

const priorityStyles: Record<Recommendation["priority"], { icon: string; label: string; className: string }> = {
  high: { icon: "▲", label: "High", className: "bg-rose-50 text-rose-800 dark:bg-rose-950 dark:text-rose-300" },
  medium: { icon: "■", label: "Medium", className: "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300" },
  low: { icon: "▼", label: "Low", className: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300" },
};

export function RecommendationList({ items }: { items: Recommendation[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted">No actions recommended.</p>;
  }
  return (
    <ol className="space-y-3">
      {items.map((item, index) => {
        const priority = priorityStyles[item.priority];
        return (
          <li key={item.key} className="rounded-lg border border-line bg-surface p-4">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <span className="font-mono text-xs text-muted">{String(index + 1).padStart(2, "0")}</span>
              <span className={`rounded px-2 py-0.5 text-xs font-semibold ${priority.className}`}>
                <span aria-hidden>{priority.icon}</span> {priority.label}
              </span>
              <p className="font-semibold">{item.title}</p>
            </div>
            <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm">
              <div className="flex gap-1.5">
                <dt className="text-muted">Owner</dt>
                <dd>{item.owner ?? "Unassigned"}</dd>
              </div>
              <div className="flex gap-1.5">
                <dt className="text-muted">Due</dt>
                <dd>{item.due ?? "Not set"}</dd>
              </div>
            </dl>
            <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-muted">
              {item.rationale.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
            {item.evidence.length > 0 && (
              <p className="mt-2 text-xs text-muted">
                From the meeting:{" "}
                {item.evidence.map((quote, i) => (
                  <span key={i}>
                    {i > 0 && " · "}“{quote.quote}” — {quote.speaker}
                  </span>
                ))}
              </p>
            )}
          </li>
        );
      })}
    </ol>
  );
}
