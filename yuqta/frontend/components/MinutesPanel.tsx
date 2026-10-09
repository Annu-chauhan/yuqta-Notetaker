"use client";

import { useActionState } from "react";

import { sendMinutesAction, type ActionState } from "@/app/meetings/actions";
import type { MinutesStatus } from "@/lib/api";

const initialState: ActionState = { error: null };

const statusText: Record<MinutesStatus["status"], { label: string; className: string }> = {
  not_sent: { label: "Not sent", className: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300" },
  awaiting_approval: { label: "Waiting for approval", className: "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300" },
  sent: { label: "✓ Sent", className: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300" },
  failed: { label: "✕ Failed", className: "bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300" },
  skipped: { label: "Not sent", className: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300" },
};

export function MinutesPanel({ meetingId, minutes, sentAt }: { meetingId: string; minutes: MinutesStatus; sentAt: string | null }) {
  const [state, action, pending] = useActionState(sendMinutesAction, initialState);
  const badge = statusText[minutes.status];
  const external = new Set(minutes.external);
  const button = minutes.status === "awaiting_approval" ? "Approve and send" : minutes.status === "sent" ? "Send again" : "Send minutes";

  return (
    <section aria-labelledby="minutes-heading" className="mt-10 rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="minutes-heading" className="font-semibold">Minutes email</h2>
        <span className={`rounded px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide ${badge.className}`}>{badge.label}</span>
      </div>
      <p className="mt-1 text-sm text-muted">
        {minutes.status === "sent" && sentAt
          ? `Sent ${sentAt} to ${minutes.recipients.join(", ")}.`
          : minutes.detail ||
            (minutes.mode === "off"
              ? "Automatic minutes are off (MINUTES_EMAIL=off). You can still send them by hand."
              : "Summary, decisions, action items, risks and open questions, emailed to the participants.")}
      </p>

      {!minutes.mail_configured ? (
        <p className="mt-3 text-sm text-amber-800 dark:text-amber-300">
          Email is not set up yet: set SMTP_HOST, SMTP_USER, SMTP_PASSWORD and SMTP_FROM in .env (see .env.example).
        </p>
      ) : (
        <form action={action} className="mt-3 space-y-2">
          <input type="hidden" name="meetingId" value={meetingId} />
          <label htmlFor="minutes-recipients" className="block text-xs font-medium">
            Recipients <span className="font-normal text-muted">(comma-separated)</span>
          </label>
          <textarea
            id="minutes-recipients"
            name="recipients"
            rows={2}
            defaultValue={minutes.recipients.join(", ")}
            placeholder="name@company.com, colleague@company.com"
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
          />
          {external.size > 0 && (
            <p className="text-xs text-amber-800 dark:text-amber-300">
              Outside your organisation: {[...external].join(", ")}. Check before sending.
            </p>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={pending}
              className="inline-flex h-9 items-center rounded-md bg-brand px-3 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
            >
              {pending ? "Sending…" : button}
            </button>
            {state.error && <p role="alert" className="text-sm text-rose-700 dark:text-rose-400">{state.error}</p>}
            {!state.error && state.message && <p role="status" className="text-sm text-emerald-700 dark:text-emerald-400">{state.message}</p>}
          </div>
        </form>
      )}

      {minutes.preview_html && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-muted hover:text-foreground">Preview the email{minutes.subject ? `: ${minutes.subject}` : ""}</summary>
          {/* Sandboxed: the preview is HTML built by the backend from escaped meeting text; it runs no scripts. */}
          <iframe
            title="Minutes email preview"
            sandbox=""
            srcDoc={minutes.preview_html}
            className="mt-2 h-96 w-full rounded-md border border-line bg-white"
          />
        </details>
      )}
    </section>
  );
}
