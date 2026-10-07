import type { Metadata } from "next";
import Link from "next/link";
import { unstable_rethrow } from "next/navigation";
import { connection } from "next/server";

import { AutoImportPanel } from "@/components/AutoImportPanel";
import { SiteHeader } from "@/components/SiteHeader";
import {
  ApiError,
  getAutoImportStatus,
  getGoogleStatus,
  listConferenceRecords,
  listGoogleEvents,
  type AutoImportStatus,
  type ConferenceRecord,
  type GoogleEvent,
  type GoogleStatus,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";

import { connectGoogleAction, disconnectGoogleAction, importTranscriptAction } from "./actions";

export const metadata: Metadata = { title: "Import · Yuqta" };

const OAUTH_ERRORS: Record<string, string> = {
  access_denied: "Google access was declined.",
  invalid_state: "The sign-in link expired or was already used. Try again.",
  token_exchange_failed: "Google sign-in could not be completed. Try again.",
  missing_code: "Google did not return an authorization code. Try again.",
};
const RANGES = [1, 7, 30] as const;
const MEETING_CODE = /^[a-z]{3}-[a-z]{4}-[a-z]{3}$/;

const button = "inline-flex h-9 items-center whitespace-nowrap rounded-md px-3 text-sm font-semibold";
const primary = `${button} bg-brand text-white hover:opacity-90`;
const secondary = `${button} border border-line bg-surface font-medium hover:bg-background`;

function one(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function eventLink(event: GoogleEvent, days: number): string {
  const params = new URLSearchParams({ days: String(days), code: event.meeting_code, event: event.id });
  return `/import?${params}#event-${event.id}`;
}

function Transcripts({ records, event, back }: { records: ConferenceRecord[]; event: GoogleEvent; back: string }) {
  if (records.length === 0) {
    return <p className="text-sm text-muted">No Meet call found for this event. Records exist only after someone joins.</p>;
  }
  return (
    <ul className="space-y-3">
      {records.map((record) => (
        <li key={record.name} className="text-sm">
          <p className="text-xs text-muted">Call started {formatDateTime(record.start_time)}</p>
          {record.transcripts.length === 0 ? (
            <p className="mt-1 text-muted">No transcript was recorded. Transcription has to be on during the call.</p>
          ) : (
            record.transcripts.map((transcript) => (
              <form key={transcript.name} action={importTranscriptAction} className="mt-2 flex flex-wrap items-center gap-3">
                <input type="hidden" name="transcript_name" value={transcript.name} />
                <input type="hidden" name="title" value={event.title} />
                <input type="hidden" name="participants" value={JSON.stringify(event.attendees)} />
                <input type="hidden" name="back" value={back} />
                <span className="rounded bg-background px-2 py-0.5 font-mono text-[11px] uppercase text-muted">
                  {transcript.state.replace("_", " ")}
                </span>
                {transcript.docs_url && (
                  <a href={transcript.docs_url} target="_blank" rel="noopener noreferrer" className="text-brand underline underline-offset-2">
                    Open Doc
                  </a>
                )}
                <button type="submit" disabled={transcript.state === "STARTED"} className={`${primary} disabled:opacity-50`}>
                  Import into Yuqta
                </button>
              </form>
            ))
          )}
        </li>
      ))}
    </ul>
  );
}

export default async function ImportPage({ searchParams }: PageProps<"/import">) {
  await connection();
  const params = await searchParams;
  const days = RANGES.find((d) => String(d) === one(params.days)) ?? 7;
  const code = one(params.code);
  const selectedId = one(params.event);
  const oauthError = one(params.google_error);
  const importError = one(params.import_error);

  let status: GoogleStatus | null = null;
  let autoImport: AutoImportStatus | null = null;
  let events: GoogleEvent[] = [];
  let records: ConferenceRecord[] | null = null;
  let loadError: string | null = null;
  try {
    status = await getGoogleStatus();
    autoImport = await getAutoImportStatus();
    if (status.connected) {
      events = (await listGoogleEvents(days)).events;
      const selected = events.find((e) => e.id === selectedId);
      if (selected && code && MEETING_CODE.test(code)) {
        const timed = !selected.all_day;
        records = (await listConferenceRecords(code, timed ? selected.start ?? undefined : undefined, timed ? selected.end ?? undefined : undefined)).conference_records;
      }
    }
  } catch (error) {
    unstable_rethrow(error);
    loadError = error instanceof ApiError ? error.message : "Could not reach Google.";
  }
  const notice = importError ?? (oauthError ? OAUTH_ERRORS[oauthError] ?? `Google sign-in failed (${oauthError}).` : null) ?? loadError;

  return (
    <div className="flex min-h-full flex-col">
      <SiteHeader />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-12 sm:px-6">
        <p className="font-mono text-xs uppercase tracking-widest text-brand">Connector · Google Workspace</p>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-bold tracking-tight">Import from Google Meet</h1>
          {status && (
            <span className="rounded bg-background px-2 py-0.5 font-mono text-[11px] uppercase text-muted">
              {status.mode === "mock" ? "Mock Google (demo data)" : "Live Google"}
            </span>
          )}
        </div>
        <p className="mt-2 max-w-2xl text-sm text-muted">
          Pick a Calendar event with a Google Meet call and import its transcript. Yuqta then analyzes it like any other
          meeting.
        </p>

        {notice && (
          <p role="alert" className="mt-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
            {notice}
          </p>
        )}

        {status && !status.configured && (
          <p className="mt-6 rounded-lg border border-dashed border-line px-4 py-6 text-sm text-muted">
            Google is not configured on the server. Set <code>GOOGLE_CLIENT_ID</code> and <code>GOOGLE_CLIENT_SECRET</code>{" "}
            (see the README), or use <code>GOOGLE_MODE=mock</code>.
          </p>
        )}

        {status?.configured && !status.connected && (
          <div className="mt-8 flex flex-col gap-4 rounded-lg border border-line bg-surface p-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="font-semibold">Connect Google</h2>
              <p className="text-sm text-muted">Read-only access to Calendar events and Meet transcripts.</p>
            </div>
            <form action={connectGoogleAction}>
              <button type="submit" className={primary}>
                Connect Google
              </button>
            </form>
          </div>
        )}

        {status?.connected && (
          <>
            <div className="mt-8 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface px-4 py-3 text-sm">
              <p>
                Connected as <strong>{status.account?.name ?? status.account?.email}</strong>
                {status.account?.name && status.account.email ? <span className="text-muted"> · {status.account.email}</span> : null}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                {RANGES.map((range) => (
                  <Link key={range} href={`/import?days=${range}`} className={range === days ? primary : secondary}>
                    {range === 1 ? "Past day" : `Past ${range} days`}
                  </Link>
                ))}
                <form action={disconnectGoogleAction}>
                  <button type="submit" className={secondary}>
                    Disconnect
                  </button>
                </form>
              </div>
            </div>
            {autoImport && <AutoImportPanel status={autoImport} />}

            {status.missing_scopes.length > 0 && (
              <p className="mt-3 text-sm text-amber-700 dark:text-amber-400">
                Calendar or Meet access was not granted. Disconnect and connect again, allowing both.
              </p>
            )}

            <section className="mt-6" aria-label="Google Meet events">
              {events.length === 0 ? (
                <p className="rounded-lg border border-dashed border-line px-4 py-10 text-center text-sm text-muted">
                  No Google Meet events in this range.
                </p>
              ) : (
                <ul className="space-y-3">
                  {events.map((event) => {
                    const selected = event.id === selectedId;
                    return (
                      <li key={event.id} id={`event-${event.id}`} className="rounded-lg border border-line bg-surface p-4">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                          <div className="min-w-0">
                            <p className="font-semibold">{event.title}</p>
                            <p className="mt-0.5 text-xs text-muted">
                              {formatDateTime(event.start)} · {event.meeting_code}
                              {event.attendees.length > 0 && ` · ${event.attendees.length} attendee${event.attendees.length === 1 ? "" : "s"}`}
                            </p>
                          </div>
                          {!selected && (
                            <Link href={eventLink(event, days)} className={secondary}>
                              Find transcripts
                            </Link>
                          )}
                        </div>
                        {selected && records && (
                          <div className="mt-3 border-t border-dashed border-line pt-3">
                            <Transcripts records={records} event={event} back={eventLink(event, days).split("#")[0]} />
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
