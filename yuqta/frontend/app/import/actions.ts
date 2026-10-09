"use server";

import { redirect, unstable_rethrow } from "next/navigation";

import {
  ApiError,
  connectGoogle,
  disconnectGoogle,
  importGoogleTranscript,
  runAutoImport,
  simulateFinishedMeeting,
} from "@/lib/api";

// Every lib/api call verifies the signed-in session first (lib/dal.ts).

const TRANSCRIPT_NAME = /^conferenceRecords\/[\w-]+\/transcripts\/[\w-]+$/;

function message(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function withError(path: string, text: string): string {
  return `${path}${path.includes("?") ? "&" : "?"}import_error=${encodeURIComponent(text)}`;
}

export async function connectGoogleAction(): Promise<void> {
  let url: string;
  try {
    url = (await connectGoogle("/import")).authorization_url;
  } catch (error) {
    unstable_rethrow(error);
    redirect(withError("/import", message(error, "Could not start Google sign-in.")));
  }
  redirect(url); // Google's consent screen (or, in mock mode, straight to the backend callback)
}

export async function disconnectGoogleAction(formData: FormData): Promise<void> {
  const account = String(formData.get("account") ?? "").trim();
  if (account.length > 320) redirect(withError("/import", "Invalid account."));
  try {
    await disconnectGoogle(account || undefined);
  } catch (error) {
    unstable_rethrow(error);
  }
  redirect("/import");
}

export async function importTranscriptAction(formData: FormData): Promise<void> {
  const transcriptName = String(formData.get("transcript_name") ?? "");
  const title = String(formData.get("title") ?? "").trim() || "Google Meet meeting";
  const back = String(formData.get("back") ?? "/import");
  let participants: string[] = [];
  try {
    const parsed: unknown = JSON.parse(String(formData.get("participants") ?? "[]"));
    if (Array.isArray(parsed)) participants = parsed.filter((p): p is string => typeof p === "string").slice(0, 200);
  } catch {
    participants = [];
  }
  const backTo = back.startsWith("/import") ? back : "/import";
  if (!TRANSCRIPT_NAME.test(transcriptName)) redirect(withError(backTo, "Invalid transcript."));

  let meetingId: string;
  try {
    meetingId = (await importGoogleTranscript({ transcript_name: transcriptName, title, participants })).id;
  } catch (error) {
    unstable_rethrow(error);
    redirect(withError(backTo, message(error, "Import failed.")));
  }
  redirect(`/meetings/${meetingId}`);
}

export async function runAutoImportAction(): Promise<void> {
  try {
    await runAutoImport();
  } catch (error) {
    unstable_rethrow(error);
    redirect(withError("/import", message(error, "Could not check for finished meetings.")));
  }
  redirect("/import#auto-import");
}

export async function simulateMeetingAction(): Promise<void> {
  try {
    await simulateFinishedMeeting();
  } catch (error) {
    unstable_rethrow(error);
    redirect(withError("/import", message(error, "Simulation failed.")));
  }
  redirect("/import#auto-import");
}
