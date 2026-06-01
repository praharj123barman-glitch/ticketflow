import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api, type Booking, type EventDetail, type Seat } from "./api";
import { Confirmation } from "./Confirmation";
import { springs } from "./motion";

/**
 * Landing spot after Stripe Checkout. On success we poll for the booking the
 * webhook creates server-side (it may arrive a beat after the browser redirect),
 * then show the normal Confirmation scene. On cancel we explain the hold is still
 * ticking and offer a way back.
 */
export function BookingReturn({
  kind, holdId, onDone,
}: {
  kind: "success" | "cancel";
  holdId: number;
  onDone: () => void;
}) {
  const [booking, setBooking] = useState<Booking | null>(null);
  const [event, setEvent] = useState<EventDetail | null>(null);
  const [seats, setSeats] = useState<Seat[]>([]);
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    if (kind !== "success" || Number.isNaN(holdId)) return;
    let stop = false;
    let tries = 0;
    const tick = async () => {
      const b = await api.bookingByHold(holdId);
      if (stop) return;
      if (b) {
        const [detail, seatList] = await Promise.all([
          api.event(b.event_id).catch(() => null),
          api.seats(b.event_id).catch(() => [] as Seat[]),
        ]);
        if (stop) return;
        setEvent(detail); setSeats(seatList); setBooking(b);
        return;
      }
      if (++tries >= 16) { setTimedOut(true); return; }   // ~24s of polling
      setTimeout(tick, 1500);
    };
    tick();
    return () => { stop = true; };
  }, [kind, holdId]);

  if (kind === "success" && booking) {
    return (
      <div className="bg-aurora min-h-screen px-4 py-16 text-white">
        <Confirmation booking={booking} event={event} seats={seats} onDone={onDone} />
      </div>
    );
  }

  return (
    <div className="bg-aurora flex min-h-screen items-center justify-center p-4 text-white">
      <motion.div
        initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={springs.soft}
        className="w-full max-w-md rounded-2xl border border-white/10 bg-white/5 p-8 text-center backdrop-blur-xl"
      >
        {kind === "cancel" ? (
          <>
            <div className="text-2xl">↩️</div>
            <div className="mt-3 text-xl font-bold">Payment cancelled</div>
            <p className="mt-2 text-sm text-white/55">No charge was made. Your seats may still be held for a few minutes — head back and try again before they're released.</p>
          </>
        ) : timedOut ? (
          <>
            <div className="text-2xl">✅</div>
            <div className="mt-3 text-xl font-bold">Payment received</div>
            <p className="mt-2 text-sm text-white/55">We're finalizing your booking and emailing your tickets. They'll appear under “My bookings” shortly.</p>
          </>
        ) : (
          <>
            <motion.div
              className="mx-auto h-12 w-12 rounded-full border-2 border-cyan-400/30 border-t-cyan-400"
              animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: "linear" }}
            />
            <div className="mt-5 text-xl font-bold">Confirming your booking…</div>
            <p className="mt-2 text-sm text-white/55">Payment went through — we're issuing your e-tickets.</p>
          </>
        )}
        <button onClick={onDone} className="mt-6 rounded-full border border-white/15 bg-white/5 px-6 py-2.5 text-sm font-semibold hover:bg-white/10">
          Back to events
        </button>
      </motion.div>
    </div>
  );
}
