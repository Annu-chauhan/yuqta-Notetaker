import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { connection } from "next/server";

import { authEnabled } from "@/lib/session";

import { LoginForm } from "./LoginForm";

export const metadata: Metadata = { title: "Sign in · Yuqta" };

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  // Read APP_PASSWORD per request, not at build time (a static page would bake in "login off").
  await connection();
  if (!authEnabled()) redirect("/");
  const { next } = await searchParams;
  return (
    <main className="flex min-h-full flex-1 items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm rounded-lg border border-line bg-surface p-6">
        <p className="flex items-center gap-2.5 font-bold tracking-tight">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-brand text-sm text-white">Y</span>
          YUQTA
        </p>
        <h1 className="mt-6 text-xl font-semibold">Sign in</h1>
        <p className="mt-1 text-sm text-muted">Enter the workspace password.</p>
        <LoginForm next={typeof next === "string" ? next : "/"} />
      </div>
    </main>
  );
}
