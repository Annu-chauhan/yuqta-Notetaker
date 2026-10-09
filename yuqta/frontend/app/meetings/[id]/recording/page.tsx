import type { Metadata } from "next";
import Link from "next/link";

import { SiteHeader } from "@/components/SiteHeader";
import { getRecordingUrl } from "@/lib/api";

export const metadata: Metadata = { title: "Recording · Yuqta" };

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Plays the meeting video. The provider's links expire after ~6 hours, so a fresh one is fetched on every visit.
 * The file is served as a generic download, so it is played in a <video> element rather than opened directly.
 */
export default async function RecordingPage({ params }: PageProps<"/meetings/[id]/recording">) {
  const { id } = await params;
  const result = UUID_PATTERN.test(id) ? await getRecordingUrl(id) : { error: "Meeting not found" };

  return (
    <div className="flex min-h-full flex-col">
      <SiteHeader />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-12 sm:px-6">
        <Link href={`/meetings/${id}`} className="text-sm text-muted hover:text-foreground">
          ← Back to the meeting
        </Link>
        <h1 className="mt-4 text-3xl font-bold tracking-tight">Recording</h1>
        {"url" in result ? (
          <>
            <video controls preload="metadata" src={result.url} className="mt-6 w-full rounded-lg border border-line bg-black" />
            <p className="mt-3 flex flex-wrap items-center gap-3 text-sm text-muted">
              <a href={result.url} download className="font-medium text-foreground underline underline-offset-2">
                Download the video
              </a>
              <span>This link works for about 6 hours; reopen this page for a new one.</span>
            </p>
          </>
        ) : (
          <p className="mt-6 rounded-lg border border-line bg-surface px-4 py-3 text-sm">{result.error}</p>
        )}
      </main>
    </div>
  );
}
