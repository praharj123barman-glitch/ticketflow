/** Minimal URL helpers — no router dependency. The app is a few top-level views,
 * so we just read the location once on load.
 *
 * A shared event link is `/e/{id}` (server-rendered OG meta in prod, see
 * app/routers/pages.py) which bounces to `/?e={id}`; we accept either form. */
export function eventIdFromUrl(): number | null {
  const q = new URLSearchParams(window.location.search).get("e");
  if (q && /^\d+$/.test(q)) return Number(q);
  const m = window.location.pathname.match(/^\/e\/(\d+)/);
  return m ? Number(m[1]) : null;
}

export function isDashboardUrl(): boolean {
  return window.location.pathname.startsWith("/dashboard")
    || new URLSearchParams(window.location.search).get("view") === "dashboard";
}

/** Stripe redirects here after Checkout. `/booking/success?hold=…&session_id=…`
 * (the webhook confirms server-side; the SPA polls for the resulting booking)
 * and `/booking/cancel?hold=…`. */
export function bookingReturnFromUrl(): { kind: "success" | "cancel"; holdId: number } | null {
  const m = window.location.pathname.match(/^\/booking\/(success|cancel)/);
  if (!m) return null;
  const hold = new URLSearchParams(window.location.search).get("hold");
  return { kind: m[1] as "success" | "cancel", holdId: hold ? Number(hold) : NaN };
}

/** Push a shallow URL without reloading (keeps share links honest as you navigate). */
export function setUrl(path: string) {
  window.history.replaceState(null, "", path);
}
