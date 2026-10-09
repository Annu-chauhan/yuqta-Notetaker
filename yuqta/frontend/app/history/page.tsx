import type { Metadata } from "next";
import Link from "next/link";
import { unstable_rethrow } from "next/navigation";
import { connection } from "next/server";

import { KpiTiles } from "@/components/analysis/KpiTiles";
import { BarChartCard } from "@/components/dashboard/BarChartCard";
import { DeleteItemButton, DeleteMeetingButton } from "@/components/DeleteMeetingButton";
import { SiteHeader } from "@/components/SiteHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { ApiError, getHistory, type BarChartWidget, type HistoryItem, type KPI, type MeetingHistory } from "@/lib/api";
import { formatDateTime, formatSource } from "@/lib/format";

export const metadata: Metadata = { title: "History · Yuqta" };

const count = (key: string, label: string, value: number): KPI => ({
  key, label, unit: "count", value, previous: null, current: null, change: null, change_pct: null, customer: null,
});

function From({ item }: { item: HistoryItem }) {
  return (
    <Link href={`/meetings/${item.meeting_id}`} className="underline underline-offset-2">
      {item.meeting_title}
    </Link>
  );
}

function ItemList({ title, items, icon, tone }: { title: string; items: HistoryItem[]; icon: string; tone: string }) {
  return (
    <section aria-label={title}>
      <h2 className="mb-3 text-sm font-semibold">
        {title} <span className="font-normal text-muted">· {items.length}</span>
      </h2>
      {items.length === 0 ? (
        <p className="text-sm text-muted">None yet.</p>
      ) : (
        <ul className="space-y-2">
          {items.slice(0, 15).map((item) => (
            <li key={`${item.meeting_id}-${item.kind}-${item.index}`} className="flex items-start justify-between gap-3 rounded-lg border border-line bg-surface p-3">
              <div className="min-w-0">
                <p className="flex gap-2 font-medium">
                  <span aria-hidden className={`font-bold ${tone}`}>{icon}</span>
                  {item.text}
                </p>
                <p className="mt-1 pl-5 text-xs text-muted">
                  <From item={item} /> · {formatDateTime(item.date)}
                </p>
              </div>
              <DeleteItemButton meetingId={item.meeting_id} kind={item.kind} index={item.index} text={item.text} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ActionTable({ items }: { items: HistoryItem[] }) {
  if (items.length === 0) return <p className="text-sm text-muted">No action items yet.</p>;
  return (
    <div className="relative overflow-x-auto rounded-lg border border-line bg-surface">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="border-b border-line text-xs text-muted">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Task</th>
            <th scope="col" className="px-3 py-2 font-medium">Owner</th>
            <th scope="col" className="px-3 py-2 font-medium">Due</th>
            <th scope="col" className="px-3 py-2 font-medium">From meeting</th>
            <th scope="col" className="px-3 py-2 font-medium">
              <span className="sr-only">Remove</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {items.map((item) => (
            <tr key={`${item.meeting_id}-${item.index}`} className="align-top">
              <td className="px-3 py-2">
                <p className="font-medium">{item.text}</p>
                <p className="mt-0.5 text-xs text-muted">“{item.quote}” — {item.speaker}</p>
              </td>
              <td className="px-3 py-2">{item.owner ?? <span className="text-amber-700 dark:text-amber-400">Unassigned</span>}</td>
              <td className="px-3 py-2 whitespace-nowrap">{item.due ?? <span className="text-muted">Not set</span>}</td>
              <td className="px-3 py-2">
                <From item={item} />
                <p className="text-xs text-muted">{formatDateTime(item.date)}</p>
              </td>
              <td className="px-3 py-2">
                <DeleteItemButton meetingId={item.meeting_id} kind={item.kind} index={item.index} text={item.text} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function workload(history: MeetingHistory): BarChartWidget {
  return {
    type: "bar_chart",
    id: "workload",
    title: "Action items per person",
    subtitle: "Across all meetings",
    orientation: "horizontal",
    category_key: "owner",
    unit: "count",
    series: [{ key: "action_items", label: "Action items", role: "share" }],
    data: history.owners.map((row) => ({ owner: row.owner, action_items: row.action_items })),
  };
}

export default async function HistoryPage() {
  await connection();
  let history: MeetingHistory | null = null;
  let loadError: string | null = null;
  try {
    history = await getHistory();
  } catch (error) {
    unstable_rethrow(error);
    loadError = error instanceof ApiError ? error.message : "Could not load the meeting history.";
  }

  return (
    <div className="flex min-h-full flex-col">
      <SiteHeader />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-12 sm:px-6">
        <p className="font-mono text-xs uppercase tracking-widest text-brand">All meetings</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight">History</h1>
        <p className="mt-1 text-sm text-muted">Everything your meetings produced, in one place: who owes what, what was decided, what is at risk.</p>

        {loadError || !history ? (
          <p role="alert" className="mt-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
            {loadError}
          </p>
        ) : history.totals.meetings === 0 ? (
          <p className="mt-6 rounded-lg border border-dashed border-line px-4 py-10 text-center text-sm text-muted">
            No meetings yet. <Link href="/meetings" className="font-medium text-foreground underline">Invite Yuqta to a meeting</Link> to start.
          </p>
        ) : (
          <div className="mt-8 space-y-10">
            <KpiTiles
              previousLabel=""
              kpis={[
                count("meetings", "Meetings", history.totals.meetings),
                count("action_items", "Action items", history.totals.action_items),
                count("unassigned", "Without an owner", history.totals.unassigned_action_items),
                count("decisions", "Decisions", history.totals.decisions),
                count("risks", "Risks raised", history.totals.risks),
                count("questions", "Open questions", history.totals.open_questions),
              ]}
            />

            <section aria-label="Action items">
              <h2 className="mb-3 text-sm font-semibold">
                Action items across all meetings <span className="font-normal text-muted">· newest meeting first</span>
              </h2>
              <ActionTable items={history.action_items} />
            </section>

            {history.owners.length > 0 && <BarChartCard widget={workload(history)} />}

            <div className="grid gap-8 lg:grid-cols-2">
              <ItemList title="Decisions" items={history.decisions} icon="✓" tone="text-emerald-700 dark:text-emerald-400" />
              <ItemList title="Risks and concerns" items={history.risks} icon="⚠" tone="text-amber-700 dark:text-amber-400" />
              <ItemList title="Open questions" items={history.open_questions} icon="?" tone="text-sky-700 dark:text-sky-400" />
            </div>

            <section aria-label="Meetings">
              <h2 className="mb-3 text-sm font-semibold">Meetings</h2>
              <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
                {history.meetings.map((meeting) => (
                  <li key={meeting.id} className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <Link href={`/meetings/${meeting.id}`} className="font-semibold underline-offset-2 hover:underline">
                        {meeting.title}
                      </Link>
                      <p className="mt-0.5 text-xs text-muted">
                        {formatDateTime(meeting.date)} · {formatSource(meeting.source)}
                        {meeting.participants.length > 0 && ` · ${meeting.participants.join(", ")}`}
                      </p>
                      {meeting.headline && <p className="mt-1 line-clamp-2 text-sm text-muted">{meeting.headline}</p>}
                      {meeting.status === "analyzed" && (
                        <p className="mt-1 text-xs text-muted">
                          {meeting.action_items} tasks · {meeting.decisions} decisions · {meeting.risks} risks · {meeting.open_questions} questions
                        </p>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <StatusBadge status={meeting.status} />
                      {meeting.status === "analyzed" && (
                        <Link href={`/dashboard?meeting=${meeting.id}`} className="text-xs font-semibold text-brand hover:underline">
                          Dashboard →
                        </Link>
                      )}
                      <DeleteMeetingButton meetingId={meeting.id} title={meeting.title} />
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
