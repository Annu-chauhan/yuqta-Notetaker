import Link from "next/link";
import { Suspense } from "react";

import { FlowSteps } from "@/components/FlowSteps";
import { SiteHeader } from "@/components/SiteHeader";
import { SystemStatus, SystemStatusFallback } from "@/components/SystemStatus";

export default function Home() {
  return (
    <div className="flex min-h-full flex-col">
      <SiteHeader />

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-16 sm:px-6 sm:py-24">
        <p className="font-mono text-xs uppercase tracking-widest text-brand">Enterprise Business Intelligence</p>
        <h1 className="mt-4 text-5xl font-extrabold tracking-tight sm:text-7xl">YUQTA</h1>
        <p className="mt-5 text-xl text-muted sm:text-2xl">Meeting → Intelligence → Action</p>
        <Link
          href="/meetings"
          className="mt-8 inline-flex h-10 items-center rounded-md bg-brand px-4 text-sm font-semibold text-white hover:opacity-90"
        >
          Go to meetings →
        </Link>

        <section className="mt-16" aria-labelledby="flow-heading">
          <h2 id="flow-heading" className="mb-4 text-sm font-semibold">
            Proof-of-concept flow
          </h2>
          <FlowSteps />
        </section>

        <section
          className="mt-12 max-w-md rounded-lg border border-line bg-surface px-5 py-2"
          aria-labelledby="status-heading"
        >
          <h2 id="status-heading" className="pt-3 text-sm font-semibold">
            System status
          </h2>
          <Suspense fallback={<SystemStatusFallback />}>
            <SystemStatus />
          </Suspense>
        </section>
      </main>
    </div>
  );
}
