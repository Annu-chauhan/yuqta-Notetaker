import type { Metadata } from "next";
import Link from "next/link";
import { notFound, unstable_rethrow } from "next/navigation";

import { AnalyzeMeetingButton } from "@/components/AnalyzeMeetingButton";
import { MeetingAnalysis } from "@/components/analysis/MeetingAnalysis";
import { SiteHeader } from "@/components/SiteHeader";
import { DeleteMeetingButton } from "@/components/DeleteMeetingButton";
import { MinutesPanel } from "@/components/MinutesPanel";
import { StatusBadge } from "@/components/StatusBadge";
import { ApiError, getAnalysis, getMeeting, getMinutes, type Analysis, type MeetingDetail, type MinutesStatus } from "@/lib/api";
import { formatDateTime, formatSeconds, formatSource } from "@/lib/format";

export const metadata: Metadata = { title: "Meeting · Yuqta" };

const speakerColors = [
  "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  "bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-200",
  "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  "bg-violet-100 text-violet-900 dark:bg-violet-950 dark:text-violet-200",
];

export default async function MeetingPage({ params }: PageProps<"/meetings/[id]">) {
  const { id } = await params;
  let meeting: MeetingDetail | null;
  let analysis: Analysis | null = null;
  let minutes: MinutesStatus | null = null;
  try {
    meeting = await getMeeting(id);
    if (meeting?.status === "analyzed") [analysis, minutes] = await Promise.all([getAnalysis(meeting.id), getMinutes(meeting.id)]);
  } catch (error) {
    unstable_rethrow(error);
    return <MeetingUnavailable message={error instanceof ApiError ? error.message : "Could not load this meeting."} />;
  }
  if (!meeting) notFound();

  const speakerOrder = [...new Set(meeting.segments.map((segment) => segment.speaker))];
  const colorFor = (speaker: string) => speakerColors[speakerOrder.indexOf(speaker) % speakerColors.length];

  return (
    <div className="flex min-h-full flex-col">
      <SiteHeader />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-12 sm:px-6">
        <Link href="/meetings" className="text-sm text-muted hover:text-foreground">
          ← All meetings
        </Link>

        <div className="mt-4 flex flex-wrap items-start justify-between gap-3">
          <h1 className="text-3xl font-bold tracking-tight">{meeting.title}</h1>
          <div className="flex items-center gap-3">
            <StatusBadge status={meeting.status} />
            {meeting.source.endsWith("_bot") && (
              <a
                href={`/meetings/${meeting.id}/recording`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex h-9 items-center rounded-md border border-line bg-surface px-3 text-sm font-medium hover:bg-background"
              >
                ▶ Watch recording
              </a>
            )}
            <DeleteMeetingButton meetingId={meeting.id} title={meeting.title} redirectTo="/meetings" showText />
          </div>
        </div>

        <dl className="mt-6 grid gap-4 rounded-lg border border-line bg-surface p-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-muted">Participants</dt>
            <dd className="mt-1">{meeting.participants.join(", ") || "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Source</dt>
            <dd className="mt-1">{formatSource(meeting.source)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Created</dt>
            <dd className="mt-1">{formatDateTime(meeting.created_at)}</dd>
          </div>
        </dl>

        <section className="mt-10" aria-labelledby="transcript-heading">
          <h2 id="transcript-heading" className="text-sm font-semibold">
            Transcript <span className="font-normal text-muted">· {meeting.segments.length} segments</span>
          </h2>
          {meeting.segments.length === 0 ? (
            <p className="mt-4 text-sm text-muted">
              {meeting.status === "failed" ? "Transcription failed for this meeting." : "No transcript yet."}
            </p>
          ) : (
            <ol className="mt-4 space-y-3">
              {meeting.segments.map((segment) => (
                <li key={segment.segment_index} className="flex gap-3 sm:gap-4">
                  <span className="w-10 shrink-0 pt-1 text-right font-mono text-xs text-muted">
                    {formatSeconds(segment.start_seconds)}
                  </span>
                  <div className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-4 py-3">
                    <span className={`rounded px-2 py-0.5 text-xs font-semibold ${colorFor(segment.speaker)}`}>
                      {segment.speaker}
                    </span>
                    <p className="mt-2 leading-relaxed">{segment.text}</p>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </section>

        <div className="mt-12 border-t border-line pt-10">
          {analysis ? (
            <>
              <MeetingAnalysis analysis={analysis} />
              {minutes && (
                <MinutesPanel
                  meetingId={meeting.id}
                  minutes={minutes}
                  sentAt={minutes.sent_at ? formatDateTime(minutes.sent_at) : null}
                  adminSentAt={minutes.admin_sent_at ? formatDateTime(minutes.admin_sent_at) : null}
                />
              )}
            </>
          ) : meeting.segments.length > 0 ? (
            <div className="flex flex-col gap-4 rounded-lg border border-dashed border-line px-5 py-6 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="font-semibold">Analyze this meeting</h2>
                <p className="mt-1 text-sm text-muted">
                  Extract business signals, check them against revenue, orders and renewals, then calculate KPIs and the
                  root cause.
                </p>
              </div>
              <AnalyzeMeetingButton meetingId={meeting.id} />
            </div>
          ) : null}
        </div>
      </main>
    </div>
  );
}

function MeetingUnavailable({ message }: { message: string }) {
  return (
    <div className="flex min-h-full flex-col">
      <SiteHeader />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-12 sm:px-6">
        <Link href="/meetings" className="text-sm text-muted hover:text-foreground">
          ← All meetings
        </Link>
        <h1 className="mt-4 text-3xl font-bold tracking-tight">Meeting</h1>
        <p role="alert" className="mt-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
          {message}
        </p>
      </main>
    </div>
  );
}
