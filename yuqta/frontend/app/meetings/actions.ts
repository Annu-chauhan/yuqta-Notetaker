"use server";

import { refresh } from "next/cache";
import { redirect, unstable_rethrow } from "next/navigation";

import {
  ApiError,
  analyzeMeeting,
  checkBots,
  createSampleMeeting,
  deleteBot,
  deleteMeeting,
  deleteMeetingItem,
  leaveBot,
  sendBot,
  syncCalendar,
  uploadMeetingAudio,
} from "@/lib/api";

export type ActionState = { error: string | null };

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

// Every lib/api call verifies the signed-in session first (lib/dal.ts), so actions inherit the check.
export async function createSampleMeetingAction(): Promise<ActionState> {
  let meetingId: string;
  try {
    meetingId = (await createSampleMeeting()).id;
  } catch (error) {
    unstable_rethrow(error);
    return { error: errorMessage(error, "Could not create the sample meeting.") };
  }
  redirect(`/meetings/${meetingId}`); // outside try: redirect() works by throwing
}

export async function analyzeMeetingAction(_: ActionState, formData: FormData): Promise<ActionState> {
  // Server Actions are reachable by direct POST, so validate the input here too.
  const meetingId = String(formData.get("meetingId") ?? "");
  if (!UUID_PATTERN.test(meetingId)) return { error: "Invalid meeting id." };
  try {
    await analyzeMeeting(meetingId);
  } catch (error) {
    unstable_rethrow(error);
    return { error: errorMessage(error, "Analysis failed.") };
  }
  refresh();
  return { error: null };
}

const MAX_AUDIO_BYTES = 200 * 1024 * 1024;

export async function uploadAudioAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const file = formData.get("file");
  const title = String(formData.get("title") ?? "").trim();
  if (!(file instanceof File) || file.size === 0) return { error: "Choose an audio or video file." };
  if (!title) return { error: "Give the meeting a name." };
  if (file.size > MAX_AUDIO_BYTES) return { error: "The file is larger than 200 MB." };

  const upload = new FormData();
  upload.set("file", file, file.name);
  upload.set("title", title);
  upload.set("participants", String(formData.get("participants") ?? ""));
  let meetingId: string;
  try {
    meetingId = (await uploadMeetingAudio(upload)).id;
  } catch (error) {
    unstable_rethrow(error);
    return { error: errorMessage(error, "Upload failed.") };
  }
  redirect(`/meetings/${meetingId}`);
}

// --- Live meetings: the Yuqta notetaker bot -------------------------------------------------

export async function sendBotAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const meetingUrl = String(formData.get("meeting_url") ?? "").trim();
  const title = String(formData.get("title") ?? "").trim().slice(0, 300);
  if (!meetingUrl) return { error: "Paste the meeting link." };
  if (meetingUrl.length > 500) return { error: "That link is too long." };
  try {
    await sendBot({ meeting_url: meetingUrl, title });
  } catch (error) {
    unstable_rethrow(error);
    return { error: errorMessage(error, "Could not send Yuqta to the meeting.") };
  }
  refresh();
  return { error: null };
}

export async function leaveBotAction(formData: FormData): Promise<void> {
  const botId = String(formData.get("botId") ?? "");
  if (!UUID_PATTERN.test(botId)) return;
  try {
    await leaveBot(botId);
  } catch (error) {
    unstable_rethrow(error); // the list shows the bot's real state on the next refresh
  }
  refresh();
}

export async function checkBotsAction(): Promise<void> {
  try {
    await checkBots();
  } catch (error) {
    unstable_rethrow(error);
  }
  refresh();
}

export async function syncCalendarAction(): Promise<void> {
  try {
    await syncCalendar();
  } catch (error) {
    unstable_rethrow(error); // the panel shows the joiner's last error on refresh
  }
  refresh();
}

export async function deleteMeetingAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const meetingId = String(formData.get("meetingId") ?? "");
  const redirectTo = String(formData.get("redirectTo") ?? "");
  if (!UUID_PATTERN.test(meetingId)) return { error: "Invalid meeting id." };
  try {
    await deleteMeeting(meetingId);
  } catch (error) {
    unstable_rethrow(error);
    if (!(error instanceof ApiError && error.status === 404)) {
      return { error: errorMessage(error, "Could not delete the meeting.") };
    } // already gone: treat as deleted
  }
  // Same-site paths only (blocks open redirects such as "//evil.example").
  if (redirectTo.startsWith("/") && !redirectTo.startsWith("//")) redirect(redirectTo);
  refresh();
  return { error: null };
}

const ITEM_KINDS = new Set(["action_items", "decisions", "risks", "open_questions"]);

export async function deleteItemAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const meetingId = String(formData.get("meetingId") ?? "");
  const kind = String(formData.get("kind") ?? "");
  const index = Number(formData.get("index"));
  const text = String(formData.get("text") ?? "");
  if (!UUID_PATTERN.test(meetingId) || !ITEM_KINDS.has(kind) || !Number.isInteger(index) || index < 0 || !text) {
    return { error: "Invalid item." };
  }
  try {
    await deleteMeetingItem(meetingId, kind as "action_items", index, text);
  } catch (error) {
    unstable_rethrow(error);
    return { error: errorMessage(error, "Could not remove the item.") };
  }
  refresh();
  return { error: null };
}

export async function deleteBotAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const botId = String(formData.get("botId") ?? "");
  if (!UUID_PATTERN.test(botId)) return { error: "Invalid entry." };
  try {
    await deleteBot(botId);
  } catch (error) {
    unstable_rethrow(error);
    if (!(error instanceof ApiError && error.status === 404)) {
      return { error: errorMessage(error, "Could not delete the entry.") };
    }
  }
  refresh();
  return { error: null };
}
