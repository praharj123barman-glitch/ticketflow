// Thin API client for the TicketFlow backend.
// Dev: calls go to /api/* and Vite proxies them to the FastAPI server.
// Prod: set VITE_API_URL to the public API origin.
const BASE = import.meta.env.VITE_API_URL ?? "/api";

let token: string | null = localStorage.getItem("tf_token");

export function getToken() {
  return token;
}
export function setToken(t: string | null) {
  token = t;
  if (t) localStorage.setItem("tf_token", t);
  else localStorage.removeItem("tf_token");
}

// Waiting-room admission token (per browser session).
let waitToken: string | null = sessionStorage.getItem("tf_wait");
export function setWaitToken(t: string | null) {
  waitToken = t;
  if (t) sessionStorage.setItem("tf_wait", t);
  else sessionStorage.removeItem("tf_wait");
}

// Stable per-browser session id for funnel analytics (dedupes view beacons).
export function sessionToken(): string {
  let t = localStorage.getItem("tf_session");
  if (!t) { t = crypto.randomUUID(); localStorage.setItem("tf_session", t); }
  return t;
}

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(opts.headers as object) };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (waitToken) headers["X-Waitroom-Token"] = waitToken;
  const res = await fetch(`${BASE}${path}`, { ...opts, headers });
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail;
    throw { status: res.status, detail, body };
  }
  return body as T;
}

export type Seat = { id: number; section: string; seat_number: string; price_cents: number; status: string; version: number };
export type Venue = { id: number; name: string; address: string; city: string };
export type Event = { id: number; name: string; venue: Venue | null; starts_at: string; status?: string };
export type EventDetail = Event & { description: string; capacity: number; available: number; tiers: { id: number; name: string; price_cents: number }[] };
export type Ticket = { id: number; seat_id: number; code: string; status: string };
export type Booking = {
  id: number;
  event_id: number;
  hold_id?: number | null;
  status: string;
  total_cents: number;
  created_at: string;
  items: { seat_id: number; price_cents: number }[];
  tickets?: Ticket[];
};
export type Hold = {
  id: number;
  event_id: number;
  status: string;
  expires_at: string;
  total_cents: number;
  items: { seat_id: number; price_cents: number }[];
};
export type Checkout = { hold_id: number; session_id: string; checkout_url: string };
export type WaitStatus = {
  token: string;
  status: "admitted" | "waiting" | "expired";
  position?: number;
  ahead?: number;
  estimated_wait_seconds?: number;
};
export type Me = { id: number; email: string; full_name: string; role: string };
export type Funnel = {
  views: number; holds: number; paid: number;
  view_to_hold: number; hold_to_paid: number; view_to_paid: number;
};
export type EventStats = {
  event_id: number; name: string; capacity: number; sold: number; held: number;
  available: number; revenue_cents: number; funnel: Funnel;
  recent_bookings: { booking_id: number; user_email: string; seats: number; total_cents: number; status: string; created_at: string }[];
};

// Live seat updates over WebSocket. Returns the socket; caller closes on unmount.
export function openSeatStream(
  eventId: number,
  handlers: { onSnapshot: (seats: Seat[]) => void; onDelta: (seats: Partial<Seat>[]) => void },
): WebSocket {
  const wsBase = BASE.startsWith("http")
    ? BASE.replace(/^http/, "ws")
    : `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}${BASE}`;
  const ws = new WebSocket(`${wsBase}/ws/events/${eventId}`);
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "snapshot") handlers.onSnapshot(msg.seats);
    else if (msg.type === "delta") handlers.onDelta(msg.seats);
  };
  return ws;
}

export const api = {
  async register(email: string, password: string) {
    return req("/auth/register", { method: "POST", body: JSON.stringify({ email, password }) });
  },
  async login(email: string, password: string) {
    // OAuth2 password flow expects form-encoded body.
    const res = await fetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ username: email, password }),
    });
    if (!res.ok) throw { status: res.status, detail: (await res.json().catch(() => null))?.detail };
    const data = (await res.json()) as { access_token: string };
    setToken(data.access_token);
    return data;
  },
  // Ephemeral guest account — lets a stranger run the whole flow with no signup.
  async guest() {
    const data = await req<{ access_token: string }>("/auth/guest", { method: "POST" });
    setToken(data.access_token);
    return data;
  },
  me: () => req<Me>("/auth/me"),

  events: () => req<Event[]>("/events"),
  event: (eventId: number) => req<EventDetail>(`/events/${eventId}`),
  seats: (eventId: number) => req<Seat[]>(`/events/${eventId}/seats`),
  // Funnel beacon (fire-and-forget) — counts a unique visitor for an event.
  recordView: (eventId: number) =>
    req(`/events/${eventId}/view`, { method: "POST", body: JSON.stringify({ session_token: sessionToken() }) }).catch(() => {}),

  // Organizer dashboard
  myEvents: () => req<Event[]>("/organizer/events"),
  eventStats: (eventId: number) => req<EventStats>(`/organizer/events/${eventId}/stats`),

  // Waiting room. Use a stable client-generated token so re-joins (incl. React
  // StrictMode's double-invoke) are idempotent — the same queue entry, not two.
  joinWaitroom: (eventId: number) => {
    if (!waitToken) setWaitToken(crypto.randomUUID());
    return req<WaitStatus>(`/waitroom/${eventId}/join`, { method: "POST" });
  },
  waitStatus: (eventId: number) => req<WaitStatus>(`/waitroom/${eventId}/status`),

  // ---- select -> hold -> pay -> confirm lifecycle ----
  // 1. Reserve seats (starts the TTL countdown). 409 if a seat was just taken.
  hold: (eventId: number, seatIds: number[]) =>
    req<Hold>("/holds", { method: "POST", body: JSON.stringify({ event_id: eventId, seat_ids: seatIds }) }),
  // 2. Open a Checkout Session. Returns a Stripe URL in prod; a fake session id
  //    (cs_test_fake_*) offline so the caller knows to use the dev-confirm path.
  checkout: (holdId: number) => req<Checkout>(`/holds/${holdId}/checkout`, { method: "POST" }),
  // 3a. PROD: Stripe redirect handles payment; the webhook confirms the booking.
  // 3b. DEV: simulate the webhook so the confirmation beat can run without keys.
  devConfirm: (holdId: number) => req<Booking>(`/holds/${holdId}/dev-confirm`, { method: "POST" }),

  myBookings: () => req<Booking[]>("/bookings"),
  // Find the booking a hold converted into (used on the Stripe success return,
  // where the webhook creates the booking server-side a moment after redirect).
  async bookingByHold(holdId: number): Promise<Booking | null> {
    const all = await req<Booking[]>("/bookings").catch(() => [] as Booking[]);
    return all.find((b) => b.hold_id === holdId) ?? null;
  },
  cancel: (bookingId: number) => req<Booking>(`/bookings/${bookingId}/cancel`, { method: "POST" }),
  // QR is served as an auth-gated SVG, so we fetch it with the bearer token and
  // return the markup to inline (no <img src> — that wouldn't carry the header).
  async ticketQr(code: string): Promise<string> {
    const res = await fetch(`${BASE}/tickets/${code}/qr.svg`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    return res.ok ? res.text() : "";
  },
};
