import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import { SESSION_COOKIE, isValidSession } from "@/lib/session";

/**
 * The real access check (proxy.ts only does an optimistic redirect). Every backend call goes
 * through lib/api.ts, which calls this first, so pages and Server Actions cannot skip it.
 */
export const verifySession = cache(async (): Promise<void> => {
  const value = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!isValidSession(value)) redirect("/login");
});
