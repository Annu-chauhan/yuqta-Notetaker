"use client";

import { useActionState } from "react";

import { analyzeMeetingAction, type ActionState } from "@/app/meetings/actions";

const initialState: ActionState = { error: null };

export function AnalyzeMeetingButton({ meetingId, reanalyze = false }: { meetingId: string; reanalyze?: boolean }) {
  const [state, action, pending] = useActionState(analyzeMeetingAction, initialState);

  return (
    <form action={action} className="flex flex-col items-start gap-2">
      <input type="hidden" name="meetingId" value={meetingId} />
      <button
        type="submit"
        disabled={pending}
        className={
          reanalyze
            ? "inline-flex h-9 items-center rounded-md border border-line bg-surface px-3 text-sm font-medium hover:bg-background disabled:cursor-wait disabled:opacity-60"
            : "inline-flex h-10 items-center rounded-md bg-brand px-4 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
        }
      >
        {pending ? "Analyzing…" : reanalyze ? "Re-run analysis" : "Analyze meeting"}
      </button>
      {state.error && (
        <p role="alert" className="text-sm text-rose-600 dark:text-rose-400">
          {state.error}
        </p>
      )}
    </form>
  );
}
