import type { Metadata } from "next";
import Link from "next/link";
import { unstable_rethrow } from "next/navigation";
import { connection } from "next/server";

import { DashboardView } from "@/components/dashboard/DashboardView";
import { SiteHeader } from "@/components/SiteHeader";
import { ApiError, getLatestDashboard, getMeetingDashboard, type DashboardSpec } from "@/lib/api";

export const metadata: Metadata = { title: "Dashboard · Yuqta" };

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function DashboardPage({ searchParams }: PageProps<"/dashboard">) {
  await connection();
  const { meeting } = await searchParams;
  const meetingId = typeof meeting === "string" && UUID_PATTERN.test(meeting) ? meeting : null;

  let spec: DashboardSpec | null = null;
  let loadError: string | null = null;
  try {
    spec = meetingId ? await getMeetingDashboard(meetingId) : await getLatestDashboard();
  } catch (error) {
    unstable_rethrow(error);
    loadError = error instanceof ApiError ? error.message : "Could not load the dashboard.";
  }

  return (
    <div className="flex min-h-full flex-col">
      <SiteHeader />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-12 sm:px-6">
        {spec ? (
          <DashboardView spec={spec} />
        ) : (
          <>
            <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
            {loadError ? (
              <p role="alert" className="mt-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
                {loadError}
              </p>
            ) : (
              <p className="mt-6 rounded-lg border border-dashed border-line px-4 py-10 text-center text-sm text-muted">
                No dashboard yet. Open a{" "}
                <Link href="/meetings" className="font-medium text-foreground underline underline-offset-2">
                  meeting
                </Link>{" "}
                and run the analysis to build one.
              </p>
            )}
          </>
        )}
      </main>
    </div>
  );
}
