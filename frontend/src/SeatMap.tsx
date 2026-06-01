import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, animate, motion, useMotionValue } from "framer-motion";
import type { Seat } from "./api";
import { clamp, seatVariants, springs, useMotionPrefs } from "./motion";

const SEAT = 26;       // seat box px
const GAP = 8;         // gap between seats / rows
const SECTION_GAP = 40;
const LABEL_H = 20;
const MIN_S = 0.5;
const MAX_S = 3.2;
const inr = (c: number) => `₹${(c / 100).toLocaleString("en-IN")}`;

type Placed = { seat: Seat; left: number; top: number };
type Band = { name: string; top: number; height: number; left: number; width: number };

/** Build a fixed-size canvas layout (sections → rows → seats) so we can both
 * render absolutely-positioned seats and compute camera framing geometry. */
function useLayout(seats: Seat[]) {
  return useMemo(() => {
    const sections = new Map<string, Map<string, Seat[]>>();
    for (const s of seats) {
      const rest = s.section && s.seat_number.startsWith(s.section + "-")
        ? s.seat_number.slice(s.section.length + 1) : s.seat_number;
      const row = (rest.match(/^[A-Za-z]+/) || ["A"])[0];
      if (!sections.has(s.section)) sections.set(s.section, new Map());
      const rows = sections.get(s.section)!;
      if (!rows.has(row)) rows.set(row, []);
      rows.get(row)!.push(s);
    }

    const placed: Placed[] = [];
    const bands: Band[] = [];
    let y = 0;
    let canvasW = 0;
    for (const [name, rows] of sections) {
      const bandTop = y;
      y += LABEL_H + 6;
      let bandW = 0;
      for (const [, rowSeats] of [...rows.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
        rowSeats.sort((a, b) =>
          (+a.seat_number.replace(/\D/g, "") || 0) - (+b.seat_number.replace(/\D/g, "") || 0));
        rowSeats.forEach((seat, i) => placed.push({ seat, left: i * (SEAT + GAP), top: y }));
        bandW = Math.max(bandW, rowSeats.length * (SEAT + GAP));
        y += SEAT + GAP;
      }
      bands.push({ name, top: bandTop, height: y - bandTop, left: 0, width: bandW });
      canvasW = Math.max(canvasW, bandW);
      y += SECTION_GAP;
    }
    for (const b of bands) b.width = canvasW;
    return { placed, bands, width: canvasW, height: y };
  }, [seats]);
}

export function SeatMap({
  seats, selected, flash, onToggle, maxSelect,
}: {
  seats: Seat[];
  selected: Set<number>;
  flash: Set<number>;          // seat ids just taken by someone else (live)
  onToggle: (s: Seat) => void;
  maxSelect: number;
}) {
  const { reduced } = useMotionPrefs();
  const { placed, bands, width, height } = useLayout(seats);
  const viewportRef = useRef<HTMLDivElement>(null);

  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const s = useMotionValue(1);                 // applied scale (instant for focal zoom)
  const [ripples, setRipples] = useState<{ id: number; left: number; top: number }[]>([]);

  const flyTo = useCallback((left: number, top: number, w: number, h: number) => {
    const vp = viewportRef.current;
    if (!vp) return;
    const vw = vp.clientWidth, vh = vp.clientHeight;
    const pad = 48;
    const target = clamp(Math.min(vw / (w + pad), vh / (h + pad)), MIN_S, MAX_S);
    const nx = vw / 2 - (left + w / 2) * target;
    const ny = vh / 2 - (top + h / 2) * target;
    const t = reduced ? { duration: 0 } : springs.camera;
    animate(s, target, t);
    animate(x, nx, t);
    animate(y, ny, t);
  }, [reduced, s, x, y]);

  // Initial framing: fit the whole map once we know the viewport size.
  useEffect(() => {
    if (width && height) flyTo(0, 0, width, height);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [width, height]);

  // Focal wheel / trackpad-pinch zoom (keeps the point under the cursor fixed).
  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const vp = viewportRef.current!;
    const rect = vp.getBoundingClientRect();
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    const cur = s.get();
    const factor = e.ctrlKey ? 1 - e.deltaY * 0.01 : 1 - e.deltaY * 0.0016; // ctrl = pinch
    const next = clamp(cur * factor, MIN_S, MAX_S);
    const contentX = (cx - x.get()) / cur;
    const contentY = (cy - y.get()) / cur;
    s.set(next);
    x.set(cx - contentX * next);
    y.set(cy - contentY * next);
  }, [s, x, y]);

  const handleToggle = (p: Placed) => {
    const wasSelected = selected.has(p.seat.id);
    onToggle(p.seat);
    if (!wasSelected && p.seat.status === "AVAILABLE") {
      // ripple from the seat + camera frames its section
      if (!reduced) {
        const rid = Date.now() + p.seat.id;
        setRipples((r) => [...r, { id: rid, left: p.left + SEAT / 2, top: p.top + SEAT / 2 }]);
        setTimeout(() => setRipples((r) => r.filter((x) => x.id !== rid)), 700);
      }
      const band = bands.find((b) => b.name === p.seat.section);
      if (band) flyTo(band.left, band.top, band.width, band.height);
    }
  };

  return (
    <div className="relative">
      {/* stage marker */}
      <div className="eyebrow mb-3 rounded-md bg-gradient-to-r from-primary-deep/25 to-indigo2/30 py-2 text-center text-[11px] text-ink/70">
        Stage
      </div>

      <div
        ref={viewportRef}
        onWheel={onWheel}
        className="relative h-[58vh] w-full overflow-hidden rounded-2xl border border-white/10 bg-black/30 touch-none"
        style={{ contain: "layout paint" }}
      >
        <motion.div
          drag={!reduced}
          dragMomentum
          dragElastic={0.12}
          dragTransition={{ power: 0.5, timeConstant: 320, bounceStiffness: 200, bounceDamping: 28 }}
          style={{ x, y, scale: s, width, height, transformOrigin: "0 0", willChange: "transform" }}
          className="absolute left-0 top-0 cursor-grab active:cursor-grabbing"
        >
          {/* section labels */}
          {bands.map((b) => (
            <div key={b.name} className="absolute text-[11px] font-semibold uppercase tracking-widest text-white/40"
                 style={{ left: 0, top: b.top, width: b.width }}>
              {b.name}
            </div>
          ))}

          {/* ripples */}
          <AnimatePresence>
            {ripples.map((r) => (
              <motion.span key={r.id}
                className="pointer-events-none absolute rounded-full border border-cyan-300/60"
                style={{ left: r.left, top: r.top, width: 0, height: 0, x: "-50%", y: "-50%" }}
                initial={{ width: 8, height: 8, opacity: 0.7 }}
                animate={{ width: 140, height: 140, opacity: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.6, ease: "easeOut" }} />
            ))}
          </AnimatePresence>

          {/* seats */}
          {placed.map((p) => (
            <SeatDot key={p.seat.id} p={p}
              selected={selected.has(p.seat.id)}
              locking={flash.has(p.seat.id)}
              reduced={reduced}
              disabled={selected.size >= maxSelect && !selected.has(p.seat.id)}
              onClick={() => handleToggle(p)} />
          ))}
        </motion.div>

        {/* zoom controls */}
        <div className="absolute bottom-3 right-3 flex flex-col gap-1.5">
          {[["+", 1.3], ["−", 1 / 1.3]].map(([label, f]) => (
            <button key={label as string}
              onClick={() => { const vp = viewportRef.current!; const cx = vp.clientWidth / 2, cy = vp.clientHeight / 2;
                const cur = s.get(); const next = clamp(cur * (f as number), MIN_S, MAX_S);
                const cX = (cx - x.get()) / cur, cY = (cy - y.get()) / cur;
                animate(s, next, springs.snappy); animate(x, cx - cX * next, springs.snappy); animate(y, cy - cY * next, springs.snappy); }}
              className="h-8 w-8 rounded-lg border border-white/10 bg-white/10 text-white/80 backdrop-blur hover:bg-white/20">
              {label as string}
            </button>
          ))}
          <button onClick={() => flyTo(0, 0, width, height)}
            className="h-8 w-8 rounded-lg border border-white/10 bg-white/10 text-[10px] text-white/80 backdrop-blur hover:bg-white/20"
            title="Fit">⤢</button>
        </div>
      </div>

      <Legend />
    </div>
  );
}

