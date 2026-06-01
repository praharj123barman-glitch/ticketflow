import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api, getToken, type Event, type EventStats, type Me } from "./api";
import { riseIn, springs, stagger } from "./motion";

const inr = (cents: number) => `₹${(cents / 100).toLocaleString("en-IN")}`;

/** Organizer dashboard — per-event sales + the viewed → held → paid conversion
 * funnel (real numbers, not vanity metrics). Gated to ORGANIZER/ADMIN. */
export function Dashboard({ onExit }: { onExit: () => void }) {
  const [me, setMe] = useState<Me | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (!getToken()) { setChecked(true); return; }
    api.me().then(setMe).catch(() => setMe(null)).finally(() => setChecked(true));
  }, []);

  if (!checked) return <Shell onExit={onExit}><p className="text-white/50">Loading…</p></Shell>;
  if (!me || (me.role !== "ORGANIZER" && me.role !== "ADMIN")) {
    return <Shell onExit={onExit}><OrganizerLogin onDone={(m) => setMe(m)} /></Shell>;
  }
  return <Shell onExit={onExit}><Funnels /></Shell>;
}

function Shell({ children, onExit }: { children: React.ReactNode; onExit: () => void }) {
  return (
    <div className="bg-aurora min-h-screen text-white">
      <header className="sticky top-0 z-20 border-b border-white/10 bg-black/30 backdrop-blur-xl">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4">
          <div className="font-bold tracking-tight">🎟️ TicketFlow · Organizer</div>
          <button onClick={onExit} className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-white/70 hover:bg-white/10">← Back to site</button>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
    </div>
  );
}

function OrganizerLogin({ onDone }: { onDone: (m: Me) => void }) {
  const [email, setEmail] = useState("organizer@ticketflow.dev");
  const [password, setPassword] = useState("password123");
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setErr(""); setBusy(true);
    try {
      await api.login(email, password);
      const m = await api.me();
      if (m.role !== "ORGANIZER" && m.role !== "ADMIN") { setErr("That account isn't an organizer."); return; }
      onDone(m);
    } catch { setErr("Login failed."); } finally { setBusy(false); }
  }

  return (
    <div className="mx-auto max-w-md rounded-2xl border border-white/10 bg-white/5 p-8 backdrop-blur-xl">
      <div className="text-xl font-bold">Organizer sign-in</div>
      <p className="mt-1 text-sm text-white/50">View live sales and the conversion funnel for your events.</p>
      <form onSubmit={submit} className="mt-5 space-y-3">
        <input value={email} onChange={(e) => setEmail(e.target.value)} type="email"
          className="w-full rounded-lg border border-white/10 bg-black/30 px-4 py-3 outline-none focus:border-cyan-400/60" />
        <input value={password} onChange={(e) => setPassword(e.target.value)} type="password"
          className="w-full rounded-lg border border-white/10 bg-black/30 px-4 py-3 outline-none focus:border-cyan-400/60" />
        {err && <div className="text-sm text-red-400">{err}</div>}
        <button disabled={busy} className="w-full rounded-lg bg-cyan-500 py-3 font-semibold hover:bg-cyan-400 disabled:opacity-50">
          {busy ? "…" : "Sign in"}
        </button>
      </form>
      <p className="mt-4 text-center text-xs text-white/40">Demo organizer: organizer@ticketflow.dev / password123</p>
    </div>
  );
}

