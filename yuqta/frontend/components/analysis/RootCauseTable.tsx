import type { RootCause } from "@/lib/api";
import { formatUsd } from "@/lib/format";

/** Single-series bar (magnitude of each segment's decline) inside a table, so exact values stay readable. */
export function RootCauseTable({ causes, periodLabel }: { causes: RootCause[]; periodLabel: string }) {
  if (causes.length === 0) {
    return <p className="text-sm text-muted">Revenue did not decline, so there is nothing to explain.</p>;
  }
  const largest = Math.max(...causes.map((cause) => Math.abs(cause.contribution)));
  const width = (cause: RootCause) => `${(Math.abs(cause.contribution) / largest) * 100}%`;
  const tooltip = (cause: RootCause) =>
    `${cause.segment}: ${formatUsd(cause.previous)} → ${formatUsd(cause.current)} (${formatUsd(cause.contribution, true)})`;

  return (
    <>
      {/* Phones: one card per account so every column stays visible. */}
      <ul className="space-y-3 sm:hidden" aria-label={`Revenue decline by account, ${periodLabel}`}>
        {causes.map((cause) => (
          <li key={cause.segment} className="rounded-lg border border-line bg-surface p-4">
            <div className="flex items-baseline justify-between gap-3">
              <p className="font-semibold">
                {cause.segment}{" "}
                <DiscussedBadge mentioned={cause.mentioned_in_meeting} />
              </p>
              <p className="tabular-nums">
                {formatUsd(cause.contribution)} <span className="text-muted">· {cause.share_of_decline_pct.toFixed(1)}%</span>
              </p>
            </div>
            <div className="mt-2 h-3" title={tooltip(cause)}>
              <div className="h-3 rounded-r bg-brand" style={{ width: width(cause) }} />
            </div>
            <ul className="mt-2 space-y-1 text-sm text-muted">
              {cause.drivers.map((driver) => (
                <li key={driver}>{driver}</li>
              ))}
            </ul>
          </li>
        ))}
      </ul>

    <div className="hidden overflow-x-auto rounded-lg border border-line bg-surface sm:block">
      <table className="w-full min-w-[640px] text-left text-sm">
        <caption className="sr-only">Revenue decline by account, {periodLabel}</caption>
        <thead className="border-b border-line text-xs text-muted">
          <tr>
            <th scope="col" className="px-4 py-2 font-medium">Account</th>
            <th scope="col" className="w-[38%] px-4 py-2 font-medium">Revenue change</th>
            <th scope="col" className="px-4 py-2 text-right font-medium">Share</th>
            <th scope="col" className="px-4 py-2 font-medium">Drivers (from data)</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {causes.map((cause) => (
            <tr key={cause.segment} className="align-top">
              <th scope="row" className="px-4 py-3 font-semibold">
                {cause.segment}
                <span className="mt-1 block">
                  <DiscussedBadge mentioned={cause.mentioned_in_meeting} />
                </span>
              </th>
              <td className="px-4 py-3">
                <div
                  className="flex items-center gap-3"
                  title={tooltip(cause)}
                >
                  <div className="h-3 flex-1">
                    <div
                      className="h-3 rounded-r bg-brand"
                      style={{ width: width(cause) }}
                    />
                  </div>
                  <span className="w-16 shrink-0 text-right tabular-nums">{formatUsd(cause.contribution)}</span>
                </div>
              </td>
              <td className="px-4 py-3 text-right tabular-nums">{cause.share_of_decline_pct.toFixed(1)}%</td>
              <td className="px-4 py-3 text-muted">
                <ul className="space-y-1">
                  {cause.drivers.map((driver) => (
                    <li key={driver}>{driver}</li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </>
  );
}

function DiscussedBadge({ mentioned }: { mentioned: boolean }) {
  return (
    <span
      className={`inline-block w-fit rounded px-1.5 py-0.5 text-[11px] font-medium ${
        mentioned ? "bg-brand/10 text-brand" : "bg-background text-muted"
      }`}
    >
      {mentioned ? "Discussed" : "Not discussed"}
    </span>
  );
}
