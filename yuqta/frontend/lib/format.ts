// Rendered on the server, so use a fixed time zone rather than the container's locale.
const dateTime = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

export function formatDateTime(value: string | null): string {
  return value ? `${dateTime.format(new Date(value))} UTC` : "—";
}

export function formatSeconds(value: number | null): string {
  if (value === null) return "";
  const minutes = Math.floor(value / 60);
  const seconds = Math.floor(value % 60);
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

const sourceLabels: Record<string, string> = {
  mock_stt: "Mock STT",
  deepgram_stt: "Deepgram",
  manual: "Manual",
  google_meet: "Google Meet",
  recall_bot: "Yuqta bot",
  mock_bot: "Yuqta bot (mock)",
};

export function formatSource(source: string): string {
  return sourceLabels[source] ?? source;
}

/** $2.39M, $440K, −$190K. Uses a true minus sign for negatives. */
export function formatUsd(value: number, signed = false): string {
  const sign = value < 0 ? "−" : signed && value > 0 ? "+" : "";
  const amount = Math.abs(value);
  let text: string;
  if (amount >= 1_000_000) text = `${(amount / 1_000_000).toFixed(2).replace(/\.?0+$/, "")}M`;
  else if (amount >= 1_000) text = `${Math.round(amount / 1_000)}K`;
  else text = amount.toFixed(0);
  return `${sign}$${text}`;
}

export function formatPct(value: number | null): string {
  if (value === null) return "n/a";
  const sign = value < 0 ? "−" : value > 0 ? "+" : "";
  return `${sign}${Math.abs(value).toFixed(1)}%`;
}

export function formatNumber(value: number, signed = false): string {
  const sign = value < 0 ? "−" : signed && value > 0 ? "+" : "";
  return `${sign}${Math.abs(value).toLocaleString("en-US")}`;
}

const month = new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric", timeZone: "UTC" });

/** "2026-08-01" -> "Aug 2026" */
export function formatPeriod(isoDate: string): string {
  return month.format(new Date(`${isoDate}T00:00:00Z`));
}
