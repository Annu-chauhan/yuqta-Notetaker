import Link from "next/link";

import { runAutoImportAction, simulateMeetingAction } from "@/app/import/actions";
import { AutoRefresh } from "@/components/AutoRefresh";
import type { AutoImportActivity, AutoImportStatus } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const statusStyle: Record<AutoImportActivity["status"], { label: string; className: string }> = {
  analyzed: { label: "✓ Analyzed", className: "text-emerald-700 dark:text-emerald-400" },
  imported: { label: "Imported", className: "text-amber-700 dark:text-amber-400" },
  duplicate: { label: "Already imported", className: "text-muted" },
  skipped: { label: "Skipped", className: "text-muted" },
  failed: { label: "✕ Failed, will retry", className: "text-rose-700 dark:text-rose-400" },
};

const button = "inline-flex h-9 items-center whitespace-nowrap rounded-md px-3 text-sm font-semibold";

export function AutoImportPanel({ status }: { status: AutoImportStatus }) {
  const listening = status.configured && status.connected && Boolean(status.events_subscription) && !status.error;
  const problem = status.error ?? (status.configured && status.connected ? status.last_error : null);

  return (
    <section id="auto-import" aria-labelledby="auto-import-heading" className="mt-8 rounded-lg border border-line bg-surface p-5">
      <AutoRefresh seconds={Math.max(10, status.poll_seconds)} />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 id="auto-import-heading" className="flex items-center gap-2 font-semibold">
            <span aria-hidden className={`h-2.5 w-2.5 rounded-full ${listening ? "bg-emerald-500" : "bg-slate-400"}`} />
            Automatic import {listening ? "is on" : "is off"}
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            {listening
              ? `When a Google Meet call ends and its transcript is ready, Yuqta imports and analyzes it automatically (checked every ${status.poll_seconds}s).`
              : status.configured
                ? "Connect Google to start listening for finished meetings."
                : "Set GOOGLE_PUBSUB_TOPIC and GOOGLE_PUBSUB_SUBSCRIPTION (see the README) to import finished meetings automatically."}
          </p>
          {status.last_poll_at && <p className="mt-1 text-xs text-muted">Last checked {formatDateTime(status.last_poll_at)}</p>}
        </div>
        {status.configured && status.connected && (
          <div className="flex flex-wrap gap-2">
            <form action={runAutoImportAction}>
              <button type="submit" className={`${button} border border-line bg-surface font-medium hover:bg-background`}>
                Check now
              </button>
            </form>
            {status.mode === "mock" && (
              <form action={simulateMeetingAction}>
                <button type="submit" className={`${button} bg-brand text-white hover:opacity-90`}>
                  Simulate a finished meeting
                </button>
              </form>
            )}
          </div>
        )}
      </div>

      {problem && (
        <p role="alert" className="mt-3 text-sm text-rose-700 dark:text-rose-400">
          {problem}
        </p>
      )}

      {status.recent.length > 0 && (
        <ul className="mt-4 divide-y divide-line border-t border-line text-sm">
          {status.recent.map((item, index) => {
            const style = statusStyle[item.status];
            return (
              <li key={`${item.transcript}-${index}`} className="flex flex-col gap-1 py-2 sm:flex-row sm:items-center sm:justify-between">
                <span className="min-w-0">
                  {item.meeting_id ? (
                    <Link href={`/meetings/${item.meeting_id}`} className="font-medium underline underline-offset-2">
                      {item.title ?? "Meeting"}
                    </Link>
                  ) : (
                    <span className="font-medium">{item.title ?? item.transcript ?? "Event"}</span>
                  )}
                  <span className="text-muted"> · {formatDateTime(item.at)}</span>
                  {item.status !== "analyzed" && item.detail && <span className="block text-xs text-muted">{item.detail}</span>}
                </span>
                <span className={`shrink-0 text-xs font-medium ${style.className}`}>{style.label}</span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