function SeatDot({ p, selected, locking, reduced, disabled, onClick }: {
  p: Placed; selected: boolean; locking: boolean; reduced: boolean; disabled: boolean; onClick: () => void;
}) {
  const { seat } = p;
  const sold = seat.status === "SOLD";
  const held = seat.status === "HELD";
  const interactive = seat.status === "AVAILABLE" || selected;

  let cls = "bg-slate-600/50 text-white/70"; // available
  if (selected) cls = "bg-cyan-400 text-black";
  else if (sold) cls = "bg-rose-900/70 text-white/30";
  else if (held) cls = "bg-amber-500/50 text-white/60";

  const state = selected ? "selected" : locking ? "locking" : "available";

  return (
    <motion.button
      onClick={onClick}
      disabled={!interactive || disabled}
      variants={seatVariants}
      animate={state}
      whileHover={reduced || !interactive ? undefined : "hover"}
      whileTap={reduced || !interactive ? undefined : "tap"}
      transition={springs.soft}
      className={`absolute grid place-items-center rounded-md text-[10px] font-medium ${cls} ${interactive ? "cursor-pointer" : "cursor-not-allowed"}`}
      style={{ left: p.left, top: p.top, width: SEAT, height: SEAT, transformStyle: "preserve-3d", willChange: "transform" }}
      title={`${seat.seat_number} · ${seat.status} · ${inr(seat.price_cents)}`}
    >
      {seat.seat_number.replace(/^[^-]*-?[A-Za-z]+/, "")}
      {/* soft pulse ring while selected */}
      {selected && !reduced && (
        <motion.span className="pointer-events-none absolute inset-0 rounded-md ring-2 ring-cyan-300"
          initial={{ opacity: 0.8, scale: 1 }} animate={{ opacity: 0, scale: 1.9 }}
          transition={{ duration: 0.7, ease: "easeOut" }} />
      )}
    </motion.button>
  );
}

function Legend() {
  const items = [["bg-slate-600/50", "Available"], ["bg-cyan-400", "Selected"],
    ["bg-amber-500/50", "Held"], ["bg-rose-900/70", "Sold"]] as const;
  return (
    <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-white/50">
      {items.map(([c, label]) => (
        <div key={label} className="flex items-center gap-2"><span className={`h-3 w-3 rounded ${c}`} />{label}</div>
      ))}
      <span className="ml-auto text-white/30">drag to pan · scroll to zoom · pick a seat to fly in</span>
    </div>
  );
}
