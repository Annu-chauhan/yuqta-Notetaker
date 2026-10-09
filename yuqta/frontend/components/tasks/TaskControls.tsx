"use client";

import { useActionState, useRef } from "react";

import { sendReminderAction, updateTaskAction, type ActionState } from "@/app/meetings/actions";
import type { TaskStatus } from "@/lib/api";

const initialState: ActionState = { error: null };
const field = "h-8 rounded-md border border-line bg-surface px-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:opacity-60";

function useTaskField(id: number, name: "status" | "owner" | "due_date") {
  const [state, action, pending] = useActionState(updateTaskAction, initialState);
  const form = useRef<HTMLFormElement>(null);
  const hidden = (
    <>
      <input type="hidden" name="id" value={id} />
      <input type="hidden" name="field" value={name} />
    </>
  );
  return { state, action, pending, form, hidden, submit: () => form.current?.requestSubmit() };
}

function Error({ state }: { state: ActionState }) {
  return state.error ? (
    <span role="alert" className="block text-xs text-rose-700 dark:text-rose-400">
      {state.error}
    </span>
  ) : null;
}

const statusLabels: Record<TaskStatus, string> = { open: "Open", in_progress: "In progress", done: "Done" };

/** Saves as soon as a different status is picked. */
export function StatusSelect({ id, status, task }: { id: number; status: TaskStatus; task: string }) {
  const { state, action, pending, form, hidden, submit } = useTaskField(id, "status");
  return (
    <form ref={form} action={action}>
      {hidden}
      <select
        name="value"
        defaultValue={status}
        disabled={pending}
        onChange={submit}
        aria-label={`Status of: ${task}`}
        className={`${field} ${status === "done" ? "text-emerald-700 dark:text-emerald-400" : status === "in_progress" ? "text-sky-700 dark:text-sky-400" : ""}`}
      >
        {Object.entries(statusLabels).map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      <Error state={state} />
    </form>
  );
}

/** Saves when the field is left or Enter is pressed, if the name changed. Empty = unassigned.
 *  Read-only (not disabled) while saving: a disabled field is left out of the form, so a save triggered while
 *  it is disabled would send no name at all. */
export function OwnerInput({ id, owner, task, owners }: { id: number; owner: string | null; task: string; owners: string[] }) {
  const { state, action, pending, form, hidden } = useTaskField(id, "owner");
  return (
    <form ref={form} action={action}>
      {hidden}
      <input
        name="value"
        defaultValue={owner ?? ""}
        placeholder="Unassigned"
        maxLength={200}
        readOnly={pending}
        aria-busy={pending}
        list="task-owners"
        aria-label={`Owner of: ${task}`}
        onBlur={(event) => {
          // Enter already submitted the form; don't save the same change twice.
          if (!pending && event.currentTarget.value.trim() !== (owner ?? "")) form.current?.requestSubmit();
        }}
        className={`${field} w-36 ${owner ? "" : "placeholder:text-amber-700 dark:placeholder:text-amber-400"}`}
      />
      {owners.length > 0 && (
        <datalist id="task-owners">
          {owners.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
      )}
      <Error state={state} />
    </form>
  );
}

/** Saves as soon as a date is picked or cleared. */
export function DueDateInput({ id, dueDate, task }: { id: number; dueDate: string | null; task: string }) {
  const { state, action, pending, form, hidden, submit } = useTaskField(id, "due_date");
  return (
    <form ref={form} action={action}>
      {hidden}
      <input
        type="date"
        name="value"
        defaultValue={dueDate ?? ""}
        readOnly={pending}
        aria-busy={pending}
        onChange={submit}
        aria-label={`Due date of: ${task}`}
        className={`${field} w-36`}
      />
      <Error state={state} />
    </form>
  );
}

export function SendReminderButton() {
  const [state, action, pending] = useActionState(sendReminderAction, initialState);
  return (
    <form action={action} className="flex flex-wrap items-center gap-2">
      <button
        type="submit"
        disabled={pending}
        className="inline-flex h-8 items-center rounded-md border border-line bg-surface px-3 text-xs font-semibold hover:bg-background disabled:cursor-wait disabled:opacity-60"
      >
        {pending ? "Sending…" : "Send test reminder now"}
      </button>
      {state.error && (
        <span role="alert" className="text-xs text-rose-700 dark:text-rose-400">
          {state.error}
        </span>
      )}
      {state.message && <span className="text-xs text-emerald-700 dark:text-emerald-400">{state.message}</span>}
    </form>
  );
}
