// No "server-only" import: proxy.ts uses this too. node:crypto keeps it out of browser bundles anyway.
import { createHash, createHmac, timingSafeEqual } from "node:crypto";

// Login is on when APP_PASSWORD is set. Sessions are stateless: "<expiry>.<hmac>" in an HttpOnly cookie.
export const SESSION_COOKIE = "yuqta_session";
export const SESSION_TTL_SECONDS = 12 * 60 * 60;

export function authEnabled(): boolean {
  return Boolean(process.env.APP_PASSWORD);
}

function secret(): string {
  // AUTH_SECRET is preferred; deriving from the password keeps the POC to one required setting.
  return process.env.AUTH_SECRET || createHash("sha256").update(`yuqta-session:${process.env.APP_PASSWORD ?? ""}`).digest("hex");
}

function sign(payload: string): string {
  return createHmac("sha256", secret()).update(payload).digest("base64url");
}

function safeEqual(a: string, b: string): boolean {
  // Compare fixed-length digests so neither content nor length leaks through timing.
  const left = createHash("sha256").update(a).digest();
  const right = createHash("sha256").update(b).digest();
  return timingSafeEqual(left, right);
}

export function createSessionValue(now = Date.now()): string {
  const expires = String(Math.floor(now / 1000) + SESSION_TTL_SECONDS);
  return `${expires}.${sign(expires)}`;
}

export function isValidSession(value: string | undefined, now = Date.now()): boolean {
  if (!authEnabled()) return true;
  if (!value) return false;
  const [expires, signature] = value.split(".");
  if (!expires || !signature || !safeEqual(signature, sign(expires))) return false;
  return Number(expires) * 1000 > now;
}

export function passwordMatches(candidate: string): boolean {
  const expected = process.env.APP_PASSWORD;
  return Boolean(expected) && safeEqual(candidate, expected as string);
}

export function cookieSecure(): boolean {
  // Set AUTH_COOKIE_SECURE=true when Yuqta is served over HTTPS.
  return process.env.AUTH_COOKIE_SECURE === "true";
}
