import "server-only";

import { unstable_rethrow } from "next/navigation";

import { verifySession } from "@/lib/dal";

export type HealthResponse = {
  status: "ok";
  app_env: string;
  database: "ok" | "unavailable";
};

export type Segment = {
  segment_index: number;
  speaker: string;
  text: string;
  start_seconds: number | null;
  end_seconds: number | null;
};

export type MeetingSummary = {
  id: string;
  title: string;
  participants: string[];
  source: string;
  status: "created" | "transcribed" | "analyzed" | "failed";
  occurred_at: string | null;
  created_at: string;
  segment_count: number;
};

export type MeetingDetail = MeetingSummary & { segments: Segment[] };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

// Server-side base URL for the FastAPI backend. Read at request time, so the same
// image works in Docker (http://backend:8000) and locally (http://localhost:8000).
function apiBaseUrl(): string {
  return process.env.API_INTERNAL_URL ?? "http://localhost:8000";
}

function authHeaders(): Record<string, string> {
  // Shared secret with the backend (API_AUTH_TOKEN). Server-side only; never sent to the browser.
  const token = process.env.API_AUTH_TOKEN;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

type RequestOptions = RequestInit & { timeoutMs?: number };

async function request<T>(path: string, { timeoutMs = 10_000, headers, ...init }: RequestOptions = {}): Promise<T> {
  await verifySession(); // every backend call requires a signed-in user (when login is enabled)
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
      ...init,
      headers: { ...authHeaders(), ...headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      // The backend may still finish the work; a refresh shows the result.
      throw new ApiError("Yuqta is taking longer than expected. Refresh the page in a minute to see the result.", 504);
    }
    throw new ApiError("The Yuqta API is unreachable.", 503);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    const detail = typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`;
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) return undefined as T; // e.g. DELETE: no body
  return (await response.json()) as T;
}

export async function getHealth(): Promise<HealthResponse | null> {
  try {
    return await request<HealthResponse>("/health", { timeoutMs: 3000 });
  } catch (error) {
    unstable_rethrow(error); // keep the login redirect from verifySession()
    return null;
  }
}

export const listMeetings = () => request<MeetingSummary[]>("/api/meetings");

export async function getMeeting(id: string): Promise<MeetingDetail | null> {
  try {
    return await request<MeetingDetail>(`/api/meetings/${encodeURIComponent(id)}`);
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 422)) return null;
    throw error;
  }
}

export const createSampleMeeting = () => request<MeetingDetail>("/api/meetings/sample", { method: "POST" });

export type Evidence = { segment_index: number; speaker: string; quote: string };

export type CorrelatedSignal = {
  kind: "metric_change" | "order_change" | "renewal_risk" | "action_item";
  summary: string;
  metric: string | null;
  direction: "up" | "down" | null;
  customers: string[];
  due: string | null;
  evidence: Evidence;
  data_check: { status: "confirmed" | "contradicted" | "no_data"; detail: string };
};

export type KPI = {
  key: string;
  label: string;
  unit: "usd" | "units" | "status" | "count";
  value: number | string;
  previous: number | null;
  current: number | null;
  change: number | null;
  change_pct: number | null;
  customer: string | null;
};

export type RootCause = {
  rank: number;
  segment: string;
  customer_id: string | null;
  previous: number;
  current: number;
  contribution: number;
  share_of_decline_pct: number;
  drivers: string[];
  mentioned_in_meeting: boolean;
  evidence: Evidence[];
};

export type Recommendation = {
  key: string;
  title: string;
  priority: "high" | "medium" | "low";
  customer: string | null;
  owner: string | null;
  due: string | null;
  rationale: string[];
  evidence: Evidence[];
};

export type MeetingPoint = { text: string; evidence: Evidence };
export type Topic = { title: string; summary: string; evidence: Evidence };
export type ActionItem = { task: string; owner: string | null; due: string | null; evidence: Evidence };
export type Participation = { speaker: string; turns: number; words: number; share_pct: number };

export type MeetingIntelligence = {
  summary: string;
  meeting_type: "sales" | "project" | "product" | "strategy" | "general";
  topics: Topic[];
  decisions: MeetingPoint[];
  action_items: ActionItem[];
  risks: MeetingPoint[];
  open_questions: MeetingPoint[];
  participation: Participation[];
};

export type Analysis = {
  meeting_id: string;
  status: string;
  llm_provider: string;
  /** True when the meeting discussed customers or revenue and business data was there to check it. */
  business_context: boolean;
  periods: { previous: string; current: string } | null;
  summary: {
    headline: string;
    revenue_change: number | null;
    revenue_change_pct: number | null;
    explained_by_discussed_pct: number | null;
    not_discussed: string[];
  };
  meeting: MeetingIntelligence;
  signals: CorrelatedSignal[];
  kpis: KPI[];
  root_causes: RootCause[];
  recommendations: Recommendation[];
};

export async function getAnalysis(meetingId: string): Promise<Analysis | null> {
  try {
    return await request<Analysis>(`/api/meetings/${encodeURIComponent(meetingId)}/analysis`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

// The AI analysis of a real transcript takes 10-60 s, far longer than an ordinary API call.
export const analyzeMeeting = (meetingId: string) =>
  request<Analysis>(`/api/meetings/${encodeURIComponent(meetingId)}/analyze`, { method: "POST", timeoutMs: 180_000 });

export type ChartSeries = { key: string; label: string; role: "previous" | "current" | "decline" | "share" };

export type BarChartWidget = {
  type: "bar_chart";
  id: string;
  title: string;
  subtitle: string;
  orientation: "vertical" | "horizontal";
  category_key: string;
  unit: "usd" | "units" | "percent" | "count";
  series: ChartSeries[];
  data: Record<string, number | string>[];
};

export type DashboardWidget =
  | { type: "summary"; headline: string; detail?: string | null }
  | { type: "kpis"; title: string; previous_label: string; kpis: KPI[] }
  | BarChartWidget
  | { type: "recommendations"; title: string; items: Recommendation[] }
  | { type: "topics"; title: string; items: Topic[] }
  | { type: "points"; id: string; title: string; tone: "decision" | "risk" | "question"; items: MeetingPoint[] };

export type DashboardSpec = {
  version: 1;
  title: string;
  meeting_id: string;
  meeting_title: string;
  periods: { previous: string; current: string } | null;
  widgets: DashboardWidget[];
};

async function orNullOn404<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 422)) return null;
    throw error;
  }
}

export const getLatestDashboard = () => orNullOn404(request<DashboardSpec>("/api/dashboard/latest"));

export const getMeetingDashboard = (meetingId: string) =>
  orNullOn404(request<DashboardSpec>(`/api/meetings/${encodeURIComponent(meetingId)}/dashboard`));

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

// --- Audio upload (Deepgram or mock STT) -------------------------------------------------

/** Forwards the browser's upload to the backend. Transcription can take minutes for long audio. */
export const uploadMeetingAudio = (form: FormData) =>
  request<MeetingDetail>("/api/meetings/audio", { method: "POST", body: form, timeoutMs: 11 * 60_000 });

// --- Google Meet connector ------------------------------------------------------------

export type GoogleStatus = {
  mode: "mock" | "live";
  configured: boolean;
  connected: boolean;
  account: { email: string | null; name: string | null } | null;
  missing_scopes: string[];
};

export type GoogleEvent = {
  id: string;
  title: string;
  start: string | null;
  end: string | null;
  all_day: boolean;
  meeting_code: string;
  attendees: string[];
};

export type ConferenceRecord = {
  name: string;
  start_time: string | null;
  end_time: string | null;
  transcripts: { name: string; state: string; docs_url: string | null }[];
};

export const getGoogleStatus = () => request<GoogleStatus>("/api/google/status");
export const connectGoogle = (returnPath: string) =>
  request<{ authorization_url: string }>("/api/google/connect", json({ return_path: returnPath }));
export const disconnectGoogle = () => request<{ connected: boolean }>("/api/google/disconnect", { method: "POST" });
export const listGoogleEvents = (daysBack: number) =>
  request<{ events: GoogleEvent[] }>(`/api/google/events?days_back=${daysBack}&days_ahead=1`);

export function listConferenceRecords(meetingCode: string, start?: string, end?: string) {
  const params = new URLSearchParams({ meeting_code: meetingCode });
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  return request<{ conference_records: ConferenceRecord[] }>(`/api/google/conference-records?${params}`);
}

export const importGoogleTranscript = (body: { transcript_name: string; title: string; participants: string[] }) =>
  request<MeetingDetail>("/api/google/import", { ...json(body), timeoutMs: 60_000 });

export type SystemInfo = {
  stt_provider: "mock" | "deepgram";
  stt_model: string | null;
  llm_provider: string;
  llm_model: string | null;
  google_mode: "mock" | "live";
  meeting_bot_provider: "mock" | "recall";
  demo_mode: boolean;
  bot_name: string;
  max_audio_mb: number;
};

export const getSystemInfo = () => request<SystemInfo>("/api/system");

export type AutoImportActivity = {
  at: string;
  transcript: string | null;
  status: "analyzed" | "imported" | "duplicate" | "skipped" | "failed";
  detail: string;
  meeting_id: string | null;
  title: string | null;
};

export type AutoImportStatus = {
  mode: "mock" | "live";
  connected: boolean;
  configured: boolean;
  poll_seconds: number;
  topic: string | null;
  subscription: string | null;
  events_subscription: string | null;
  events_subscription_expires: string | null;
  error: string | null;
  last_poll_at: string | null;
  last_error: string | null;
  recent: AutoImportActivity[];
};

export const getAutoImportStatus = () => request<AutoImportStatus>("/api/google/auto-import");
export const runAutoImport = () =>
  request<AutoImportStatus>("/api/google/auto-import/run", { method: "POST", timeoutMs: 120_000 });
export const simulateFinishedMeeting = () =>
  request<AutoImportStatus>("/api/google/auto-import/simulate", { method: "POST", timeoutMs: 120_000 });

// --- Live meetings: the Yuqta notetaker bot ----------------------------------------------

export type BotStatus =
  | "scheduled"
  | "joining"
  | "waiting"
  | "in_call"
  | "recording"
  | "processing"
  | "transcribed"
  | "analyzed"
  | "failed"
  | "cancelled";

export type MeetingBot = {
  id: string;
  provider: string;
  meeting_url: string;
  title: string;
  status: BotStatus;
  provider_status: string | null;
  detail: string;
  meeting_id: string | null;
  join_at: string | null;
  calendar_event_id: string | null;
  created_at: string;
  updated_at: string;
};

export type MeetingBotList = {
  provider: "mock" | "recall";
  bot_name: string;
  poll_seconds: number;
  last_poll_at: string | null;
  bots: MeetingBot[];
};

export const listBots = () => request<MeetingBotList>("/api/bots");
export const sendBot = (body: { meeting_url: string; title: string }) =>
  request<MeetingBot>("/api/bots", { ...json(body), timeoutMs: 30_000 });
export const deleteBot = (botId: string) =>
  request<void>(`/api/bots/${encodeURIComponent(botId)}`, { method: "DELETE", timeoutMs: 30_000 });
export const leaveBot = (botId: string) =>
  request<MeetingBot>(`/api/bots/${encodeURIComponent(botId)}/leave`, { method: "POST", timeoutMs: 30_000 });
// Checking can import and analyze a finished call (an LLM call), so allow time.
export const checkBots = () => request<MeetingBotList>("/api/bots/check", { method: "POST", timeoutMs: 180_000 });

export type CalendarAutoJoin = {
  enabled: boolean;
  google_mode: "mock" | "live";
  google_connected: boolean;
  hours_ahead: number;
  poll_seconds: number;
  last_run_at: string | null;
  last_error: string | null;
  recent: string[];
};

export const getCalendarAutoJoin = () => request<CalendarAutoJoin>("/api/bots/calendar");
export const syncCalendar = () => request<CalendarAutoJoin>("/api/bots/calendar/sync", { method: "POST", timeoutMs: 60_000 });

// --- Meeting history ---------------------------------------------------------------------

export type HistoryMeeting = {
  id: string;
  title: string;
  date: string;
  source: string;
  status: MeetingSummary["status"];
  headline: string | null;
  meeting_type: MeetingIntelligence["meeting_type"] | null;
  participants: string[];
  action_items: number;
  decisions: number;
  risks: number;
  open_questions: number;
};

export type HistoryItem = {
  kind: "action_items" | "decisions" | "risks" | "open_questions";
  index: number;
  text: string;
  owner: string | null;
  due: string | null;
  meeting_id: string;
  meeting_title: string;
  date: string;
  speaker: string;
  quote: string;
};

export type MeetingHistory = {
  totals: {
    meetings: number;
    analyzed: number;
    action_items: number;
    unassigned_action_items: number;
    decisions: number;
    risks: number;
    open_questions: number;
  };
  meetings: HistoryMeeting[];
  action_items: HistoryItem[];
  decisions: HistoryItem[];
  risks: HistoryItem[];
  open_questions: HistoryItem[];
  owners: { owner: string; action_items: number }[];
};

export const getHistory = () => request<MeetingHistory>("/api/history");
export const deleteMeetingItem = (meetingId: string, kind: HistoryItem["kind"], index: number, text: string) =>
  request<void>(
    `/api/meetings/${encodeURIComponent(meetingId)}/items/${kind}/${index}?${new URLSearchParams({ text })}`,
    { method: "DELETE" },
  );
export const deleteMeeting = (meetingId: string) =>
  request<void>(`/api/meetings/${encodeURIComponent(meetingId)}`, { method: "DELETE" });
