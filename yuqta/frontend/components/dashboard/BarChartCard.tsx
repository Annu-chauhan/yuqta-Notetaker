"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";

import type { BarChartWidget, ChartSeries } from "@/lib/api";
import { formatNumber, formatUsd } from "@/lib/format";

import { useVizColors, type VizColors } from "./useVizColors";

const BAR_MAX = 24; // px; marks never fill the whole band

function formatValue(value: number, unit: BarChartWidget["unit"]): string {
  if (unit === "usd") return formatUsd(value);
  if (unit === "percent") return `${value.toFixed(1)}%`;
  if (unit === "count") return formatNumber(value);
  return `${formatNumber(value)} units`;
}

const categoryLabels: Record<string, string> = { account: "Account", speaker: "Speaker", owner: "Owner" };

function seriesColor(series: ChartSeries, colors: VizColors): string {
  return colors[series.role];
}

function ChartTooltip({
  active,
  payload,
  label,
  widget,
  colors,
}: TooltipContentProps & { widget: BarChartWidget; colors: VizColors }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-line bg-surface px-3 py-2 text-sm shadow-sm">
      <p className="mb-1 text-xs text-muted">{label}</p>
      {widget.series.map((series) => {
        const row = payload[0].payload as Record<string, number>;
        const raw = row[series.key];
        return (
          <p key={series.key} className="flex items-center gap-2">
            <span aria-hidden className="inline-block h-0.5 w-3" style={{ background: seriesColor(series, colors) }} />
            <strong className="font-semibold tabular-nums">{formatValue(raw, widget.unit)}</strong>
            <span className="text-muted">{series.label}</span>
          </p>
        );
      })}
    </div>
  );
}

function Legend({ widget, colors }: { widget: BarChartWidget; colors: VizColors }) {
  if (widget.series.length < 2) return null; // a single series is named by the title
  return (
    <ul className="mb-2 flex flex-wrap gap-4 text-sm text-muted">
      {widget.series.map((series) => (
        <li key={series.key} className="flex items-center gap-2">
          <span aria-hidden className="inline-block h-3 w-3 rounded-sm" style={{ background: seriesColor(series, colors) }} />
          {series.label}
        </li>
      ))}
    </ul>
  );
}

function DataTable({ widget }: { widget: BarChartWidget }) {
  return (
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer text-muted hover:text-foreground">View as table</summary>
      <table className="mt-2 w-full text-left">
        <thead className="text-xs text-muted">
          <tr>
            <th scope="col" className="py-1 font-medium">{categoryLabels[widget.category_key] ?? widget.category_key}</th>
            {widget.series.map((series) => (
              <th key={series.key} scope="col" className="py-1 text-right font-medium">
                {series.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {widget.data.map((row) => (
            <tr key={String(row[widget.category_key])}>
              <th scope="row" className="py-1 font-normal">{String(row[widget.category_key])}</th>
              {widget.series.map((series) => (
                <td key={series.key} className="py-1 text-right tabular-nums">
                  {formatValue(Number(row[series.key]), widget.unit)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

export function BarChartCard({ widget }: { widget: BarChartWidget }) {
  const colors = useVizColors();
  const horizontal = widget.orientation === "horizontal";
  const axisStyle = { fill: colors.axis, fontSize: 12 };
  const tickFormatter = (value: number) => formatValue(value, widget.unit);
  // Declines are drawn as positive lengths, so their axis shows the negated value.
  const axisSign = widget.series.some((s) => s.role === "decline") ? -1 : 1;
  const categoryWidth = widget.category_key === "account" ? 64 : 120;

  // Declines are drawn as positive lengths from the baseline; labels keep the sign.
  const data = horizontal
    ? widget.data.map((row) => ({
        ...row,
        ...Object.fromEntries(widget.series.map((s) => [`${s.key}__length`, Math.abs(Number(row[s.key]))])),
      }))
    : widget.data;

  return (
    <figure className="rounded-lg border border-line bg-surface p-4">
      <figcaption className="mb-3">
        <h3 className="font-semibold">{widget.title}</h3>
        <p className="text-sm text-muted">{widget.subtitle}</p>
      </figcaption>
      <Legend widget={widget} colors={colors} />
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          {horizontal ? (
            <BarChart data={data} layout="vertical" margin={{ top: 4, right: 64, bottom: 4, left: 4 }}>
              <CartesianGrid horizontal={false} stroke={colors.grid} />
              <XAxis type="number" tickFormatter={(v: number) => formatValue(axisSign * v, widget.unit)} tick={axisStyle} axisLine={false} tickLine={false} />
              <YAxis type="category" dataKey={widget.category_key} tick={axisStyle} axisLine={{ stroke: colors.grid }} tickLine={false} width={categoryWidth} />
              <Tooltip cursor={{ fill: colors.grid, opacity: 0.4 }} content={(props) => <ChartTooltip {...props} widget={widget} colors={colors} />} />
              {widget.series.map((series) => (
                <Bar key={series.key} dataKey={`${series.key}__length`} name={series.label} fill={seriesColor(series, colors)} radius={[0, 4, 4, 0]} maxBarSize={BAR_MAX} isAnimationActive={false}>
                  <LabelList dataKey={series.key} position="right" formatter={(v: unknown) => formatValue(Number(v), widget.unit)} style={{ fill: colors.text, fontSize: 12 }} />
                </Bar>
              ))}
            </BarChart>
          ) : (
            <BarChart data={data} barGap={2} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
              <CartesianGrid vertical={false} stroke={colors.grid} />
              <XAxis dataKey={widget.category_key} tick={axisStyle} axisLine={{ stroke: colors.grid }} tickLine={false} />
              <YAxis tickFormatter={tickFormatter} tick={axisStyle} axisLine={false} tickLine={false} width={56} />
              <Tooltip cursor={{ fill: colors.grid, opacity: 0.4 }} content={(props) => <ChartTooltip {...props} widget={widget} colors={colors} />} />
              {widget.series.map((series) => (
                <Bar key={series.key} dataKey={series.key} name={series.label} fill={seriesColor(series, colors)} radius={[4, 4, 0, 0]} maxBarSize={BAR_MAX} isAnimationActive={false} />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      <DataTable widget={widget} />
    </figure>
  );
}
