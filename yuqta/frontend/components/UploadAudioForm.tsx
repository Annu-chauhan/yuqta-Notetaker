"use client";

import { useActionState } from "react";

import { uploadAudioAction, type ActionState } from "@/app/meetings/actions";

const initialState: ActionState = { error: null };
const inputClass =
  "h-10 w-full rounded-md border border-line bg-surface px-3 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20";

export function UploadAudioForm({ provider }: { provider: string }) {
  const [state, action, pending] = useActionState(uploadAudioAction, initialState);
  return (
    <form action={action} className="grid gap-3 rounded-lg border border-line bg-surface p-4 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <h2 className="font-semibold">Upload a recording</h2>
        <p className="text-sm text-muted">
          Audio or video up to 200 MB, transcribed with speaker labels by the <strong>{provider}</strong> speech-to-text
          provider.
        </p>
      </div>
      <div>
        <label htmlFor="title" className="mb-1 block text-xs font-medium">Meeting name</label>
        <input id="title" name="title" required maxLength={300} placeholder="e.g. Weekly revenue review" className={inputClass} />
      </div>
      <div>
        <label htmlFor="participants" className="mb-1 block text-xs font-medium">Participants (optional)</label>
        <input id="participants" name="participants" maxLength={2000} placeholder="Names, separated by commas" className={inputClass} />
      </div>
      <div className="sm:col-span-2">
        <label htmlFor="file" className="mb-1 block text-xs font-medium">Recording</label>
        <input id="file" name="file" type="file" required accept="audio/*,video/*" className="block w-full text-sm text-muted file:mr-3 file:h-9 file:rounded-md file:border-0 file:bg-background file:px-3 file:text-sm file:font-medium file:text-foreground" />
      </div>
      <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
        <button
          type="submit"
          disabled={pending}
          className="inline-flex h-10 items-center rounded-md bg-brand px-4 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
        >
          {pending ? "Uploading and transcribing…" : "Upload and transcribe"}
        </button>
        {state.error && (
          <p role="alert" className="text-sm text-rose-600 dark:text-rose-400">
            {state.error}
          </p>
        )}
      </div>
    </form>
  );
}
