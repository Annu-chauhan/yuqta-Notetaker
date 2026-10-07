import Link from "next/link";

import { AnalyzeMeetingButton } from "@/components/AnalyzeMeetingButton";
import { RecommendationList } from "@/components/RecommendationList";
import type { Analysis, MeetingIntelligence } from "@/lib/api";
import { formatPeriod } from "@/lib/format";

import { KpiTiles } from "./KpiTiles";
import { MeetingPoints, TopicList } from "./MeetingPoints";
import { RootCauseTable } from "./RootCauseTable";
import { SignalList } from "./SignalList";

const meetingTypes: Record<MeetingIntelligence["meeting_type"], string> = {
  sales: "Sales meeting",
  project: "Project meeting",
  product: "Product meeting",
  strategy: "Strategy meeting",
  general: "Meeting",
};

function WhoSpoke({ meeting }: { meeting: MeetingIntelligence }) {
  return (
    <ul className="space-y-2">
      {meeting.participation.map((row) => (
        <li key={row.speaker} className="grid grid-cols-[minmax(0,10rem)_1fr_auto] items-center gap-3 text-sm">
          <span className="truncate">{row.speaker}</span>
          <span className="h-2 overflow-hidden rounded bg-background" aria-hidden>
            <span className="block h-full rounded bg-brand" style={{ width: `${row.share_pct}%` }} />
          </span>
          <span className="tabular-nums text-muted">
            {row.share_pct.toFixed(0)}% · {row.turns} {row.turns === 1 ? "turn" : "turns"}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function MeetingAnalysis({ analysis }: { analysis: Analysis }) {
  const { meeting, periods } = analysis;
  const business = analysis.business_context && periods !== null;
  const previous = periods ? formatPeriod(periods.previous) : "";
  const current = periods ? formatPeriod(periods.current) : "";

  return (
    <section aria-labelledby="analysis-heading" className="space-y-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-mono text-xs uppercase tracking-widest text-brand">
            {business ? "Understand → Correlate → KPI → RCA → Recommendations" : "Meeting intelligence"}
          </p>
          <h2 id="analysis-heading" className="mt-2 text-2xl font-bold tracking-tight">
            Analysis
          </h2>
          <p className="mt-1 text-sm text-muted">
            {meetingTypes[meeting.meeting_type]}
            {business && ` · checked against business data (${current} vs ${previous})`} · by {analysis.llm_provider}
          </p>
        </div>
        <div className="flex flex-wrap items-start gap-2">
          <Link
            href={`/dashboard?meeting=${analysis.meeting_id}`}
            className="inline-flex h-9 items-center rounded-md bg-brand px-3 text-sm font-semibold text-white hover:opacity-90"
          >
            Open dashboard →
          </Link>
          <AnalyzeMeetingButton meetingId={analysis.meeting_id} reanalyze />
        </div>
      </div>

      <div className="rounded-lg border-l-4 border-brand bg-surface px-4 py-3">
        <p className="text-base leading-relaxed">{analysis.summary.headline}</p>
        {business && meeting.summary && <p className="mt-2 text-sm leading-relaxed text-muted">{meeting.summary}</p>}
      </div>

      {meeting.topics.length > 0 && (
        <div>
          <h3 className="mb-3 text-sm font-semibold">Topics discussed</h3>
          <TopicList items={meeting.topics} />
        </div>
      )}

      <div className="grid gap-8 lg:grid-cols-2">
        <div>
          <h3 className="mb-3 text-sm font-semibold">Decisions</h3>
          <MeetingPoints items={meeting.decisions} tone="decision" empty="No decisions were recorded." />
        </div>
        <div>
          <h3 className="mb-3 text-sm font-semibold">Risks and concerns</h3>
          <MeetingPoints items={meeting.risks} tone="risk" empty="No risks were raised." />
        </div>
        {meeting.open_questions.length > 0 && (
          <div>
            <h3 className="mb-3 text-sm font-semibold">Open questions</h3>
            <MeetingPoints items={meeting.open_questions} tone="question" />
          </div>
        )}
        {meeting.participation.length > 0 && (
          <div>
            <h3 className="mb-3 text-sm font-semibold">Who spoke</h3>
            <WhoSpoke meeting={meeting} />
          </div>
        )}
      </div>

      {business && (
        <>
          <div>
            <h3 className="mb-3 text-sm font-semibold">Key metrics</h3>
            <KpiTiles kpis={analysis.kpis} previousLabel={previous} />
          </div>

          <div>
            <h3 className="mb-3 text-sm font-semibold">
              Business signals <span className="font-normal text-muted">· checked against business data</span>
            </h3>
            <SignalList signals={analysis.signals} />
          </div>

          <div>
            <h3 className="mb-3 text-sm font-semibold">
              Root cause · revenue decline by account <span className="font-normal text-muted">({previous} → {current})</span>
            </h3>
            <RootCauseTable causes={analysis.root_causes} periodLabel={`${previous} to ${current}`} />
          </div>
        </>
      )}

      <div>
        <h3 className="mb-3 text-sm font-semibold">{business ? "Recommended actions" : "Next steps"}</h3>
        <RecommendationList items={analysis.recommendations} />
      </div>
    </section>
  );
}
