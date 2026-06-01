import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api, type Event } from "./api";
import { DemoSeatMap } from "./DemoSeatMap";
import { riseIn, springs, stagger, useMotionPrefs } from "./motion";

const FEATURES = [
  ["01", "Never double-booked", "A Redis lock + Postgres row lock make it impossible for two fans to grab the same seat — even under a flood of concurrent requests."],
  ["02", "Live seat map", "Seats update in real time over WebSockets. Watch the house fill as others book; your picks are held the instant you tap."],
  ["03", "Fair queue on-sale", "A virtual waiting room admits fans in order during demand spikes, so a popular drop stays fair instead of falling over."],
] as const;

const NAV = ["EVENTS", "SEAT MAP", "WAITING ROOM", "ORGANIZER"];
const CONCERTS = ["/concerts/stage-purple.jpg", "/concerts/stage-confetti.jpg", "/concerts/crowd.jpg", "/concerts/festival.jpg"];

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
    <div className="bg-aurora min-h-screen text-ink">
      {/* full-bleed concert backdrop behind the hero (tinted into the synthwave
          palette + faded to navy so the headline stays crisp) */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-0 h-[880px] overflow-hidden">
        <img src="/concerts/stage-purple.jpg" alt="" className="h-full w-full object-cover object-center opacity-60" />
        <div className="absolute inset-0 bg-gradient-to-b from-surface/30 via-surface/60 to-surface" />
        <div className="absolute inset-0 bg-gradient-to-r from-surface via-surface/45 to-transparent" />
        <div className="absolute inset-0 bg-indigo2/20 mix-blend-overlay" />
      </div>

      {/* nav */}
      <header className="relative z-10 mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <button onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })} className="flex items-center gap-2">
          <span className="text-primary">◆</span>
          <span className="font-display text-2xl tracking-[0.12em]">TICKETFLOW</span>
        </button>
        <nav className="hidden items-center gap-8 md:flex">
          {NAV.map((n) => (
            <button key={n} onClick={n === "ORGANIZER" ? onDashboard : onTrySample}
              className="eyebrow text-[11px] text-ink-dim transition hover:text-primary">{n}</button>
          ))}
        </nav>
        <button onClick={onDemoLogin}
          className="rounded-md bg-primary px-5 py-2 font-accent text-sm font-bold text-[#3a0066] transition hover:brightness-110 glow-primary">
          GET ACCESS
        </button>
      </header>

      {/* hero */}
      <section className="relative z-10 mx-auto grid max-w-6xl items-center gap-12 px-6 pb-12 pt-10 lg:grid-cols-[1.05fr_0.95fr] lg:pt-16">
        <motion.div variants={stagger(0.08)} initial="hidden" animate="show">
          <motion.div variants={riseIn} className="eyebrow mb-6 text-[11px] text-primary/80">
            Real-time concurrent booking engine
          </motion.div>

          <motion.h1 variants={riseIn} className="font-display text-7xl leading-[0.92] sm:text-8xl">
            BOOK THE<br />
            <span className="text-primary text-glow">SEAT YOU WANT.</span>
          </motion.h1>
          <motion.div variants={riseIn} className="-mt-1">
            <span className="font-accent text-xl italic text-periwinkle/90">before someone else does.</span>
          </motion.div>

          <motion.p variants={riseIn} className="mt-6 max-w-md text-lg leading-relaxed text-ink-dim">
            Step into the rush. A live, sectioned seat map where every pick is locked instantly and double-booking is
            <span className="text-ink"> impossible</span> — even when thousands hit the same on-sale.
          </motion.p>

          <motion.div variants={riseIn} className="mt-9 flex flex-wrap items-center gap-3">
            <motion.button
              onClick={onTrySample} disabled={busy}
              whileHover={reduced ? undefined : { scale: 1.03, y: -2 }} whileTap={reduced ? undefined : { scale: 0.97 }}
              transition={springs.snappy}
              className="inline-flex items-center gap-2 rounded-md bg-gradient-to-br from-[#9333ea] to-[#7f34df] px-7 py-3.5 font-accent text-sm font-bold uppercase tracking-wider text-white glow-primary disabled:opacity-50"
            >
              {busy ? "Starting…" : "Try a sample event"}
              <span className="text-white/60">— no signup</span>
            </motion.button>
            <button onClick={onDemoLogin}
              className="rounded-md border border-line px-6 py-3.5 font-accent text-sm font-bold uppercase tracking-wider text-ink/80 transition hover:border-primary/60 hover:text-primary">
              Demo login
            </button>
          </motion.div>
          <motion.p variants={riseIn} className="mt-4 text-xs text-ink-dim/70">
            Guest mode runs the real hold → pay → ticket flow (Stripe test mode — no real card).
          </motion.p>
        </motion.div>

        {/* right: live-map "pass" with a floating stat chip */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 18 }} animate={{ opacity: 1, scale: 1, y: 0 }} transition={springs.soft}
          className="relative"
        >
          <div className="glass rounded-xl p-3 glow-indigo">
            <DemoSeatMap />
          </div>
          <motion.div
            initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ ...springs.soft, delay: 0.3 }}
            className="absolute -right-3 -top-5 flex items-center gap-3 rounded-lg border border-line bg-surface-1/90 px-4 py-2.5 backdrop-blur-xl glow-primary"
          >
            <div className="flex -space-x-2">
              {["#b76dff", "#3626ce", "#c3c0ff", "#a855f7"].map((c, i) => (
                <span key={i} className="h-6 w-6 rounded-full border-2 border-surface-1" style={{ background: c }} />
              ))}
            </div>
            <div className="leading-tight">
              <div className="font-display text-lg text-primary">1,112 SEATS</div>
              <div className="text-[10px] text-ink-dim">live across 4 events</div>
            </div>
          </motion.div>
        </motion.div>
      </section>

      {/* events */}
      <section className="relative z-10 mx-auto max-w-6xl px-6 py-14">
        <div className="mb-7 flex items-end justify-between border-b border-line/60 pb-4">
          <h2 className="font-display text-5xl">UPCOMING EVENTS</h2>
          <span className="eyebrow text-[10px] text-ink-dim">Tap a pass to pick seats live</span>
        </div>
        <motion.div
          variants={stagger(0.06)} initial="hidden" animate="show"
          className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4"
        >
          {events.map((ev, i) => <PassCard key={ev.id} ev={ev} img={CONCERTS[i % CONCERTS.length]} onOpen={() => onOpenEvent(ev.id)} reduced={reduced} />)}
          {events.length === 0 && <p className="text-ink-dim">Loading events…</p>}
        </motion.div>
      </section>

      {/* features */}
      <section className="relative z-10 mx-auto max-w-6xl px-6 py-14">
        <div className="grid gap-5 md:grid-cols-3">
          {FEATURES.map(([num, title, body]) => (
            <motion.div key={num}
              initial={{ opacity: 0, y: 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={springs.soft}
              className="glass rounded-xl p-6">
              <div className="font-display text-3xl text-primary/40">{num}</div>
              <div className="mt-2 font-accent text-lg font-bold">{title}</div>
              <p className="mt-2 text-sm leading-relaxed text-ink-dim">{body}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* footer */}
      <footer className="relative z-10 mx-auto max-w-6xl px-6 py-10">
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-line/60 pt-6 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-primary">◆</span>
            <span className="font-display text-xl tracking-[0.12em]">TICKETFLOW</span>
          </div>
          <div className="flex flex-wrap gap-6 eyebrow text-[10px] text-ink-dim">
            <button onClick={onTrySample} className="hover:text-primary">EVENTS</button>
            <button onClick={onDashboard} className="hover:text-primary">ORGANIZER</button>
            <a href="/api/docs" className="hover:text-primary">API</a>
          </div>
          <span className="eyebrow text-[10px] text-ink-dim/60">© 2026 TICKETFLOW · BUILT FOR THE RUSH</span>
        </div>
      </footer>
    </div>
  );
}

function PassCard({ ev, img, onOpen, reduced }: { ev: Event; img: string; onOpen: () => void; reduced: boolean }) {
  const d = new Date(ev.starts_at);
  return (
    <motion.button
      variants={riseIn} onClick={onOpen}
      whileHover={reduced ? undefined : { y: -5 }} transition={springs.soft}
      className="group relative overflow-hidden rounded-xl border border-line bg-surface-1 text-left transition hover:border-primary/50"
    >
      {/* pass header — real concert photo, tinted into the palette + notch */}
      <div className="relative h-32 overflow-hidden">
        <img src={img} alt="" loading="lazy"
          className="h-full w-full object-cover transition duration-500 group-hover:scale-105" />
        <div className="absolute inset-0 bg-gradient-to-t from-surface-1 via-surface-1/30 to-transparent" />
        <div className="absolute inset-0 bg-indigo2/35 mix-blend-multiply" />
        <span className="eyebrow absolute left-3 top-3 rounded bg-black/40 px-2 py-0.5 text-[9px] text-white/90">3-DAY PASS</span>
        <span className="absolute bottom-2 left-3 rounded bg-black/40 px-2 py-0.5 text-[10px] uppercase tracking-widest text-white/90">
          {ev.venue?.city ?? "Live"}
        </span>
        {/* perforation */}
        <span className="absolute -bottom-2 left-1/2 h-4 w-4 -translate-x-1/2 rounded-full bg-surface" />
      </div>
      <div className="p-4">
        <div className="line-clamp-2 font-display text-xl leading-tight tracking-wide">{ev.name}</div>
        <div className="mt-1 text-xs text-ink-dim">{ev.venue?.name}</div>
        <div className="mt-3 flex items-center justify-between">
          <span className="font-accent text-sm font-bold text-periwinkle">
            {d.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
          </span>
          <span className="eyebrow text-[10px] text-primary group-hover:text-glow">PICK SEATS →</span>
        </div>
      </div>
    </motion.button>
  );
}
