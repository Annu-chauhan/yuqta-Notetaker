"use client";

import { useActionState } from "react";

import { sendBotAction, type ActionState } from "@/app/meetings/actions";

const initialState: ActionState = { error: null };
const inputClass =
  "h-10 w-full rounded-md border border-line bg-surface px-3 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20";

export function InviteBotForm() {
  const [state, action, pending] = useActionState(sendBotAction, initialState);
  return (
    <form action={action} className="grid gap-3 sm:grid-cols-[2fr_1fr] sm:items-end">
      <div>
        <label htmlFor="meeting_url" className="mb-1 block text-xs font-medium">Meeting link</label>
        <input
          id="meeting_url"
          name="meeting_url"
          required
          maxLength={500}
          inputMode="url"
          autoComplete="off"
          placeholder="https://meet.google.com/abc-defg-hij"
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor="bot_title" className="mb-1 block text-xs font-medium">Meeting name (optional)</label>
        <input id="bot_title" name="title" maxLength={300} placeholder="e.g. Weekly revenue review" className={inputClass} />
      </div>
      <div>
        <label htmlFor="admin_email" className="mb-1 block text-xs font-medium">
          Admin email <span className="font-normal text-muted">(optional: gets the recording and summary)</span>
        </label>
        <input id="admin_email" name="admin_email" type="email" maxLength={320} autoComplete="email" placeholder="host@company.com" className={inputClass} />
      </div>
      <button
        type="submit"
        disabled={pending}
        className="inline-flex h-10 items-center justify-center whitespace-nowrap rounded-md bg-brand px-4 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
      >
        {pending ? "Sending…" : "Send Yuqta to the meeting"}
      </button>
      {state.error && (
        <p role="alert" className="text-sm text-rose-600 sm:col-span-2 dark:text-rose-400">
          {state.error}
        </p>
      )}
    </form>
  );
}
