import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { springs, useMotionPrefs } from "./motion";

/** A purpose-built, self-driving seat map for the landing hero — it loops
 * forever showing seats getting taken by "other fans" in real time and your own
 * pick popping in, in the same visual language as the real map. Not interactive;
 * it's a living screenshot. Static (no loop) under prefers-reduced-motion. */
const ROWS = 7, COLS = 18;
const TOTAL = ROWS * COLS;

type St = "available" | "held" | "sold" | "mine";

export function DemoSeatMap() {
  const { reduced } = useMotionPrefs();
  // start with a believable ~35% sold house
  const [seats, setSeats] = useState<St[]>(() =>
    Array.from({ length: TOTAL }, () => (Math.random() < 0.35 ? "sold" : "available")),
  );
  const [mine, setMine] = useState<number[]>([]);

  useEffect(() => {
    if (reduced) return;
    const id = setInterval(() => {
      setSeats((prev) => {
        const next = [...prev];
        // a few seats get held by others, some convert to sold, occasional churn
        for (let k = 0; k < 3; k++) {
          const i = Math.floor(Math.random() * TOTAL);
          if (next[i] === "available") next[i] = "held";
          else if (next[i] === "held") next[i] = "sold";
        }
        // keep the house from filling up entirely — free a couple back
        for (let k = 0; k < 2; k++) {
          const i = Math.floor(Math.random() * TOTAL);
          if (next[i] === "sold" && Math.random() < 0.5) next[i] = "available";
        }
        return next;
      });
      // cycle "your" selection of 2 adjacent good seats
      setMine(() => {
        const start = Math.floor(Math.random() * (TOTAL - 2));
        return [start, start + 1];
      });
    }, 1100);
    return () => clearInterval(id);
  }, [reduced]);

  const color = (s: St, isMine: boolean) =>
    isMine ? "bg-cyan-400" : s === "sold" ? "bg-rose-900/70" : s === "held" ? "bg-amber-500/60" : "bg-slate-600/40";

  const cells = useMemo(() => Array.from({ length: TOTAL }, (_, i) => i), []);

  return (
    <div className="rounded-2xl border border-white/10 bg-black/40 p-4 shadow-2xl">
      <div className="mb-3 rounded-full bg-gradient-to-r from-cyan-500/20 to-indigo-500/20 py-1.5 text-center text-[9px] uppercase tracking-[0.4em] text-white/60">
        Stage
      </div>
      <div className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${COLS}, minmax(0, 1fr))` }}>
        {cells.map((i) => {
          const isMine = mine.includes(i);
          return (
            <motion.div
              key={i}
              className={`aspect-square rounded-[3px] ${color(seats[i], isMine)}`}
              animate={isMine ? { scale: [1, 1.35, 1.12] } : { scale: 1 }}
              transition={isMine ? springs.pop : springs.soft}
            />
          );
        })}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3 text-[11px] text-white/50">
        <Legend c="bg-slate-600/40" t="Available" />
        <Legend c="bg-cyan-400" t="Your pick" />
        <Legend c="bg-amber-500/60" t="Held" />
        <Legend c="bg-rose-900/70" t="Sold" />
        <span className="ml-auto flex items-center gap-1.5 text-cyan-300/80">
          <motion.span className="h-1.5 w-1.5 rounded-full bg-cyan-400"
            animate={reduced ? undefined : { opacity: [1, 0.3, 1] }} transition={{ repeat: Infinity, duration: 1.6 }} />
          live
        </span>
      </div>
    </div>
  );
}

const Legend = ({ c, t }: { c: string; t: string }) => (
  <span className="flex items-center gap-1.5"><span className={`h-2.5 w-2.5 rounded-[2px] ${c}`} />{t}</span>
);
