import type { MeetingPoint, Topic } from "@/lib/api";

const toneStyles: Record<"decision" | "risk" | "question", { icon: string; className: string }> = {
  decision: { icon: "✓", className: "text-emerald-700 dark:text-emerald-400" },
  risk: { icon: "⚠", className: "text-amber-700 dark:text-amber-400" },
  question: { icon: "?", className: "text-sky-700 dark:text-sky-400" },
};

/** Decisions, risks or open questions, each with the transcript line it came from. */
export function MeetingPoints({ items, tone, empty }: { items: MeetingPoint[]; tone: keyof typeof toneStyles; empty?: string }) {
  if (items.length === 0) return empty ? <p className="text-sm text-muted">{empty}</p> : null;
  const style = toneStyles[tone];
  return (
    <ul className="space-y-2">
      {items.map((item, index) => (
        <li key={index} className="rounded-lg border border-line bg-surface p-3">
          <p className="flex gap-2 font-medium">
            <span aria-hidden className={`font-bold ${style.className}`}>
              {style.icon}
            </span>
            {item.text}
          </p>
          <p className="mt-1 pl-5 text-xs text-muted">
            “{item.evidence.quote}” — {item.evidence.speaker}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function TopicList({ items }: { items: Topic[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {items.map((topic, index) => (
        <li key={index} className="rounded-lg border border-line bg-surface p-3">
          <p className="font-semibold">{topic.title}</p>
          <p className="mt-1 text-sm text-muted">{topic.summary}</p>
        </li>
      ))}
    </ul>
  );
}
