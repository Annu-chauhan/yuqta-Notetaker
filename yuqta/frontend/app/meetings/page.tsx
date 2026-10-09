import type { Metadata } from "next";
import Link from "next/link";
import { unstable_rethrow } from "next/navigation";
import { connection } from "next/server";

import { CreateSampleMeetingButton } from "@/components/CreateSampleMeetingButton";
import { DeleteMeetingButton } from "@/components/DeleteMeetingButton";
import { LiveMeetingsPanel } from "@/components/LiveMeetingsPanel";
import { SiteHeader } from "@/components/SiteHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { UploadAudioForm } from "@/components/UploadAudioForm";
import {
  ApiError,
  getCalendarAutoJoin,
  getSystemInfo,
  listBots,
  listMeetings,
  type CalendarAutoJoin,
  type MeetingBotList,
  type MeetingSummary,
  type SystemInfo,
} from "@/lib/api";
import { formatDateTime, formatSource } from "@/lib/format";

export const metadata: Metadata = { title: "Meetings · Yuqta" };

export default async function MeetingsPage() {
  await connection();
  let meetings: MeetingSummary[] = [];
  let system: SystemInfo | null = null;
  let bots: MeetingBotList | null = null;
  let calendar: CalendarAutoJoin | null = null;
  let loadError: string | null = null;
  try {
    [meetings, system, bots, calendar] = await Promise.all([listMeetings(), getSystemInfo(), listBots(), getCalendarAutoJoin()]);
  } catch (error) {
    unstable_rethrow(error);
    loadError = error instanceof ApiError ? error.message : "Could not load meetings.";
  }

  return (
    <div className="flex min-h-full flex-col">
      <SiteHeader />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-12 sm:px-6">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-brand">Step 01–02 · Meeting → Transcript</p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">Meetings</h1>
            <p className="mt-2 max-w-xl text-sm text-muted">
              Invite Yuqta to a live call or upload a recording.
              {system?.demo_mode && (
                <>
                  {" "}Or create the <strong className="font-semibold text-foreground">Enterprise Revenue Review</strong> demo.
                </>
              )}
            </p>
          </div>
          {system?.demo_mode && <CreateSampleMeetingButton />}
        </div>

        {bots && (
          <div className="mt-8">
            <LiveMeetingsPanel data={bots} calendar={calendar} />
          </div>
        )}

        {system && (
          <div className="mt-6">
            <UploadAudioForm
              provider={system.stt_provider === "deepgram" ? `Deepgram (${system.stt_model})` : "mock (returns the sample transcript)"}
            />
            <p className="mt-2 text-sm text-muted">
              Or{" "}
              <Link href="/import" className="font-medium text-foreground underline underline-offset-2">
                import a Google Meet transcript
              </Link>
              .
            </p>
          </div>
        )}

        <section className="mt-10" aria-label="Meeting list">
          {loadError ? (
            <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
              {loadError}
            </p>
          ) : meetings.length === 0 ? (
            <p className="rounded-lg border border-dashed border-line px-4 py-10 text-center text-sm text-muted">
              No meetings yet. Create the sample meeting to get started.
            </p>
          ) : (
            <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
              {meetings.map((meeting) => (
                <li key={meeting.id} className="flex items-center gap-2 pr-3 hover:bg-background">
                  <Link
                    href={`/meetings/${meeting.id}`}
                    className="flex min-w-0 flex-1 flex-col gap-2 px-4 py-4 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-semibold">{meeting.title}</p>
                      <p className="mt-1 text-xs text-muted">
                        {formatDateTime(meeting.created_at)} · {formatSource(meeting.source)} · {meeting.segment_count}{" "}
                        {meeting.segment_count === 1 ? "segment" : "segments"}
                      </p>
                    </div>
                    <StatusBadge status={meeting.status} />
                  </Link>
                  <DeleteMeetingButton meetingId={meeting.id} title={meeting.title} />
                </li>
              ))}
            </ul>
          )}
        </section>
      </main>
    </div>
  );
}
