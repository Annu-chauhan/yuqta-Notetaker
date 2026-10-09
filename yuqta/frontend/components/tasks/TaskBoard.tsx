import Link from "next/link";

import { DeleteItemButton } from "@/components/DeleteMeetingButton";
import type { ReminderStatus, Task, TaskList, TaskView } from "@/lib/api";
import { daysBetween, formatDateTime, formatDay } from "@/lib/format";

import { DueDateInput, OwnerInput, SendReminderButton, StatusSelect } from "./TaskControls";

const VIEWS: { view: TaskView; label: string; count: (list: TaskList) => number | null }[] = [
  { view: "open", label: "Open", count: (l) => l.counts.open + l.counts.in_progress },
  { view: "overdue", label: "Overdue", count: (l) => l.counts.overdue },
  { view: "due_soon", label: "Due in 7 days", count: () => null },
  { view: "done", label: "Done", count: (l) => l.counts.done },
  { view: "all", label: "All", count: () => null },
];

function href(view: TaskView, owner?: string) {
  const params = new URLSearchParams({ view });
  if (owner) params.set("owner", owner);
  return `/history?${params}#tasks`;
}

function DueBadge({ task, today }: { task: Task; today: string }) {
  if (task.status === "done") {
    return <span className="text-xs text-emerald-700 dark:text-emerald-400">✓ Done{task.completed_at ? ` ${formatDateTime(task.completed_at)}` : ""}</span>;
  }
  if (task.overdue && task.due_date) {
    const days = daysBetween(task.due_date, today);
    return (
      <span className="rounded bg-rose-50 px-1.5 py-0.5 text-xs font-semibold text-rose-700 dark:bg-rose-950 dark:text-rose-300">
        Overdue {days} day{days === 1 ? "" : "s"}
      </span>
    );
  }
  if (task.due_today) {
    return <span className="rounded bg-amber-50 px-1.5 py-0.5 text-xs font-semibold text-amber-800 dark:bg-amber-950 dark:text-amber-300">Due today</span>;
  }
  if (task.due_date) return <span className="text-xs text-muted">{formatDay(task.due_date)}</span>;
  return task.due_text ? <span className="text-xs text-muted">“{task.due_text}” (no date)</span> : null;
}

function ReminderBox({ reminders }: { reminders: ReminderStatus | null }) {
  if (!reminders) return null;
  const { preview } = reminders;
  return (
    <div className="mt-4 rounded-md border border-line bg-background px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 font-medium">
          <span aria-hidden className={`h-2 w-2 rounded-full ${reminders.configured ? "bg-emerald-500" : "bg-slate-400"}`} />
          Daily reminder email {reminders.configured ? "is on" : "is off"}
        </p>
        {reminders.configured && <SendReminderButton />}
      </div>
      <p className="mt-1 text-muted">
        {reminders.configured
          ? `Every day after ${String(reminders.hour).padStart(2, "0")}:00 (${reminders.timezone}) to ${reminders.recipients.join(", ")}: overdue tasks and tasks due in the next 3 days.`
          : "Connect Google on the Import page and allow sending email (or set SMTP in .env) to get overdue and due-soon tasks by email every morning."}
        {reminders.last_sent && ` Last sent ${formatDay(reminders.last_sent.day)}.`}
      </p>
      <p className="mt-1 text-xs text-muted">
        Today&apos;s reminder: {preview.overdue} overdue · {preview.due_today} due today · {preview.due_soon} due in the next 3 days
      </p>
      {reminders.last_error && (
        <p role="alert" className="mt-1 text-xs text-rose-700 dark:text-rose-400">
          {reminders.last_error}
        </p>
      )}
    </div>
  );
}

export function TaskBoard({ list, view, owner, reminders }: { list: TaskList; view: TaskView; owner?: string; reminders: ReminderStatus | null }) {
  const tab = "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-semibold";
  return (
    <section id="tasks" aria-labelledby="tasks-heading">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="tasks-heading" className="text-sm font-semibold">
          Action items <span className="font-normal text-muted">· tracked until done</span>
        </h2>
        <nav aria-label="Task views" className="flex flex-wrap gap-1.5">
          {VIEWS.map(({ view: v, label, count }) => {
            const n = count(list);
            const active = v === view;
            return (
              <Link
                key={v}
                href={href(v, owner)}
                aria-current={active ? "page" : undefined}
                className={`${tab} ${active ? "bg-brand text-white" : "border border-line bg-surface hover:bg-background"} ${v === "overdue" && n ? (active ? "" : "text-rose-700 dark:text-rose-400") : ""}`}
              >
                {label}
                {n !== null && <span className={active ? "opacity-80" : "text-muted"}>{n}</span>}
              </Link>
            );
          })}
        </nav>
      </div>

      {list.owners.length > 0 && (
        <p className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted">Person:</span>
          {[undefined, ...list.owners].map((name) => (
            <Link
              key={name ?? "everyone"}
              href={href(view, name)}
              className={`rounded-full px-2.5 py-1 ${name === owner ? "bg-foreground text-background" : "border border-line bg-surface hover:bg-background"}`}
            >
              {name ?? "Everyone"}
            </Link>
          ))}
          {list.counts.unassigned > 0 && (
            <span className="ml-1 text-amber-700 dark:text-amber-400">{list.counts.unassigned} open without an owner</span>
          )}
        </p>
      )}

      {list.tasks.length === 0 ? (
        <p className="mt-4 rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-muted">
          {view === "overdue" ? "Nothing is overdue. 🎉" : view === "done" ? "No completed tasks yet." : "No tasks here."}
        </p>
      ) : (
        <div className="relative mt-4 overflow-x-auto rounded-lg border border-line bg-surface">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="border-b border-line text-xs text-muted">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Status</th>
                <th scope="col" className="px-3 py-2 font-medium">Task</th>
                <th scope="col" className="px-3 py-2 font-medium">Owner</th>
                <th scope="col" className="px-3 py-2 font-medium">Due</th>
                <th scope="col" className="px-3 py-2 font-medium">
                  <span className="sr-only">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {list.tasks.map((task) => (
                <tr key={task.id} className={`align-top ${task.status === "done" ? "opacity-70" : ""}`}>
                  <td className="px-3 py-2">
                    <StatusSelect id={task.id} status={task.status} task={task.task} />
                  </td>
                  <td className="px-3 py-2">
                    <p className={`font-medium ${task.status === "done" ? "line-through decoration-1" : ""}`}>{task.task}</p>
                    {task.quote && (
                      <p className="mt-0.5 text-xs text-muted">
                        “{task.quote}” — {task.speaker}
                      </p>
                    )}
                    <p className="mt-0.5 text-xs text-muted">
                      <Link href={`/meetings/${task.meeting_id}`} className="underline underline-offset-2">
                        {task.meeting_title}
                      </Link>{" "}
                      · {formatDateTime(task.meeting_date)}
                    </p>
                  </td>
                  <td className="px-3 py-2">
                    <OwnerInput id={task.id} owner={task.owner} task={task.task} owners={list.owners} />
                  </td>
                  <td className="space-y-1 px-3 py-2">
                    <DueDateInput id={task.id} dueDate={task.due_date} task={task.task} />
                    <DueBadge task={task} today={list.today} />
                  </td>
                  <td className="px-3 py-2">
                    {task.index !== null && (
                      <DeleteItemButton meetingId={task.meeting_id} kind="action_items" index={task.index} text={task.task} />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ReminderBox reminders={reminders} />
    </section>
  );
}
