import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { api, setWaitToken, type WaitStatus } from "./api";
import { useMotionPrefs } from "./motion";

/** Calm, slow-drifting orbs behind the queue card — ambient, never distracting.
 * Disabled under prefers-reduced-motion. */
function AmbientField() {
  const { reduced } = useMotionPrefs();
  const orbs = useMemo(
    () => Array.from({ length: 5 }, (_, i) => ({
      id: i,
      size: 200 + Math.random() * 220,
      left: Math.random() * 100,
      top: Math.random() * 100,
      hue: ["bg-cyan-500/10", "bg-indigo-500/10", "bg-fuchsia-500/[0.07]"][i % 3],
      dur: 14 + Math.random() * 10,
      dx: (Math.random() - 0.5) * 80,
      dy: (Math.random() - 0.5) * 80,
    })),
    [],
  );
  if (reduced) return null;
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {orbs.map((o) => (
        <motion.div
          key={o.id}
          className={`absolute rounded-full blur-3xl ${o.hue}`}
          style={{ width: o.size, height: o.size, left: `${o.left}%`, top: `${o.top}%`, willChange: "transform" }}
          animate={{ x: [0, o.dx, 0], y: [0, o.dy, 0] }}
          transition={{ repeat: Infinity, duration: o.dur, ease: "easeInOut" }}
        />
      ))}
    </div>
  );
}

const ordinal = (n: number) => {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return n.toLocaleString() + (s[(v - 20) % 10] || s[v] || s[0]);
};
const fmtWait = (sec?: number) => {
  if (sec == null) return "—";
  if (sec < 60) return `~${sec}s`;
  return `~${Math.ceil(sec / 60)} min`;
};

export function WaitingRoom({ eventId, onAdmitted }: { eventId: number; onAdmitted: () => void }) {
  const [state, setState] = useState<WaitStatus | null>(null);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;

    async function tick(first: boolean) {
      try {
        const s = first ? await api.joinWaitroom(eventId) : await api.waitStatus(eventId);
        if (stop) return;
        setWaitToken(s.token);
        setState(s);
        if (s.status === "admitted") return onAdmitted();
        timer = setTimeout(() => tick(s.status === "expired"), s.status === "expired" ? 600 : 2500);
      } catch {
        if (!stop) timer = setTimeout(() => tick(false), 3000);
      }
    }
    tick(true);
    return () => { stop = true; clearTimeout(timer); };
  }, [eventId, onAdmitted]);

  return (
    <div className="bg-aurora relative min-h-screen flex items-center justify-center overflow-hidden p-4">
      <AmbientField />
      <motion.div
        initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
        className="relative z-10 w-full max-w-md rounded-2xl border border-white/10 bg-white/5 backdrop-blur-xl p-8 text-center shadow-2xl"
      >
        <motion.div
          className="mx-auto mb-6 h-12 w-12 rounded-full border-2 border-cyan-400/30 border-t-cyan-400"
          animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: "linear" }}
        />
        <div className="text-xl font-bold tracking-tight">You're in the queue</div>
        <p className="mt-1 text-sm text-white/50">High demand — we're letting fans in a few at a time to keep things fair.</p>

        <div className="mt-7">
          <motion.div
            key={state?.position ?? "init"}
            initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
            className="text-5xl font-extrabold text-cyan-300"
          >
            {state?.position != null ? ordinal(state.position) : "…"}
          </motion.div>
          <div className="mt-1 text-sm text-white/50">in line</div>
        </div>

        <div className="mt-6 flex items-center justify-center gap-6 text-sm">
          <div>
            <div className="text-white/40">Est. wait</div>
            <div className="font-semibold">{fmtWait(state?.estimated_wait_seconds)}</div>
          </div>
          <div className="h-8 w-px bg-white/10" />
          <div>
            <div className="text-white/40">Ahead of you</div>
            <div className="font-semibold">{(state?.ahead ?? 0).toLocaleString()}</div>
          </div>
        </div>

        <p className="mt-7 text-xs text-white/40">Keep this tab open — you'll move to the seat map automatically.</p>
      </motion.div>
    </div>
  );
}
