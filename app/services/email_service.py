"""Transactional email with a dev/test backend.

If SMTP settings are configured, mail is sent via SMTP. Otherwise (dev/CI) the
message is logged and appended to an in-memory outbox so it can be inspected in
tests. Sending is always best-effort — a mail failure must never break a booking.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from ..config import settings

logger = logging.getLogger("ticketflow.email")

# Dev backend: last-N sent messages, inspectable by tests.
outbox: list[dict] = []


def send_booking_confirmation(to_email: str, event_name: str, booking_id: int, ticket_codes: list[str]) -> None:
    subject = f"Your tickets for {event_name} (booking #{booking_id})"
    body = (
        f"Thanks for your booking!\n\nEvent: {event_name}\nBooking: #{booking_id}\n"
        f"Tickets: {len(ticket_codes)}\n"
        + "\n".join(f"  - {c}" for c in ticket_codes)
        + "\n\nShow the QR code at the entrance.\n"
    )
    message = {"to": to_email, "subject": subject, "body": body}

    try:
        if settings.smtp_host:
            msg = EmailMessage()
            msg["From"] = settings.email_from
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.set_content(body)
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as s:
                if settings.smtp_user:
                    s.starttls()
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
            logger.info("sent confirmation email to %s (booking %s)", to_email, booking_id)
        else:
            outbox.append(message)
            logger.info("[dev-email] to=%s subject=%s tickets=%d", to_email, subject, len(ticket_codes))
    except Exception:
        logger.exception("failed to send confirmation email to %s", to_email)
