import Link from "next/link";

import { checkBotsAction, leaveBotAction } from "@/app/meetings/actions";
import { AutoRefresh } from "@/components/AutoRefresh";
import { InviteBotForm } from "@/components/InviteBotForm";
import type { BotStatus, MeetingBot, MeetingBotList } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const ACTIVE: BotStatus[] = ["joining", "waiting", "in_call", "recording", "processing"];

const statusStyle: Record<BotStatus, { label: string; className: string }> = {
  joining: { label: "Joining", className: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300" },
  waiting: { label: "Waiting to be let in", className: "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300" },
  in_call: { label: "In the call", className: "bg-sky-50 text-sky-800 dark:bg-sky-950 dark:text-sky-300" },
  recording: { label: "● Recording", className: "bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300" },
  processing: { label: "Transcribing", className: "bg-sky-50 text-sky-800 dark:bg-sky-950 dark:text-sky-300" },
  transcribed: { label: "Transcribed", className: "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300" },
  analyzed: { label: "✓ Analyzed", className: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300" },
  failed: { label: "✕ Failed", className: "bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300" },
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
          <span className="break-all">{bot.meeting_url}</span> · {formatDateTime(bot.created_at)}
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
        {inCall && (
          <form action={leaveBotAction}>
            <input type="hidden" name="botId" value={bot.id} />
            <button type="submit" className={`${button} border border-line bg-surface hover:bg-background`}>
              End recording
            </button>
          </form>
        )}
      </div>
    </li>
  );
}

export function LiveMeetingsPanel({ data }: { data: MeetingBotList }) {
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
