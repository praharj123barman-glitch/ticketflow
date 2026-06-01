/**
 * Shared motion system — spring presets + transition variants used across the
 * app so every animation feels like it belongs to one product, not one-offs.
 * All animations are transform/opacity only (GPU-composited) to hold 60fps.
 */
import { useReducedMotion } from "framer-motion";
import type { Transition, Variants } from "framer-motion";

export const springs = {
  /** general UI motion */
  soft: { type: "spring", stiffness: 210, damping: 26, mass: 0.8 },
  /** quick, decisive */
  snappy: { type: "spring", stiffness: 420, damping: 32 },
  /** seat select — overshoots, satisfying */
  pop: { type: "spring", stiffness: 560, damping: 16, mass: 0.7 },
  /** ambient / calm (waiting room) */
  gentle: { type: "spring", stiffness: 80, damping: 18 },
  /** camera fly-to — heavy, cinematic */
  camera: { type: "spring", stiffness: 120, damping: 26, mass: 1 },
} satisfies Record<string, Transition>;

/** Seat visual states (transform/opacity only). */
export const seatVariants: Variants = {
  available: { scale: 1, y: 0, rotateY: 0, opacity: 1 },
  hover: { scale: 1.22, y: -3 },
  tap: { scale: 0.86 },
  selected: { scale: [1, 1.32, 1.12], y: -1, transition: springs.pop },
  // someone else grabbed it: flip + settle into a dimmed "taken" state
  locking: { scale: [1, 0.86, 1], rotateY: [0, 180, 360], transition: { duration: 0.55 } },
};

/** Staggered container reveal (used for scenes/lists). */
export const stagger = (each = 0.045): Variants => ({
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: each } },
});

export const riseIn: Variants = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: springs.soft },
};

/**
 * Scene transitions — used by the booking flow (hero → seat map → checkout →
 * confirmation). Direction-aware so forward navigation slides/scales inward and
 * back pops outward, giving one continuous "camera move" feel between screens.
 */
export const sceneVariants: Variants = {
  enter: (dir: number) => ({ opacity: 0, x: dir > 0 ? 64 : -64, scale: 0.98, filter: "blur(6px)" }),
  center: { opacity: 1, x: 0, scale: 1, filter: "blur(0px)", transition: { ...springs.soft, filter: { duration: 0.3 } } },
  exit: (dir: number) => ({ opacity: 0, x: dir > 0 ? -48 : 48, scale: 0.99, filter: "blur(4px)", transition: { duration: 0.28, ease: "easeIn" } }),
};

/** E-ticket reveal — flips in from edge-on with a slight overshoot. */
export const ticketFlip: Variants = {
  hidden: { rotateY: -92, opacity: 0, y: 28, scale: 0.92 },
  show: { rotateY: 0, opacity: 1, y: 0, scale: 1, transition: { type: "spring", stiffness: 140, damping: 17, mass: 0.9 } },
};

/**
 * Countdown tension: maps remaining time to a color and a pulse flag. Calm cyan
 * when there's time, amber under 90s, red at the wire. Pure function so any
 * countdown UI shares the exact same ramp.
 */
export function countdownTone(remainingMs: number, totalMs: number) {
  const frac = clamp(totalMs ? remainingMs / totalMs : 0, 0, 1);
  const seconds = remainingMs / 1000;
  if (seconds <= 30) return { color: "#fb7185", glow: "rgba(251,113,133,0.55)", urgent: true, frac };   // rose
  if (seconds <= 90) return { color: "#fbbf24", glow: "rgba(251,191,36,0.45)", urgent: false, frac };   // amber
  return { color: "#22d3ee", glow: "rgba(34,211,238,0.35)", urgent: false, frac };                       // cyan
}

/**
 * Confetti pieces (transform/opacity only). Generated once per burst; the
 * component animates each piece's fall. Reduced-motion callers don't render these.
 */
export function makeConfetti(n = 80) {
  const colors = ["#22d3ee", "#818cf8", "#f472b6", "#fbbf24", "#34d399", "#ffffff"];
  return Array.from({ length: n }, (_, i) => ({
    id: i,
    x: Math.random() * 100,                 // vw start
    delay: Math.random() * 0.25,
    duration: 1.6 + Math.random() * 1.4,
    drift: (Math.random() - 0.5) * 220,     // px horizontal drift
    rotate: Math.random() * 720 - 360,
    size: 6 + Math.random() * 8,
    color: colors[i % colors.length],
  }));
}

/**
 * Reduced-motion-aware presets. When the user prefers reduced motion we keep
 * state changes (color/position) but strip springs/overshoot/parallax.
 */
export function useMotionPrefs() {
  const reduced = !!useReducedMotion();
  return {
    reduced,
    transition: reduced ? ({ duration: 0 } as Transition) : springs.soft,
    camera: reduced ? ({ duration: 0 } as Transition) : springs.camera,
    // hover/tap disabled under reduced motion
    hover: reduced ? undefined : "hover",
    tap: reduced ? undefined : "tap",
  };
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
