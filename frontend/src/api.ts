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

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(opts.headers as object) };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${BASE}${path}`, { ...opts, headers });
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail;
    throw { status: res.status, detail, body };
  }
  return body as T;
}

export type Seat = { id: number; seat_number: string; price_cents: number; status: string; version: number };
export type Event = { id: number; name: string; venue: string; starts_at: string };
export type Booking = {
  id: number;
  event_id: number;
  status: string;
  total_cents: number;
  created_at: string;
  items: { seat_id: number; price_cents: number }[];
};

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
  events: () => req<Event[]>("/events"),
  seats: (eventId: number) => req<Seat[]>(`/events/${eventId}/seats`),
  book: (eventId: number, seatIds: number[]) =>
    req<Booking>("/bookings", { method: "POST", body: JSON.stringify({ event_id: eventId, seat_ids: seatIds }) }),
  myBookings: () => req<Booking[]>("/bookings"),
  cancel: (bookingId: number) => req<Booking>(`/bookings/${bookingId}/cancel`, { method: "POST" }),
};
