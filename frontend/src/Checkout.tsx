import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { api, type Booking, type Hold, type Seat } from "./api";
import { countdownTone, riseIn, springs, stagger, useMotionPrefs } from "./motion";

const inr = (cents: number) => `₹${(cents / 100).toLocaleString("en-IN")}`;
const RING = 132, R = 58, C = 2 * Math.PI * R;

/** Live remaining-ms ticker for a hold, plus the total window for the ring %. */
function useCountdown(expiresAt: string) {
  const target = useMemo(() => new Date(expiresAt).getTime(), [expiresAt]);
  const totalRef = useRef<number>(Math.max(1, target - Date.now()));
  const [remaining, setRemaining] = useState(() => Math.max(0, target - Date.now()));
  useEffect(() => {
    const id = setInterval(() => setRemaining(Math.max(0, target - Date.now())), 250);
    return () => clearInterval(id);
  }, [target]);
  return { remaining, total: totalRef.current };
}

export function Checkout({
  hold, seats, onPaid, onExpire, onBack,
}: {
  hold: Hold;
  seats: Seat[];
  onPaid: (b: Booking) => void;
  onExpire: () => void;
  onBack: () => void;
}) {
  const { reduced } = useMotionPrefs();
  const { remaining, total } = useCountdown(hold.expires_at);
  const [paying, setPaying] = useState(false);
  const [err, setErr] = useState("");

  const tone = countdownTone(remaining, total);
  const mm = Math.floor(remaining / 60000);
  const ss = Math.floor((remaining % 60000) / 1000);
  const seatById = useMemo(() => new Map(seats.map((s) => [s.id, s])), [seats]);

  // Fire expiry exactly once when the clock hits zero.
  const expiredRef = useRef(false);
  useEffect(() => {
    if (remaining <= 0 && !expiredRef.current) {
      expiredRef.current = true;
      onExpire();
    }
  }, [remaining, onExpire]);

  async function pay() {
    setErr(""); setPaying(true);
    try {
      const co = await api.checkout(hold.id);
      // Offline dev → fake session id → simulate the webhook. Real Stripe →
      // redirect to the hosted Checkout page (the webhook confirms on return).
      if (co.session_id.startsWith("cs_test_fake_")) {
        const booking = await api.devConfirm(hold.id);
        onPaid(booking);
      } else {
        window.location.href = co.checkout_url;
      }
    } catch (x: any) {
      if (x?.status === 410) { setErr("Your hold expired — please reselect your seats."); setTimeout(onExpire, 1200); }
      else setErr("Payment couldn't start. Please try again.");
      setPaying(false);
    }
  }

  return (
    <motion.div variants={stagger(0.07)} initial="hidden" animate="show"
      className="mx-auto grid max-w-4xl gap-6 md:grid-cols-[1fr_1fr]">
      {/* countdown — the tension beat */}
      <motion.div variants={riseIn}
        className="flex flex-col items-center justify-center rounded-3xl border border-white/10 bg-black/30 p-8 text-center">
        <div className="text-xs uppercase tracking-[0.3em] text-white/40">Seats held for</div>
        <div className="relative mt-6 grid place-items-center" style={{ width: RING, height: RING }}>
          <svg width={RING} height={RING} className="-rotate-90">
            <circle cx={RING / 2} cy={RING / 2} r={R} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={8} />
            <motion.circle
              cx={RING / 2} cy={RING / 2} r={R} fill="none" stroke={tone.color} strokeWidth={8} strokeLinecap="round"
              strokeDasharray={C}
              animate={{ strokeDashoffset: C * (1 - tone.frac) }}
              transition={{ duration: 0.3, ease: "linear" }}
              style={{ filter: `drop-shadow(0 0 6px ${tone.glow})` }}
            />
          </svg>
          <motion.div
            className="absolute font-mono text-4xl font-bold tabular-nums"
            style={{ color: tone.color }}
            animate={reduced ? undefined : (tone.urgent ? { scale: [1, 1.12, 1] } : { scale: 1 })}
            transition={tone.urgent ? { repeat: Infinity, duration: 0.8 } : springs.soft}
          >
            {mm}:{ss.toString().padStart(2, "0")}
          </motion.div>
        </div>
        <p className="mt-6 max-w-[16rem] text-sm text-white/45">
          {tone.urgent ? "Hurry — your seats are about to be released!" : "Complete payment before the timer runs out to keep your seats."}
        </p>
      </motion.div>

      {/* order summary + pay */}
      <motion.div variants={riseIn} className="rounded-3xl border border-white/10 bg-white/5 p-8 backdrop-blur-xl">
        <div className="text-lg font-bold">Order summary</div>
        <ul className="mt-4 space-y-2">
          {hold.items.map((it) => {
            const s = seatById.get(it.seat_id);
            return (
              <li key={it.seat_id} className="flex items-center justify-between rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm">
                <span className="text-white/80">{s ? `${s.section} · ${s.seat_number}` : `Seat ${it.seat_id}`}</span>
                <span className="font-medium">{inr(it.price_cents)}</span>
              </li>
            );
          })}
        </ul>
        <div className="mt-4 flex items-center justify-between border-t border-white/10 pt-4">
          <span className="text-white/50">Total</span>
          <span className="text-xl font-bold">{inr(hold.total_cents)}</span>
        </div>

        {err && <div className="mt-3 rounded-lg bg-red-500/15 px-3 py-2 text-sm text-red-300">{err}</div>}

        <motion.button
          onClick={pay} disabled={paying || remaining <= 0}
          whileHover={reduced || paying ? undefined : { scale: 1.02 }}
          whileTap={reduced || paying ? undefined : { scale: 0.98 }}
          transition={springs.snappy}
          className="mt-5 w-full rounded-xl bg-cyan-400 py-3.5 font-semibold text-black transition hover:bg-cyan-300 disabled:opacity-40"
        >
          {paying ? "Processing…" : `Pay ${inr(hold.total_cents)}`}
        </motion.button>
        <button onClick={onBack} disabled={paying}
          className="mt-3 w-full rounded-xl border border-white/10 py-2.5 text-sm text-white/60 hover:bg-white/5 disabled:opacity-40">
          Back to seat map
        </button>
        <p className="mt-4 text-center text-[11px] text-white/30">Test mode — no real card is charged.</p>
      </motion.div>
    </motion.div>
  );
}
