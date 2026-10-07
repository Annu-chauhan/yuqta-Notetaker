"use client"; // Error boundaries must be Client Components

import Link from "next/link";
import { useEffect } from "react";

// Last-resort fallback for unexpected errors anywhere in the app.
export default function Error({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col items-start px-4 py-24 sm:px-6">
      <p className="font-mono text-xs uppercase tracking-widest text-brand">Yuqta</p>
      <h1 className="mt-2 text-2xl font-bold tracking-tight">Something went wrong</h1>
      <p className="mt-2 text-sm text-muted">
        The page could not be loaded. If the backend is restarting, try again in a few seconds.
        {error.digest && <span className="block font-mono text-xs">Reference: {error.digest}</span>}
      </p>
      <div className="mt-6 flex gap-2">
        <button
          type="button"
          onClick={() => retry()}
          className="inline-flex h-10 items-center rounded-md bg-brand px-4 text-sm font-semibold text-white hover:opacity-90"
        >
          Try again
        </button>
        <Link href="/" className="inline-flex h-10 items-center rounded-md border border-line px-4 text-sm font-medium hover:bg-surface">
          Home
        </Link>
      </div>
    </main>
  );
}
