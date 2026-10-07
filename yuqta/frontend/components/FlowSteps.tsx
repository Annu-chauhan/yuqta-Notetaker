const steps = [
  "Meeting",
  "Transcript",
  "Understand",
  "Correlate",
  "KPI",
  "RCA",
  "Dashboard",
  "Recommendations",
];

export function FlowSteps() {
  return (
    <ol className="flex flex-wrap items-center gap-x-2 gap-y-3">
      {steps.map((step, index) => (
        <li key={step} className="flex items-center gap-2">
          <span className="rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium">
            <span className="mr-1.5 font-mono text-xs text-muted">{String(index + 1).padStart(2, "0")}</span>
            {step}
          </span>
          {index < steps.length - 1 && (
            <span className="text-muted" aria-hidden>
              →
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}
