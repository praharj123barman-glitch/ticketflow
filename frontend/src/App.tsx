import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  api, getToken, setToken, openSeatStream,
  type Booking, type EventDetail, type Hold, type Seat,
} from "./api";
import { WaitingRoom } from "./WaitingRoom";
import { SeatMap } from "./SeatMap";
import { EventHero } from "./EventHero";
import { Checkout } from "./Checkout";
import { Confirmation } from "./Confirmation";
import { Landing } from "./Landing";
import { Dashboard } from "./Dashboard";
import { eventIdFromUrl, isDashboardUrl, setUrl } from "./routing";
import { sceneVariants, springs } from "./motion";

const inr = (cents: number) => `₹${(cents / 100).toLocaleString("en-IN")}`;
const MAX = 8;

type View = "landing" | "auth" | "dashboard" | "event";

export default function App() {
  const [eventId, setEventId] = useState<number | null>(() => eventIdFromUrl());
  const [view, setView] = useState<View>(() =>
    isDashboardUrl() ? "dashboard" : eventIdFromUrl() != null ? "event" : "landing",
  );
  const [busy, setBusy] = useState(false);

  // Enter an event, transparently creating a guest account if the visitor has no
  // token yet — so a stranger (incl. someone arriving on a shared /e/{id} link)
  // can book with zero signup friction. Fire the funnel view beacon on entry.
  const enterEvent = useCallback(async (id: number) => {
    setBusy(true);
    try {
      if (!getToken()) await api.guest();
      api.recordView(id);
      setEventId(id);
      setUrl(`/e/${id}`);
      setView("event");
    } finally {
      setBusy(false);
    }
  }, []);

  const trySample = useCallback(async () => {
    const evs = await api.events().catch(() => []);
    if (evs[0]) await enterEvent(evs[0].id);
  }, [enterEvent]);

  // Deep link: someone opened /e/{id} (or /?e={id}) directly — ensure a token
  // and count the view exactly once on first load.
  useEffect(() => {
    if (view === "event" && eventId != null) {
      (async () => { if (!getToken()) await api.guest(); api.recordView(eventId); })();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const goLanding = () => { setUrl("/"); setView("landing"); };

  if (view === "dashboard") return <Dashboard onExit={goLanding} />;
  if (view === "auth") return <Auth onAuthed={trySample} onBack={goLanding} />;
  if (view === "event" && eventId != null) return <EventFlow eventId={eventId} onExit={goLanding} />;
  return (
    <Landing
      onTrySample={trySample}
      onDemoLogin={() => setView("auth")}
      onOpenEvent={enterEvent}
      onDashboard={() => { setUrl("/dashboard"); setView("dashboard"); }}
      busy={busy}
    />
  );
}

/* Gate the booking flow behind the waiting room for a specific event. */
function EventFlow({ eventId, onExit }: { eventId: number; onExit: () => void }) {
  const [admitted, setAdmitted] = useState(false);
  if (!admitted) return <WaitingRoom eventId={eventId} onAdmitted={() => setAdmitted(true)} />;
  return <Booker eventId={eventId} onExit={onExit} />;
}

/* ---------------- Auth ---------------- */
function Auth({ onAuthed, onBack }: { onAuthed: () => void; onBack?: () => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("demo@ticketflow.dev");
  const [password, setPassword] = useState("password123");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      if (mode === "register") await api.register(email, password);
      await api.login(email, password);
      onAuthed();
    } catch (x: any) {
      setErr(typeof x?.detail === "string" ? x.detail : "Authentication failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bg-aurora min-h-screen flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}
        className="w-full max-w-md rounded-2xl border border-white/10 bg-white/5 backdrop-blur-xl p-8 shadow-2xl"
      >
        <div className="text-2xl font-bold tracking-tight">🎟️ TicketFlow</div>
        <p className="mt-1 text-sm text-white/50">Concurrent seat booking — pick a seat before someone else does.</p>

        <div className="mt-6 flex gap-1 rounded-lg bg-white/5 p-1 text-sm">
          {(["login", "register"] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)}
              className={`flex-1 rounded-md py-2 capitalize transition ${mode === m ? "bg-cyan-500/90 text-white" : "text-white/60 hover:text-white"}`}>
              {m}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="mt-5 space-y-3">
          <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" placeholder="email"
            className="w-full rounded-lg border border-white/10 bg-black/30 px-4 py-3 outline-none focus:border-cyan-400/60" />
          <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" placeholder="password (min 8 chars)"
            className="w-full rounded-lg border border-white/10 bg-black/30 px-4 py-3 outline-none focus:border-cyan-400/60" />
          {err && <div className="text-sm text-red-400">{err}</div>}
          <button disabled={busy}
            className="w-full rounded-lg bg-cyan-500 py-3 font-semibold text-white transition hover:bg-cyan-400 disabled:opacity-50">
            {busy ? "..." : mode === "login" ? "Log in" : "Create account & log in"}
          </button>
        </form>
        <p className="mt-4 text-center text-xs text-white/40">Demo: demo@ticketflow.dev / password123</p>
        {onBack && (
          <button onClick={onBack} className="mt-4 w-full text-center text-xs text-white/40 hover:text-white/70">← Back to home</button>
        )}
      </motion.div>
    </div>
  );
}

/* ---------------- Booker — a cinematic scene machine ---------------- */
type Scene = "hero" | "seatmap" | "checkout" | "confirmation";
const ORDER: Scene[] = ["hero", "seatmap", "checkout", "confirmation"];

function Booker({ eventId, onExit }: { eventId: number; onExit: () => void }) {
  const [event, setEvent] = useState<EventDetail | null>(null);
  const [seats, setSeats] = useState<Seat[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [flash, setFlash] = useState<Set<number>>(new Set());     // seats just taken by others (live)
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [hold, setHold] = useState<Hold | null>(null);
  const [confirmed, setConfirmed] = useState<Booking | null>(null);
  const [toast, setToast] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  const [busy, setBusy] = useState(false);

  // scene + navigation direction (drives the slide direction of transitions)
  const [scene, setScene] = useState<Scene>("hero");
  const [dir, setDir] = useState(1);
  const go = useCallback((next: Scene) => {
    setDir(ORDER.indexOf(next) >= ORDER.indexOf(scene) ? 1 : -1);
    setScene(next);
  }, [scene]);

  const showToast = (kind: "ok" | "err", msg: string) => {
    setToast({ kind, msg });
    setTimeout(() => setToast(null), 3500);
  };

  const refreshSeats = useCallback(async () => { setSeats(await api.seats(eventId)); }, [eventId]);

  const load = useCallback(async () => {
    const [detail, seatList, mine] = await Promise.all([
      api.event(eventId), api.seats(eventId), api.myBookings().catch(() => []),
    ]);
    setEvent(detail); setSeats(seatList); setBookings(mine);
  }, [eventId]);

  useEffect(() => { load(); }, [load]);

  // Live updates over WebSocket — no polling. Deltas patch seats as they change
  // anywhere in the system; seats taken by others flash via the seat-map's
  // "locking" animation.
  useEffect(() => {
    const ws = openSeatStream(eventId, {
      onSnapshot: (s) => setSeats(s),
      onDelta: (changes) => {
        setSeats((prev) => {
          const byId = new Map(prev.map((x) => [x.id, x]));
          for (const c of changes) {
            const cur = byId.get(c.id!);
            if (cur) byId.set(c.id!, { ...cur, status: c.status ?? cur.status, version: c.version ?? cur.version });
          }
          return [...byId.values()].sort((a, b) => a.id - b.id);
        });
        const taken = changes.filter((c) => c.status === "HELD" || c.status === "SOLD").map((c) => c.id!);
        if (taken.length) {
          setFlash((prev) => new Set([...prev, ...taken]));
          setTimeout(() => setFlash((prev) => {
            const n = new Set(prev); taken.forEach((id) => n.delete(id)); return n;
          }), 1500);
        }
      },
    });
    return () => ws.close();
  }, [eventId]);

  const toggle = (s: Seat) => {
    if (s.status !== "AVAILABLE") return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(s.id)) next.delete(s.id);
      else if (next.size < MAX) next.add(s.id);
      return next;
    });
  };

  const selectedSeats = useMemo(() => seats.filter((s) => selected.has(s.id)), [seats, selected]);
  const total = selectedSeats.reduce((sum, s) => sum + s.price_cents, 0);
  const counts = useMemo(() => ({
    available: seats.filter((s) => s.status === "AVAILABLE").length,
    sold: seats.filter((s) => s.status === "SOLD").length,
  }), [seats]);

  // seat map -> hold (reserve + start TTL) -> checkout scene
  async function startCheckout() {
    if (selected.size === 0) return;
    setBusy(true);
    try {
      const h = await api.hold(eventId, [...selected]);
      setHold(h);
      go("checkout");
    } catch (x: any) {
      if (x?.status === 409) showToast("err", "A seat was just taken by someone else — pick another.");
      else if (x?.status === 503) showToast("err", "High demand — please retry.");
      else showToast("err", "Couldn't hold those seats.");
      await refreshSeats();
      setSelected(new Set());
    } finally {
      setBusy(false);
    }
  }

  function onPaid(b: Booking) {
    setConfirmed(b);
    setSelected(new Set());
    setHold(null);
    go("confirmation");
    api.myBookings().then(setBookings).catch(() => {});
    refreshSeats();
  }

  function onHoldExpired() {
    setHold(null);
    setSelected(new Set());
    showToast("err", "Your hold expired — those seats were released.");
    refreshSeats();
    go("seatmap");
  }

  async function doCancel(id: number) {
    await api.cancel(id);
    showToast("ok", "Booking cancelled, seats released.");
    await refreshSeats();
    setBookings(await api.myBookings());
  }

  return (
    <div className="bg-aurora min-h-screen text-white">
      <header className="sticky top-0 z-30 border-b border-white/10 bg-black/30 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
          <div className="flex items-center gap-3">
            <button onClick={onExit} title="All events" className="rounded-lg border border-white/10 px-2.5 py-1.5 text-sm text-white/60 hover:bg-white/10">←</button>
            <button onClick={() => go("hero")} className="text-left">
              <div className="text-lg font-bold tracking-tight">🎟️ {event?.name ?? "TicketFlow"}</div>
              <div className="text-xs text-white/50">{event?.venue?.name ?? "Venue"} · {counts.available} available · {counts.sold} sold</div>
            </button>
          </div>
          <button onClick={() => { setToken(null); onExit(); }} className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-white/70 hover:bg-white/10">
            Log out
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8">
        <AnimatePresence mode="wait" custom={dir}>
          <motion.div
            key={scene} custom={dir} variants={sceneVariants}
            initial="enter" animate="center" exit="exit"
          >
            {scene === "hero" && event && (
              <EventHero event={event} onEnter={() => go("seatmap")} />
            )}

            {scene === "seatmap" && (
              <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
                <section>
                  <SeatMap seats={seats} selected={selected} flash={flash} onToggle={toggle} maxSelect={MAX} />
                </section>
                <aside className="space-y-4">
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-5 backdrop-blur-xl">
                    <div className="text-sm font-semibold">Your selection</div>
                    {selectedSeats.length === 0 ? (
                      <p className="mt-2 text-sm text-white/40">Tap available seats to select (up to {MAX}).</p>
                    ) : (
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {selectedSeats.map((s) => (
                          <span key={s.id} className="rounded-md bg-cyan-500/20 px-2 py-1 text-xs text-cyan-200">{s.seat_number}</span>
                        ))}
                      </div>
                    )}
                    <div className="mt-4 flex items-center justify-between text-sm">
                      <span className="text-white/50">Total</span>
                      <span className="font-semibold">{inr(total)}</span>
                    </div>
                    <button disabled={selected.size === 0 || busy} onClick={startCheckout}
                      className="mt-3 w-full rounded-lg bg-cyan-500 py-2.5 font-semibold transition hover:bg-cyan-400 disabled:opacity-40">
                      {busy ? "Holding…" : selected.size ? `Continue · ${inr(total)}` : "Select seats"}
                    </button>
                  </div>

                  <div className="rounded-2xl border border-white/10 bg-white/5 p-5 backdrop-blur-xl">
                    <div className="text-sm font-semibold">My bookings</div>
                    {bookings.length === 0 ? (
                      <p className="mt-2 text-sm text-white/40">No bookings yet.</p>
                    ) : (
                      <ul className="mt-3 space-y-2">
                        {bookings.map((b) => (
                          <li key={b.id} className="rounded-lg border border-white/10 bg-black/20 p-3 text-sm">
                            <div className="flex items-center justify-between">
                              <span className={b.status !== "CONFIRMED" ? "text-white/40 line-through" : ""}>
                                #{b.id} · {b.items.length} seat(s) · {inr(b.total_cents)}
                              </span>
                              {b.status === "CONFIRMED" && (
                                <button onClick={() => doCancel(b.id)} className="text-xs text-red-300 hover:text-red-200">cancel</button>
                              )}
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </aside>
              </div>
            )}

            {scene === "checkout" && hold && (
              <Checkout hold={hold} seats={seats} onPaid={onPaid} onExpire={onHoldExpired} onBack={() => go("seatmap")} />
            )}

            {scene === "confirmation" && confirmed && (
              <Confirmation booking={confirmed} event={event} seats={seats} onDone={() => go("hero")} />
            )}
          </motion.div>
        </AnimatePresence>
      </main>

      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 30 }}
            transition={springs.soft}
            className={`fixed bottom-6 left-1/2 z-40 -translate-x-1/2 rounded-xl px-5 py-3 text-sm font-medium shadow-2xl backdrop-blur-xl
              ${toast.kind === "ok" ? "bg-emerald-500/90" : "bg-red-500/90"}`}>
            {toast.msg}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
