import { useMemo } from "react";
import { motion } from "framer-motion";
import { makeConfetti, useMotionPrefs } from "./motion";

/**
 * One celebratory confetti burst. Pure transform/opacity (GPU-composited), fixed
 * overlay, pointer-events-none. Renders nothing under prefers-reduced-motion.
 * Mount it when the moment happens; unmount (or key it) to re-fire.
 */
export function Confetti({ count = 90 }: { count?: number }) {
  const { reduced } = useMotionPrefs();
  const pieces = useMemo(() => makeConfetti(count), [count]);
  if (reduced) return null;

  return (
    <div className="pointer-events-none fixed inset-0 z-50 overflow-hidden">
      {pieces.map((p) => (
        <motion.span
          key={p.id}
          className="absolute top-0 rounded-[2px]"
          style={{ left: `${p.x}vw`, width: p.size, height: p.size * 0.6, background: p.color, willChange: "transform" }}
          initial={{ y: -20, x: 0, rotate: 0, opacity: 1 }}
          animate={{ y: "108vh", x: p.drift, rotate: p.rotate, opacity: [1, 1, 0.9, 0] }}
          transition={{ delay: p.delay, duration: p.duration, ease: [0.2, 0.6, 0.4, 1] }}
        />
      ))}
    </div>
  );
}
