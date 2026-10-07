import Link from "next/link";

import { logoutAction } from "@/app/login/actions";
import { authEnabled } from "@/lib/session";

const navLink = "font-medium text-muted hover:text-foreground";

export function SiteHeader() {
  return (
    <header className="border-b border-line">
      <div className="mx-auto flex h-16 max-w-5xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" aria-label="Yuqta home" className="flex shrink-0 items-center gap-2.5 font-bold tracking-tight">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-brand text-sm text-white">Y</span>
          {/* Wordmark hidden on very narrow phones so the nav (incl. Sign out) always fits. */}
          <span className="hidden min-[400px]:inline">YUQTA</span>
        </Link>
        <nav className="flex items-center gap-3 text-sm sm:gap-5">
          <Link href="/meetings" className={navLink}>
            Meetings
          </Link>
          <Link href="/import" className={navLink}>
            Import
          </Link>
          <Link href="/dashboard" className={navLink}>
            Dashboard
          </Link>
          {authEnabled() ? (
            <form action={logoutAction}>
              <button type="submit" className={navLink}>
                Sign out
              </button>
            </form>
          ) : (
            <span className="hidden font-mono text-xs text-muted sm:inline">POC · V0.1</span>
          )}
        </nav>
      </div>
    </header>
  );
}
