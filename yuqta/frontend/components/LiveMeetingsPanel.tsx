import Link from "next/link";

import { checkBotsAction, leaveBotAction, syncCalendarAction } from "@/app/meetings/actions";
import { AutoRefresh } from "@/components/AutoRefresh";
import { DeleteBotButton } from "@/components/DeleteMeetingButton";
import { InviteBotForm } from "@/components/InviteBotForm";
import type { BotStatus, CalendarAutoJoin, MeetingBot, MeetingBotList } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

// Statuses that change within seconds. Scheduled bots may be hours away, so they don't trigger refreshes.
const ACTIVE: BotStatus[] = ["joining", "waiting", "in_call", "recording", "processing"];

const statusStyle: Record<BotStatus, { label: string; className: string }> = {
  scheduled: { label: "Scheduled", className: "bg-violet-50 text-violet-800 dark:bg-violet-950 dark:text-violet-300" },
  joining: { label: "Joining", className: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300" },
  waiting: { label: "Waiting to be let in", className: "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300" },
  in_call: { label: "In the call", className: "bg-sky-50 text-sky-800 dark:bg-sky-950 dark:text-sky-300" },
  recording: { label: "● Recording", className: "bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300" },
  processing: { label: "Transcribing", className: "bg-sky-50 text-sky-800 dark:bg-sky-950 dark:text-sky-300" },
  transcribed: { label: "Transcribed", className: "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300" },
  analyzed: { label: "✓ Analyzed", className: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300" },
  failed: { label: "✕ Failed", className: "bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300" },
  cancelled: { label: "Cancelled", className: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400" },
};

const button = "inline-flex h-8 items-center whitespace-nowrap rounded-md px-3 text-xs font-semibold";

function BotRow({ bot, botName }: { bot: MeetingBot; botName: string }) {
  const style = statusStyle[bot.status];
  const inCall = ["joining", "waiting", "in_call", "recording"].includes(bot.status);
  return (
    <li className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2">
          <span className="truncate font-medium">{bot.title}</span>
          <span className={`rounded px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide ${style.className}`}>
            {style.label}
          </span>
        </p>
        <p className="mt-1 text-xs text-muted">
          <span className="break-all">{bot.meeting_url}</span> ·{" "}
          {bot.join_at && bot.status === "scheduled" ? `joins ${formatDateTime(bot.join_at)}` : formatDateTime(bot.created_at)}
          {bot.calendar_event_id && " · from calendar"}
        </p>
        <p className={`mt-1 text-sm ${bot.status === "failed" ? "text-rose-700 dark:text-rose-400" : "text-muted"}`}>
          {bot.status === "waiting" ? (
            <>
              Waiting to be let in: in the call, click <strong className="text-foreground">Admit</strong> for{" "}
              <strong className="text-foreground">{botName}</strong>.
            </>
          ) : (
            bot.detail
          )}
        </p>
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">
        {bot.meeting_id && (
          <Link href={`/meetings/${bot.meeting_id}`} className={`${button} border border-line bg-surface hover:bg-background`}>
            Transcript &amp; analysis
          </Link>
        )}
        {bot.status === "analyzed" && bot.meeting_id && (
          <Link href={`/dashboard?meeting=${bot.meeting_id}`} className={`${button} bg-brand text-white hover:opacity-90`}>
            Dashboard →
          </Link>
        )}
        {["transcribed", "analyzed", "failed"].includes(bot.status) && (
          <DeleteBotButton botId={bot.id} title={bot.title} hasMeeting={bot.meeting_id !== null} />
        )}
        {(inCall || bot.status === "scheduled") && (
          <form action={leaveBotAction}>
            <input type="hidden" name="botId" value={bot.id} />
            <button type="submit" className={`${button} border border-line bg-surface hover:bg-background`}>
              {bot.status === "scheduled" ? "Cancel" : "End recording"}
            </button>
          </form>
        )}
      </div>
    </li>
  );
}

function CalendarBox({ calendar }: { calendar: CalendarAutoJoin }) {
  const on = calendar.enabled && calendar.google_connected && !calendar.last_error;
  const every = calendar.poll_seconds < 60 ? `${calendar.poll_seconds} s` : `${Math.round(calendar.poll_seconds / 60)} min`;
  return (
    <div className="mt-4 rounded-md border border-line bg-background px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 font-medium">
          <span aria-hidden className={`h-2 w-2 rounded-full ${on ? "bg-emerald-500" : "bg-slate-400"}`} />
          Calendar auto-join {on ? "is on" : "is off"}
        </p>
        {calendar.enabled && calendar.google_connected && (
          <form action={syncCalendarAction}>
            <button type="submit" className={`${button} border border-line bg-surface hover:bg-background`}>
              Check calendar now
            </button>
          </form>
        )}
      </div>
      <p className="mt-1 text-muted">
        {!calendar.enabled ? (
          "Set AUTO_JOIN_CALENDAR=true to send Yuqta to every Google Meet on your calendar automatically."
        ) : !calendar.google_connected ? (
          <>
            <Link href="/import" className="font-medium text-foreground underline underline-offset-2">
              Connect Google Calendar
            </Link>{" "}
            on the Import page to start{calendar.google_mode === "mock" ? " (GOOGLE_MODE=mock uses a fake calendar)" : ""}.
          </>
        ) : (
          <>
            Yuqta joins every Google Meet in the next {calendar.hours_ahead} hours on{" "}
            {calendar.accounts.length > 1
              ? `${calendar.accounts.length} calendars (${calendar.accounts.join(", ")})`
              : (calendar.accounts[0] ?? "your calendar")}
            , a minute before it starts. Checked every {every}
            {calendar.last_run_at ? `, last ${formatDateTime(calendar.last_run_at)}` : ""}.{" "}
            <Link href="/import" className="underline underline-offset-2">
              Add or remove accounts
            </Link>
          </>
        )}
      </p>
      {calendar.enabled && calendar.last_error && (
        <p role="alert" className="mt-1 text-rose-700 dark:text-rose-400">
          {calendar.last_error}
        </p>
      )}
      {calendar.recent.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-xs text-muted">
          {calendar.recent.slice(0, 3).map((line, index) => (
            <li key={index}>{line}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function LiveMeetingsPanel({ data, calendar }: { data: MeetingBotList; calendar: CalendarAutoJoin | null }) {
  const active = data.bots.some((bot) => ACTIVE.includes(bot.status));
  return (
    <section aria-labelledby="live-heading" className="rounded-lg border border-line bg-surface p-4">
      {active && <AutoRefresh seconds={Math.max(5, Math.min(10, data.poll_seconds))} />}
      <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 id="live-heading" className="font-semibold">
            Invite Yuqta to a live meeting
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            <strong className="text-foreground">{data.bot_name}</strong> joins the call as a participant and records who
            says what. When the call ends, Yuqta transcribes it, checks it against your business data and updates the{" "}
            <Link href="/dashboard" className="underline underline-offset-2">dashboard</Link>, with no further clicks.
            {data.provider === "mock" && " (Demo mode: a simulated bot plays the sample meeting in about 30 seconds.)"}
          </p>
        </div>
        {active && (
          <form action={checkBotsAction}>
            <button type="submit" className={`${button} border border-line bg-surface hover:bg-background`}>
              Check now
            </button>
          </form>
        )}
      </div>

      <div className="mt-4">
        <InviteBotForm />
      </div>

      {calendar && <CalendarBox calendar={calendar} />}

      {data.bots.length > 0 && (
        <ul className="mt-4 divide-y divide-line border-t border-line">
          {data.bots.slice(0, 5).map((bot) => (
            <BotRow key={bot.id} bot={bot} botName={data.bot_name} />
          ))}
        </ul>
      )}
    </section>
  );
}
