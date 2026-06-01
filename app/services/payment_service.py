"""Stripe integration (test mode) with an offline 'fake' fallback.

If STRIPE_SECRET_KEY is set, real Stripe Checkout Sessions + signature-verified
webhooks + refunds are used. If not (offline dev / CI), a deterministic fake
mode lets the whole select->hold->pay->confirm flow run and be tested without
network or keys. Idempotency-Key is sent on charge-creating calls so a retried
request never double-charges.
"""
from __future__ import annotations

import json

from ..config import settings

try:  # stripe is optional in offline mode
    import stripe  # type: ignore
except Exception:  # pragma: no cover
    stripe = None  # type: ignore


def stripe_enabled() -> bool:
    return bool(settings.stripe_secret_key) and stripe is not None


def _client():
    stripe.api_key = settings.stripe_secret_key
    return stripe


def create_checkout_session(hold_id: int, line_items: list[tuple[str, int]]) -> tuple[str, str]:
    """Create a Checkout Session for a hold. Returns (session_id, checkout_url).
    Idempotency-Key is keyed on the hold so a double-click can't open two
    sessions / charge twice. line_items: list of (label, amount_cents)."""
    success = settings.checkout_success_url.replace("{HOLD_ID}", str(hold_id))
    cancel = settings.checkout_cancel_url.replace("{HOLD_ID}", str(hold_id))

    if not stripe_enabled():
        # Deterministic fake: same hold -> same session id (idempotent).
        sid = f"cs_test_fake_{hold_id}"
        return sid, f"{success}&session_id={sid}"

    s = _client().checkout.Session.create(
        mode="payment",
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": settings.currency,
                    "unit_amount": amount,
                    "product_data": {"name": label},
                },
            }
            for (label, amount) in line_items
        ],
        success_url=success,
        cancel_url=cancel,
        client_reference_id=str(hold_id),
        metadata={"hold_id": str(hold_id)},
        idempotency_key=f"checkout-{hold_id}",
    )
    return s.id, s.url


def verify_webhook(payload: bytes, sig_header: str | None) -> dict:
    """Verify + parse a Stripe webhook. In offline mode (no webhook secret) the
    payload is trusted and parsed as JSON (dev only)."""
    if settings.stripe_webhook_secret and stripe is not None:
        event = _client().Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
        return event if isinstance(event, dict) else event.to_dict()
    return json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)


def refund(payment_intent_id: str | None) -> None:
    """Refund a captured payment (used when a hold lapsed before the webhook
    arrived). Idempotency-Key prevents a double refund on retry."""
    if not payment_intent_id:
        return
    if not stripe_enabled():
        return  # offline dev: nothing to refund
    _client().Refund.create(
        payment_intent=payment_intent_id,
        idempotency_key=f"refund-{payment_intent_id}",
    )