function Funnels() {
  const [events, setEvents] = useState<Event[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [stats, setStats] = useState<EventStats | null>(null);

  useEffect(() => {
    api.myEvents().then((evs) => { setEvents(evs); if (evs[0]) setSel(evs[0].id); }).catch(() => {});
  }, []);
  useEffect(() => {
    if (sel == null) return;
    setStats(null);
    api.eventStats(sel).then(setStats).catch(() => {});
  }, [sel]);

  return (
    <div>
      <div className="mb-6 flex flex-wrap gap-2">
        {events.map((ev) => (
          <button key={ev.id} onClick={() => setSel(ev.id)}
            className={`rounded-full px-4 py-2 text-sm transition ${sel === ev.id ? "bg-cyan-500 text-white" : "border border-white/10 text-white/70 hover:bg-white/10"}`}>
            {ev.name}
          </button>
        ))}
        {events.length === 0 && <p className="text-white/40">No events yet.</p>}
      </div>

      {stats && (
        <motion.div key={stats.event_id} variants={stagger(0.06)} initial="hidden" animate="show" className="space-y-6">
          {/* sales tiles */}
          <motion.div variants={riseIn} className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Tile label="Revenue" value={inr(stats.revenue_cents)} accent />
            <Tile label="Sold" value={`${stats.sold} / ${stats.capacity}`} />
            <Tile label="Held now" value={String(stats.held)} />
            <Tile label="Available" value={String(stats.available)} />
          </motion.div>

          {/* conversion funnel */}
          <motion.div variants={riseIn} className="rounded-2xl border border-white/10 bg-white/5 p-6 backdrop-blur-xl">
            <div className="flex items-center justify-between">
              <div className="text-lg font-bold">Conversion funnel</div>
              <div className="text-sm text-white/50">Overall <span className="font-semibold text-cyan-300">{stats.funnel.view_to_paid}%</span> viewed → paid</div>
            </div>
            <div className="mt-5 space-y-3">
              <FunnelBar label="Viewed" value={stats.funnel.views} max={stats.funnel.views} color="bg-indigo-400/70" note="unique visitors" />
              <FunnelBar label="Held a seat" value={stats.funnel.holds} max={stats.funnel.views} color="bg-cyan-400/70" note={`${stats.funnel.view_to_hold}% of viewers`} />
              <FunnelBar label="Paid" value={stats.funnel.paid} max={stats.funnel.views} color="bg-emerald-400/80" note={`${stats.funnel.hold_to_paid}% of holds`} />
            </div>
          </motion.div>

          {/* recent bookings */}
          <motion.div variants={riseIn} className="rounded-2xl border border-white/10 bg-white/5 p-6 backdrop-blur-xl">
            <div className="text-lg font-bold">Recent bookings</div>
            {stats.recent_bookings.length === 0 ? (
              <p className="mt-2 text-sm text-white/40">No bookings yet.</p>
            ) : (
              <table className="mt-3 w-full text-sm">
                <thead className="text-left text-white/40">
                  <tr><th className="py-2 font-medium">#</th><th className="font-medium">Buyer</th><th className="font-medium">Seats</th><th className="font-medium">Total</th><th className="font-medium">Status</th></tr>
                </thead>
                <tbody>
                  {stats.recent_bookings.map((b) => (
                    <tr key={b.booking_id} className="border-t border-white/5">
                      <td className="py-2 text-white/50">{b.booking_id}</td>
                      <td className="max-w-[14rem] truncate">{b.user_email}</td>
                      <td>{b.seats}</td>
                      <td>{inr(b.total_cents)}</td>
                      <td><span className={b.status === "CONFIRMED" ? "text-emerald-300" : "text-white/40"}>{b.status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </motion.div>
        </motion.div>
      )}
    </div>
  );
}

function Tile({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className={`rounded-2xl border p-4 ${accent ? "border-cyan-400/30 bg-cyan-400/10" : "border-white/10 bg-white/5"}`}>
      <div className="text-[11px] uppercase tracking-widest text-white/40">{label}</div>
      <div className="mt-1 text-2xl font-bold">{value}</div>
    </div>
  );
}

function FunnelBar({ label, value, max, color, note }: { label: string; value: number; max: number; color: string; note: string }) {
  const pct = max > 0 ? Math.max(4, (value / max) * 100) : 4;
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-white/50">{value.toLocaleString()} · <span className="text-white/35">{note}</span></span>
      </div>
      <div className="h-7 overflow-hidden rounded-lg bg-black/30">
        <motion.div className={`h-full ${color}`} initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={springs.soft} />
      </div>
    </div>
  );
}
