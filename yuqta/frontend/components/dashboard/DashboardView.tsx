import Link from "next/link";

import { KpiTiles } from "@/components/analysis/KpiTiles";
import { MeetingPoints, TopicList } from "@/components/analysis/MeetingPoints";
import { RecommendationList } from "@/components/RecommendationList";
import type { DashboardSpec, DashboardWidget } from "@/lib/api";
import { formatPeriod } from "@/lib/format";

import { BarChartCard } from "./BarChartCard";

/** Renders a dashboard spec widget by widget. The backend decides what is shown. */
function Widget({ widget }: { widget: DashboardWidget }) {
  switch (widget.type) {
    case "summary":
      return (
        <div className="rounded-lg border-l-4 border-brand bg-surface px-4 py-3 lg:col-span-2">
          <p className="text-base leading-relaxed">{widget.headline}</p>
          {widget.detail && <p className="mt-2 text-sm leading-relaxed text-muted">{widget.detail}</p>}
        </div>
      );
    case "kpis":
      return (
        <section className="lg:col-span-2" aria-label={widget.title}>
          <h2 className="mb-3 text-sm font-semibold">{widget.title}</h2>
          <KpiTiles kpis={widget.kpis} previousLabel={widget.previous_label} />
        </section>
      );
    case "bar_chart":
      return <BarChartCard widget={widget} />;
    case "topics":
      return (
        <section className="lg:col-span-2" aria-label={widget.title}>
          <h2 className="mb-3 text-sm font-semibold">{widget.title}</h2>
          <TopicList items={widget.items} />
        </section>
      );
    case "points":
      return (
        <section aria-label={widget.title}>
          <h2 className="mb-3 text-sm font-semibold">{widget.title}</h2>
          <MeetingPoints items={widget.items} tone={widget.tone} />
        </section>
      );
    case "recommendations":
      return (
        <section className="lg:col-span-2" aria-label={widget.title}>
          <h2 className="mb-3 text-sm font-semibold">{widget.title}</h2>
          <RecommendationList items={widget.items} />
        </section>
      );
  }
}

export function DashboardView({ spec }: { spec: DashboardSpec }) {
  return (
    <>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-mono text-xs uppercase tracking-widest text-brand">
            {spec.periods ? "Steps 07–08 · Dashboard → Recommendations" : "Meeting intelligence"}
          </p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight">Dashboard</h1>
          <p className="mt-1 text-sm text-muted">
            {spec.periods && `${formatPeriod(spec.periods.current)} vs ${formatPeriod(spec.periods.previous)} · `}
            From{" "}
            <Link href={`/meetings/${spec.meeting_id}`} className="font-medium text-foreground underline underline-offset-2">
              {spec.meeting_title}
            </Link>
          </p>
        </div>
      </div>
      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        {spec.widgets.map((widget, index) => (
          <Widget key={index} widget={widget} />
        ))}
      </div>
    </>
  );
}
