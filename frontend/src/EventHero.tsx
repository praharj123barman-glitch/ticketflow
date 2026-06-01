import { useRef } from "react";
import { motion, useMotionValue, useSpring, useTransform } from "framer-motion";
import type { EventDetail } from "./api";
import { riseIn, springs, stagger, useMotionPrefs } from "./motion";

const inr = (cents: number) => `₹${(cents / 100).toLocaleString("en-IN")}`;

/**
 * Cinematic event landing — layered orbs drift with the cursor (parallax) and
 * the headline reveals word-by-word. "Get tickets" hands off to the seat map.
 */
export function EventHero({ event, onEnter }: { event: EventDetail; onEnter: () => void }) {
  const { reduced } = useMotionPrefs();
  const ref = useRef<HTMLDivElement>(null);

  // Cursor parallax: pointer position → smoothed -0.5..0.5 offset for each layer.
  const px = useMotionValue(0);
  const py = useMotionValue(0);
  const mx = useSpring(px, { stiffness: 60, damping: 18 });
  const my = useSpring(py, { stiffness: 60, damping: 18 });
  const onMove = (e: React.PointerEvent) => {
    if (reduced || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    px.set((e.clientX - r.left) / r.width - 0.5);
    py.set((e.clientY - r.top) / r.height - 0.5);
  };

  // Three depth layers move at different magnitudes.
  const far = { x: useTransform(mx, (v) => v * 24), y: useTransform(my, (v) => v * 24) };
  const mid = { x: useTransform(mx, (v) => v * -48), y: useTransform(my, (v) => v * -48) };
  const near = { x: useTransform(mx, (v) => v * 70), y: useTransform(my, (v) => v * 70) };

  const date = new Date(event.starts_at);
  const dateStr = date.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const timeStr = date.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
  const words = event.name.split(" ");
  const minPrice = event.tiers.length ? Math.min(...event.tiers.map((t) => t.price_cents)) : 0;

  return (
    <div
      ref={ref}
      onPointerMove={onMove}
      className="relative flex min-h-[82vh] items-center justify-center overflow-hidden rounded-3xl border border-white/10 bg-black/40 px-6 py-16"
    >
      {/* parallax depth layers */}
      <motion.div style={far} className="pointer-events-none absolute -left-32 -top-24 h-96 w-96 rounded-full bg-cyan-500/20 blur-3xl" />
      <motion.div style={mid} className="pointer-events-none absolute -right-24 top-10 h-[28rem] w-[28rem] rounded-full bg-indigo-500/20 blur-3xl" />
      <motion.div style={near} className="pointer-events-none absolute bottom-[-6rem] left-1/3 h-80 w-80 rounded-full bg-fuchsia-500/10 blur-3xl" />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_120%,rgba(34,211,238,0.10),transparent_55%)]" />

      <motion.div
        variants={stagger(0.08)} initial="hidden" animate="show"
        className="relative z-10 mx-auto max-w-3xl text-center"
      >
        <motion.div variants={riseIn} className="eyebrow mb-5 inline-flex items-center gap-2 rounded-md border border-line bg-surface-1/60 px-4 py-1.5 text-[11px] text-primary/80">
          {event.venue?.city || "Live"} · {event.available} seats left
        </motion.div>

        {/* word-by-word headline reveal */}
        <h1 className="font-display flex flex-wrap justify-center gap-x-5 text-6xl leading-[0.95] text-white sm:text-8xl">
          {words.map((w, i) => (
            <span key={i} className="inline-block overflow-hidden">
              <motion.span
                className="inline-block bg-gradient-to-br from-white via-primary to-primary-deep bg-clip-text text-transparent"
                initial={{ y: "110%", opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ ...springs.soft, delay: 0.15 + i * 0.08 }}
              >
                {w}
              </motion.span>
            </span>
          ))}
        </h1>

        <motion.p variants={riseIn} className="mx-auto mt-6 max-w-xl text-lg text-white/60">
          {event.description || "An unmissable live experience."}
        </motion.p>

        <motion.div variants={riseIn} className="mt-8 flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-sm text-white/70">
          <Meta label="Venue" value={event.venue?.name ?? "TBA"} />
          <Dot />
          <Meta label="Date" value={dateStr} />
          <Dot />
          <Meta label="Doors" value={timeStr} />
          {minPrice > 0 && (<><Dot /><Meta label="From" value={inr(minPrice)} /></>)}
        </motion.div>

        <motion.button
          variants={riseIn}
          onClick={onEnter}
          whileHover={reduced ? undefined : { scale: 1.04, y: -2 }}
          whileTap={reduced ? undefined : { scale: 0.97 }}
          transition={springs.snappy}
          className="group mt-10 inline-flex items-center gap-2 rounded-full bg-cyan-400 px-8 py-4 text-base font-semibold text-black shadow-[0_0_40px_-8px_rgba(34,211,238,0.7)] hover:bg-cyan-300"
        >
          Get tickets
          <motion.span className="inline-block" animate={reduced ? undefined : { x: [0, 4, 0] }} transition={{ repeat: Infinity, duration: 1.4 }}>→</motion.span>
        </motion.button>
        <motion.p variants={riseIn} className="mt-4 text-xs text-white/35">Pick your seats on an interactive map · held for 10 minutes at checkout</motion.p>
      </motion.div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-left">
      <div className="text-[10px] uppercase tracking-widest text-white/35">{label}</div>
      <div className="font-semibold text-white/85">{value}</div>
    </div>
  );
}
const Dot = () => <span className="hidden h-1 w-1 rounded-full bg-white/20 sm:block" />;
