"use client";

import { useActionState } from "react";

import { deleteBotAction, deleteItemAction, deleteMeetingAction, type ActionState } from "@/app/meetings/actions";

const initialState: ActionState = { error: null };

type TrashButtonProps = {
  action: (state: ActionState, formData: FormData) => Promise<ActionState>;
  fields: Record<string, string | number>;
  confirmText: string;
  label: string;
  showText?: boolean;
};

/** Trash button that asks for confirmation first, because deleting cannot be undone. */
function TrashButton({ action: serverAction, fields, confirmText, label, showText = false }: TrashButtonProps) {
  const [state, action, pending] = useActionState(serverAction, initialState);
  return (
    <form
      action={action}
      onSubmit={(event) => {
        if (!window.confirm(confirmText)) event.preventDefault();
      }}
      className="flex shrink-0 items-center gap-2"
    >
      {Object.entries(fields).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      <button
        type="submit"
        disabled={pending}
        aria-label={label}
        title={label}
        className={`inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-line bg-surface text-muted hover:border-rose-300 hover:bg-rose-50 hover:text-rose-700 disabled:cursor-wait disabled:opacity-50 dark:hover:border-rose-800 dark:hover:bg-rose-950 dark:hover:text-rose-300 ${showText ? "px-3 text-xs font-semibold" : "w-8"}`}
      >
        <svg aria-hidden viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6" />
        </svg>
        {showText && "Delete"}
      </button>
      {state.error && (
        <span role="alert" className="text-xs text-rose-700 dark:text-rose-400">
          {state.error}
        </span>
      )}
    </form>
  );
}

/** Deletes a whole meeting. With redirectTo, the browser goes there afterwards (e.g. from the meeting's own page). */
export function DeleteMeetingButton({ meetingId, title, redirectTo, showText }: { meetingId: string; title: string; redirectTo?: string; showText?: boolean }) {
  return (
    <TrashButton
      action={deleteMeetingAction}
      fields={redirectTo ? { meetingId, redirectTo } : { meetingId }}
      confirmText={`Delete “${title}”?\n\nIts transcript, analysis and dashboard are removed. This cannot be undone.`}
      label={`Delete meeting ${title}`}
      showText={showText}
    />
  );
}

const itemNames = { action_items: "action item", decisions: "decision", risks: "risk", open_questions: "open question" } as const;

/** Removes one task, decision, risk or open question from its meeting. */
export function DeleteItemButton({ meetingId, kind, index, text }: { meetingId: string; kind: keyof typeof itemNames; index: number; text: string }) {
  return (
    <TrashButton
      action={deleteItemAction}
      fields={{ meetingId, kind, index, text }}
      confirmText={`Remove this ${itemNames[kind]}?\n\n“${text}”\n\nIt is removed from the meeting's analysis and dashboard. Re-running the analysis can bring it back.`}
      label={`Remove ${itemNames[kind]}: ${text}`}
    />
  );
}

/** Removes a finished or failed bot entry from the live-meetings list, with the meeting it produced. */
export function DeleteBotButton({ botId, title, hasMeeting }: { botId: string; title: string; hasMeeting: boolean }) {
  return (
    <TrashButton
      action={deleteBotAction}
      fields={{ botId }}
      confirmText={
        hasMeeting
          ? `Delete “${title}”?\n\nThe entry and its meeting (transcript, analysis and dashboard) are removed. This cannot be undone.`
          : `Remove “${title}” from the list?`
      }
      label={`Delete ${title}`}
    />
  );
}
