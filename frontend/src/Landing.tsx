import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api, type Event } from "./api";
import { DemoSeatMap } from "./DemoSeatMap";
import { riseIn, springs, stagger, useMotionPrefs } from "./motion";

const FEATURES = [
  ["Never double-booked", "A Redis lock + Postgres row lock make it impossible for two fans to grab the same seat — even under a flood of concurrent requests."],
  ["Live seat map", "Seats update in real time over WebSockets. Watch the house fill as others book; your picks are held the moment you tap."],
  ["Fair queue at on-sale", "A virtual waiting room admits fans in order during demand spikes, so a popular drop stays fair instead of crashing."],
];

export function Landing({
  onTrySample, onDemoLogin, onOpenEvent, onDashboard, busy,
}: {
  onTrySample: () => void;
  onDemoLogin: () => void;
  onOpenEvent: (id: number) => void;
  onDashboard: () => void;
  busy: boolean;
}) {
  const { reduced } = useMotionPrefs();
  const [events, setEvents] = useState<Event[]>([]);
  useEffect(() => { api.events().then(setEvents).catch(() => {}); }, []);

  return (
    <div className="bg-aurora min-h-screen text-white">
      {/* nav */}
      <header className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
        <div className="flex items-center gap-2 text-lg font-bold tracking-tight">
          <span className="grid h-7 w-10 place-items-center rounded-md bg-cyan-400 text-black">🎟</span> TicketFlow
        </div>
        <div className="flex items-center gap-2 text-sm">
          <button onClick={onDashboard} className="rounded-lg px-3 py-1.5 text-white/60 hover:text-white">Organizer</button>
          <button onClick={onDemoLogin} className="rounded-lg border border-white/10 px-3 py-1.5 text-white/80 hover:bg-white/10">Demo login</button>
        </div>
      </header>

      {/* hero */}
      <section className="mx-auto grid max-w-6xl items-center gap-10 px-5 pb-8 pt-8 lg:grid-cols-2 lg:pt-16">
        <motion.div variants={stagger(0.08)} initial="hidden" animate="show">
          <motion.div variants={riseIn} className="mb-5 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-cyan-200/80">
            Real-time concurrent booking engine
          </motion.div>
          <motion.h1 variants={riseIn} className="text-5xl font-extrabold leading-[1.05] tracking-tight sm:text-6xl">
            Book the seat you want.{" "}
            <span className="bg-gradient-to-br from-cyan-300 to-indigo-400 bg-clip-text text-transparent">Before someone else does.</span>
          </motion.h1>
          <motion.p variants={riseIn} className="mt-5 max-w-lg text-lg text-white/60">
            A live, sectioned seat map where every pick is locked instantly and double-booking is impossible — even when thousands rush the same on-sale.
          </motion.p>

          <motion.div variants={riseIn} className="mt-8 flex flex-wrap items-center gap-3">
            <motion.button
              onClick={onTrySample} disabled={busy}
              whileHover={reduced ? undefined : { scale: 1.04, y: -2 }} whileTap={reduced ? undefined : { scale: 0.97 }}
              transition={springs.snappy}
              className="inline-flex items-center gap-2 rounded-full bg-cyan-400 px-7 py-3.5 font-semibold text-black shadow-[0_0_40px_-8px_rgba(34,211,238,0.7)] hover:bg-cyan-300 disabled:opacity-50"
            >
              {busy ? "Starting…" : "Try a sample event"}
              <span className="text-black/60">· no signup</span>
            </motion.button>
            <button onClick={onDemoLogin} className="rounded-full border border-white/15 px-6 py-3.5 text-sm font-semibold text-white/80 hover:bg-white/5">
              Or use the demo login
            </button>
          </motion.div>
          <motion.p variants={riseIn} className="mt-3 text-xs text-white/35">
            Guest mode is a real account behind the scenes — you'll run the exact hold → pay → ticket flow (test mode, no real card).
          </motion.p>
        </motion.div>

        {/* looping live-map demo */}
        <motion.div
          initial={{ opacity: 0, scale: 0.96, y: 16 }} animate={{ opacity: 1, scale: 1, y: 0 }} transition={springs.soft}
        >
          <DemoSeatMap />
        </motion.div>
      </section>

      {/* upcoming events */}
      <section className="mx-auto max-w-6xl px-5 py-12">
        <div className="mb-5 flex items-end justify-between">
          <h2 className="text-2xl font-bold tracking-tight">Upcoming events</h2>
          <span className="text-sm text-white/40">Tap any event to pick seats live</span>
        </div>
        <motion.div
          variants={stagger(0.06)} initial="hidden" animate="show"
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
        >
          {events.map((ev) => <EventCard key={ev.id} ev={ev} onOpen={() => onOpenEvent(ev.id)} reduced={reduced} />)}
          {events.length === 0 && <p className="text-white/40">Loading events…</p>}
        </motion.div>
      </section>

      {/* features */}
      <section className="mx-auto max-w-6xl px-5 py-12">
        <div className="grid gap-5 md:grid-cols-3">
          {FEATURES.map(([title, body]) => (
            <motion.div key={title}
              initial={{ opacity: 0, y: 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={springs.soft}
              className="rounded-2xl border border-white/10 bg-white/5 p-6 backdrop-blur-xl">
              <div className="text-lg font-semibold">{title}</div>
              <p className="mt-2 text-sm leading-relaxed text-white/55">{body}</p>
            </motion.div>
          ))}
        </div>
      </section>

      <footer className="mx-auto max-w-6xl px-5 py-10 text-sm text-white/40">
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-6">
          <span>TicketFlow — a concurrent booking system demo.</span>
          <button onClick={onDashboard} className="hover:text-white/70">Organizer dashboard →</button>
        </div>
      </footer>
    </div>
  );
}

function EventCard({ ev, onOpen, reduced }: { ev: Event; onOpen: () => void; reduced: boolean }) {
  const d = new Date(ev.starts_at);
  return (
    <motion.button
      variants={riseIn} onClick={onOpen}
      whileHover={reduced ? undefined : { y: -4, scale: 1.02 }} transition={springs.soft}
      className="group overflow-hidden rounded-2xl border border-white/10 bg-white/5 text-left backdrop-blur-xl"
    >
      <div className="relative h-28 bg-gradient-to-br from-cyan-500/25 via-indigo-500/20 to-fuchsia-500/15">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(255,255,255,0.12),transparent_60%)]" />
        <span className="absolute bottom-2 left-3 rounded-full bg-black/40 px-2 py-0.5 text-[10px] uppercase tracking-widest text-white/70">
          {ev.venue?.city ?? "Live"}
        </span>
      </div>
      <div className="p-4">
        <div className="line-clamp-2 font-semibold leading-snug">{ev.name}</div>
        <div className="mt-1 text-xs text-white/45">{ev.venue?.name}</div>
        <div className="mt-3 flex items-center justify-between text-xs">
          <span className="text-white/55">{d.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</span>
          <span className="font-semibold text-cyan-300 group-hover:underline">Pick seats →</span>
        </div>
      </div>
    </motion.button>
  );
}
