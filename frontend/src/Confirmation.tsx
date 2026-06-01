import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api, type Booking, type EventDetail, type Seat } from "./api";
import { Confetti } from "./Confetti";
import { riseIn, springs, stagger, ticketFlip, useMotionPrefs } from "./motion";

const inr = (cents: number) => `₹${(cents / 100).toLocaleString("en-IN")}`;

/** The payoff: confetti fires, the e-ticket flips in with its QR. */
export function Confirmation({
  booking, event, seats, onDone,
}: {
  booking: Booking;
  event: EventDetail | null;
  seats: Seat[];
  onDone: () => void;
}) {
  const { reduced } = useMotionPrefs();
  const seatById = new Map(seats.map((s) => [s.id, s]));
  const firstTicket = booking.tickets?.[0];
  const [qr, setQr] = useState<string>("");

  useEffect(() => {
    if (firstTicket) api.ticketQr(firstTicket.code).then(setQr).catch(() => {});
  }, [firstTicket]);

  const seatLabels = booking.items
    .map((it) => { const s = seatById.get(it.seat_id); return s ? `${s.section} ${s.seat_number}` : `#${it.seat_id}`; })
    .join(" · ");
  const date = event ? new Date(event.starts_at) : null;

  return (
    <div className="relative">
      <Confetti />
      <motion.div variants={stagger(0.1)} initial="hidden" animate="show" className="mx-auto max-w-md text-center">
        <motion.div variants={riseIn}
          className="mx-auto grid h-16 w-16 place-items-center rounded-full bg-emerald-500/20 text-3xl"
          animate={reduced ? undefined : { scale: [0.6, 1.15, 1] }} transition={springs.pop}>
          ✓
        </motion.div>
        <motion.h2 variants={riseIn} className="mt-4 text-3xl font-extrabold tracking-tight">You're going!</motion.h2>
        <motion.p variants={riseIn} className="mt-1 text-white/55">Booking #{booking.id} confirmed · {inr(booking.total_cents)}</motion.p>

        {/* the e-ticket — flips in edge-on */}
        <motion.div className="mt-8 [perspective:1200px]" variants={riseIn}>
          <motion.div
            variants={reduced ? riseIn : ticketFlip}
            className="relative mx-auto w-full max-w-sm overflow-hidden rounded-2xl border border-white/15 bg-gradient-to-br from-white/10 to-white/5 p-6 text-left shadow-2xl backdrop-blur-xl"
            style={{ transformStyle: "preserve-3d" }}
          >
            {/* perforation notches */}
            <span className="absolute -left-3 top-1/2 h-6 w-6 -translate-y-1/2 rounded-full bg-[#0a0a12]" />
            <span className="absolute -right-3 top-1/2 h-6 w-6 -translate-y-1/2 rounded-full bg-[#0a0a12]" />

            <div className="text-[10px] uppercase tracking-[0.3em] text-cyan-300/80">E-Ticket</div>
            <div className="mt-1 text-xl font-bold leading-tight">{event?.name ?? "Your event"}</div>
            <div className="mt-0.5 text-sm text-white/55">{event?.venue?.name}{event?.venue?.city ? `, ${event.venue.city}` : ""}</div>

            <div className="mt-4 flex items-end justify-between gap-4 border-t border-dashed border-white/15 pt-4">
              <div className="min-w-0">
                <div className="text-[10px] uppercase tracking-widest text-white/35">Seats</div>
                <div className="truncate text-sm font-semibold">{seatLabels}</div>
                {date && (
                  <>
                    <div className="mt-2 text-[10px] uppercase tracking-widest text-white/35">When</div>
                    <div className="text-sm font-semibold">
                      {date.toLocaleDateString("en-IN", { day: "numeric", month: "short" })} · {date.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}
                    </div>
                  </>
                )}
              </div>
              {/* QR */}
              <motion.div
                className="shrink-0 rounded-lg bg-white p-1.5"
                initial={reduced ? false : { opacity: 0, scale: 0.7 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 0.5, ...springs.pop }}
              >
                {qr
                  ? <div className="h-24 w-24 [&>svg]:h-full [&>svg]:w-full" dangerouslySetInnerHTML={{ __html: qr }} />
                  : <div className="h-24 w-24 animate-pulse rounded bg-black/10" />}
              </motion.div>
            </div>
            {firstTicket && <div className="mt-3 font-mono text-[10px] tracking-wider text-white/35">{firstTicket.code}</div>}
          </motion.div>
        </motion.div>

        <motion.p variants={riseIn} className="mt-5 text-xs text-white/40">
          {booking.tickets && booking.tickets.length > 1
            ? `${booking.tickets.length} tickets sent to your email · scan at the gate`
            : "Sent to your email · scan at the gate"}
        </motion.p>

        <motion.button variants={riseIn} onClick={onDone}
          whileHover={reduced ? undefined : { scale: 1.03 }} whileTap={reduced ? undefined : { scale: 0.97 }}
          className="mt-6 rounded-full border border-white/15 bg-white/5 px-6 py-3 text-sm font-semibold hover:bg-white/10">
          Back to event
        </motion.button>
      </motion.div>
    </div>
  );
}
