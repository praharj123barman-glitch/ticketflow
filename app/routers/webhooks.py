"""Stripe webhook → CONFIRM. This is the only place a hold becomes a booking.

Idempotency is enforced in booking_service.confirm_hold (processed-events ledger
keyed by the Stripe event id, plus a UNIQUE bookings.hold_id), so duplicate
webhook deliveries are safe no-ops. If the hold lapsed before payment settled,
we refund and do NOT grant seats.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import booking_service, payment_service

logger = logging.getLogger("ticketflow.webhooks")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    try:
        event = payment_service.verify_webhook(payload, sig)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature")

    event_type = event.get("type")
    if event_type != "checkout.session.completed":
        return {"status": "ignored", "type": event_type}

    obj = event.get("data", {}).get("object", {})
    raw_hold_id = (obj.get("metadata") or {}).get("hold_id") or obj.get("client_reference_id")
    if raw_hold_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Missing hold reference")
    hold_id = int(raw_hold_id)
    payment_intent = obj.get("payment_intent")
    event_id = event.get("id")

    try:
        result = await run_in_threadpool(
            booking_service.confirm_hold, db, hold_id, payment_intent, event_id
        )
    except booking_service.HoldNotFoundError:
        # Unknown hold — refund to be safe (money captured but nothing to grant).
        await run_in_threadpool(payment_service.refund, payment_intent)
        return {"status": "refunded", "reason": "hold_not_found"}

    if result.outcome == booking_service.REFUND_REQUIRED:
        await run_in_threadpool(payment_service.refund, payment_intent)
        logger.info("refunded hold %s — lapsed before payment settled", hold_id)
        return {"status": "refunded", "reason": "hold_expired"}

    return {
        "status": result.outcome.lower(),
        "booking_id": result.booking.id if result.booking else None,
    }
