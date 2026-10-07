"use client";

import { useActionState } from "react";

import { createSampleMeetingAction, type ActionState } from "@/app/meetings/actions";

const initialState: ActionState = { error: null };

export function CreateSampleMeetingButton() {
  const [state, action, pending] = useActionState(createSampleMeetingAction, initialState);

  return (
    <form action={action} className="flex flex-col items-start gap-2">
      <button
        type="submit"
        disabled={pending}
        className="inline-flex h-10 items-center rounded-md bg-brand px-4 text-sm font-semibold text-white transition hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
      >
        {pending ? "Transcribing…" : "Create sample meeting"}
      </button>
      {state.error && (
        <p role="alert" className="text-sm text-rose-600 dark:text-rose-400">
          {state.error}
        </p>
      )}
    </form>
  );
}
