import { useEffect, useMemo, useState, useCallback } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { api, getToken, setToken, type Booking, type Event, type Seat } from "./api";

const inr = (cents: number) => `₹${(cents / 100).toLocaleString("en-IN")}`;
const MAX = 8;

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  return authed ? <Booker onLogout={() => { setToken(null); setAuthed(false); }} /> : <Auth onAuthed={() => setAuthed(true)} />;
}

/* ---------------- Auth ---------------- */
function Auth({ onAuthed }: { onAuthed: () => void }) {
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
      </motion.div>
    </div>
  );
}

/* ---------------- Booker ---------------- */
function Booker({ onLogout }: { onLogout: () => void }) {
  const [event, setEvent] = useState<Event | null>(null);
  const [seats, setSeats] = useState<Seat[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [toast, setToast] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  const [booking, setBooking] = useState(false);

  const showToast = (kind: "ok" | "err", msg: string) => {
    setToast({ kind, msg });
    setTimeout(() => setToast(null), 3500);
  };

  const refresh = useCallback(async (eventId: number) => {
    setSeats(await api.seats(eventId));
  }, []);

  const load = useCallback(async () => {
    const evs = await api.events();
    if (evs.length === 0) return;
    setEvent(evs[0]);
    await refresh(evs[0].id);
    setBookings(await api.myBookings());
  }, [refresh]);

  useEffect(() => { load(); }, [load]);

  // Live polling so you can watch seats get taken by other users in real time.
  useEffect(() => {
    if (!event) return;
    const t = setInterval(() => refresh(event.id), 4000);
    return () => clearInterval(t);
  }, [event, refresh]);

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

  async function doBook() {
    if (!event || selected.size === 0) return;
    setBooking(true);
    try {
      const b = await api.book(event.id, [...selected]);
      showToast("ok", `Booked ${b.items.length} seat(s) for ${inr(b.total_cents)} ✓`);
      setSelected(new Set());
      await refresh(event.id);
      setBookings(await api.myBookings());
    } catch (x: any) {
      if (x?.status === 409) showToast("err", `Seat just got taken by someone else! Refreshing...`);
      else if (x?.status === 503) showToast("err", "High demand — please retry.");
      else showToast("err", "Booking failed.");
      await refresh(event.id);
      setSelected(new Set());
    } finally {
      setBooking(false);
    }
  }

  async function doCancel(id: number) {
    await api.cancel(id);
    showToast("ok", "Booking cancelled, seats released.");
    if (event) await refresh(event.id);
    setBookings(await api.myBookings());
  }

  const rows = useMemo(() => {
    const map = new Map<string, Seat[]>();
    for (const s of seats) {
      const row = s.seat_number.replace(/[0-9]/g, "");
      if (!map.has(row)) map.set(row, []);
      map.get(row)!.push(s);
    }
    for (const arr of map.values()) arr.sort((a, b) => +a.seat_number.replace(/\D/g, "") - +b.seat_number.replace(/\D/g, ""));
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [seats]);

  const counts = useMemo(() => ({
    available: seats.filter((s) => s.status === "AVAILABLE").length,
    booked: seats.filter((s) => s.status === "BOOKED").length,
  }), [seats]);

  return (
    <div className="bg-aurora min-h-screen text-white">
      {/* header */}
      <header className="sticky top-0 z-20 border-b border-white/10 bg-black/30 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
          <div>
            <div className="text-lg font-bold tracking-tight">🎟️ {event?.name ?? "TicketFlow"}</div>
            <div className="text-xs text-white/50">{event?.venue} · {counts.available} available · {counts.booked} booked</div>
          </div>
          <button onClick={onLogout} className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-white/70 hover:bg-white/10">
            Log out
          </button>
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-6 px-4 py-8 lg:grid-cols-[1fr_320px]">
        {/* seat map */}
        <section>
          <div className="mb-5 rounded-full bg-gradient-to-r from-cyan-500/20 to-indigo-500/20 py-2 text-center text-xs uppercase tracking-[0.3em] text-white/60">
            Stage
          </div>
          <div className="space-y-1.5 overflow-x-auto">
            {rows.map(([row, rowSeats]) => (
              <div key={row} className="flex items-center gap-1.5">
                <span className="w-5 shrink-0 text-xs text-white/40">{row}</span>
                <div className="flex flex-wrap gap-1.5">
                  {rowSeats.map((s) => <SeatBtn key={s.id} seat={s} selected={selected.has(s.id)} onClick={() => toggle(s)} />)}
                </div>
              </div>
            ))}
          </div>
          <Legend />
        </section>

        {/* sidebar */}
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
            <button disabled={selected.size === 0 || booking} onClick={doBook}
              className="mt-3 w-full rounded-lg bg-cyan-500 py-2.5 font-semibold transition hover:bg-cyan-400 disabled:opacity-40">
              {booking ? "Booking…" : `Book ${selected.size || ""} seat${selected.size === 1 ? "" : "s"}`}
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
                      <span className={b.status === "CANCELLED" ? "text-white/40 line-through" : ""}>
                        #{b.id} · {b.items.length} seat(s) · {inr(b.total_cents)}
                      </span>
                      {b.status !== "CANCELLED" && (
                        <button onClick={() => doCancel(b.id)} className="text-xs text-red-300 hover:text-red-200">cancel</button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
      </main>

      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 30 }}
            className={`fixed bottom-6 left-1/2 -translate-x-1/2 rounded-xl px-5 py-3 text-sm font-medium shadow-2xl backdrop-blur-xl
              ${toast.kind === "ok" ? "bg-emerald-500/90" : "bg-red-500/90"}`}>
            {toast.msg}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function SeatBtn({ seat, selected, onClick }: { seat: Seat; selected: boolean; onClick: () => void }) {
  const base = "h-7 w-7 rounded-md text-[10px] font-medium grid place-items-center transition";
  let cls = "bg-slate-600/50 hover:bg-slate-500 text-white/70 cursor-pointer"; // available
  if (selected) cls = "bg-cyan-400 text-black scale-110 cursor-pointer";
  else if (seat.status === "BOOKED") cls = "bg-rose-900/60 text-white/30 cursor-not-allowed";
  else if (seat.status === "HELD") cls = "bg-amber-500/50 text-white/60 cursor-not-allowed";
  return (
    <motion.button whileTap={{ scale: 0.85 }} onClick={onClick} className={`${base} ${cls}`}
      title={`${seat.seat_number} · ${seat.status} · ${inr(seat.price_cents)}`}>
      {seat.seat_number.replace(/\D/g, "")}
    </motion.button>
  );
}

function Legend() {
  const items = [
    ["bg-slate-600/50", "Available"],
    ["bg-cyan-400", "Selected"],
    ["bg-amber-500/50", "Held"],
    ["bg-rose-900/60", "Booked"],
  ] as const;
  return (
    <div className="mt-6 flex flex-wrap gap-4 text-xs text-white/50">
      {items.map(([c, label]) => (
        <div key={label} className="flex items-center gap-2"><span className={`h-3 w-3 rounded ${c}`} />{label}</div>
      ))}
    </div>
  );
}
