import { connection } from "next/server";

import { getHealth } from "@/lib/api";

type Tone = "ok" | "warn" | "down";

const toneClasses: Record<Tone, string> = {
  ok: "bg-brand",
  warn: "bg-amber-500",
  down: "bg-rose-500",
};

function StatusItem({ label, value, tone }: { label: string; value: string; tone: Tone }) {
  return (
    <li className="flex items-center justify-between gap-4 py-3">
      <span className="text-sm text-muted">{label}</span>
      <span className="flex items-center gap-2 font-mono text-xs uppercase tracking-wide">
        <span className={`h-2 w-2 rounded-full ${toneClasses[tone]}`} aria-hidden />
        {value}
      </span>
    </li>
  );
}

export async function SystemStatus() {
  await connection(); // always check live status at request time
  const health = await getHealth();

  return (
    <ul className="divide-y divide-line">
      <StatusItem label="Frontend" value="Running" tone="ok" />
      <StatusItem
        label="Backend API"
        value={health ? `Healthy · ${health.app_env}` : "Unreachable"}
        tone={health ? "ok" : "down"}
      />
      <StatusItem
        label="PostgreSQL"
        value={!health ? "Unknown" : health.database === "ok" ? "Connected" : "Unavailable"}
        tone={!health ? "warn" : health.database === "ok" ? "ok" : "down"}
      />
    </ul>
  );
}

export function SystemStatusFallback() {
  return <p className="py-3 text-sm text-muted">Checking services…</p>;
}
