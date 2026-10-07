import type { MeetingSummary } from "@/lib/api";

const styles: Record<MeetingSummary["status"], string> = {
  created: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  transcribed: "bg-sky-50 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  analyzed: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  failed: "bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
};

export function StatusBadge({ status }: { status: MeetingSummary["status"] }) {
  return (
    <span className={`rounded px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide ${styles[status]}`}>
      {status}
    </span>
  );
}
