"""Public, shareable, crawler-friendly pages.

A SPA can't be read by WhatsApp/LinkedIn/Twitter crawlers (they don't run JS), so
the share URL `/e/{id}` is served *server-side* with per-event OpenGraph/Twitter
meta + a real <title>, then bounces humans to the SPA (`/?e={id}`). Crawlers read
the meta and never follow the redirect, so links preview with the right title,
description, and image. Also serves a dynamically-rendered OG image, a sitemap,
and robots.txt.

In production nginx routes `/e/`, `/og/`, `/sitemap.xml`, `/robots.txt` to this
backend (everything else is the SPA); in local vite dev the SPA fallback serves
`/e/{id}` directly (meta only matters for prod crawlers).
"""
from __future__ import annotations

import datetime as dt
import html
import io

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Event, EventStatus, Venue
from ..services import events_service

router = APIRouter(tags=["pages"], include_in_schema=False)


def _base() -> str:
    return settings.public_base_url.rstrip("/")


def _event_meta(event: Event, venue: Venue | None, available: int, capacity: int) -> dict:
    when = event.starts_at.strftime("%a, %d %b %Y · %H:%M")
    place = f"{venue.name}, {venue.city}" if venue else "Live event"
    desc = (event.description or f"{place} · {when}.").strip()
    desc = f"{desc} · {available} of {capacity} seats available — pick yours live on an interactive map."
    return {"title": f"{event.name} — TicketFlow", "description": desc, "place": place, "when": when}


@router.get("/e/{event_id}", response_class=HTMLResponse)
def event_share_page(event_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    event = db.get(Event, event_id)
    if event is None or event.status != EventStatus.PUBLISHED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Event not found")

    capacity, available = events_service.capacity_and_available(db, event_id)
    meta = _event_meta(event, event.venue, available, capacity)
    base = _base()
    url = f"{base}/e/{event_id}"
    img = f"{base}/og/event/{event_id}.png"
    spa = f"/?e={event_id}"

    e = html.escape
    doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{e(meta['title'])}</title>
  <meta name="description" content="{e(meta['description'])}" />
  <link rel="canonical" href="{e(url)}" />

  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="TicketFlow" />
  <meta property="og:title" content="{e(meta['title'])}" />
  <meta property="og:description" content="{e(meta['description'])}" />
  <meta property="og:url" content="{e(url)}" />
  <meta property="og:image" content="{e(img)}" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />

  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{e(meta['title'])}" />
  <meta name="twitter:description" content="{e(meta['description'])}" />
  <meta name="twitter:image" content="{e(img)}" />

  <meta http-equiv="refresh" content="0; url={e(spa)}" />
  <script>window.location.replace({spa!r});</script>
  <style>
    body{{margin:0;background:#0a0a12;color:#cbd5e1;font-family:system-ui,sans-serif;
      display:grid;place-items:center;height:100vh;text-align:center}}
    a{{color:#22d3ee}}
  </style>
</head>
<body>
  <div>
    <div style="font-size:1.4rem;font-weight:700;color:#fff">🎟️ {e(event.name)}</div>
    <p>Taking you to the live seat map…</p>
    <p><a href="{e(spa)}">Continue to {e(meta['place'])} →</a></p>
  </div>
</body>
</html>"""
    return HTMLResponse(doc)


@router.get("/og/event/{event_id}.png")
def event_og_image(event_id: int, db: Session = Depends(get_db)) -> Response:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Event not found")
    capacity, available = events_service.capacity_and_available(db, event_id)
    png = _render_og(event, event.venue, available, capacity)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=300"})


@router.get("/sitemap.xml")
def sitemap(db: Session = Depends(get_db)) -> Response:
    base = _base()
    events = db.execute(
        select(Event).where(Event.status == EventStatus.PUBLISHED).order_by(Event.id)
    ).scalars().all()
    today = dt.date.today().isoformat()
    urls = [f"  <url><loc>{base}/</loc><changefreq>daily</changefreq></url>"]
    for ev in events:
        urls.append(
            f"  <url><loc>{base}/e/{ev.id}</loc>"
            f"<lastmod>{today}</lastmod><changefreq>hourly</changefreq></url>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls) + "\n</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml")


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots() -> PlainTextResponse:
    return PlainTextResponse(f"User-agent: *\nAllow: /\nSitemap: {_base()}/sitemap.xml\n")


# ---- OG image rendering (Pillow) ----
def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    candidates = (
        ["arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        ["arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:3]


def _render_og(event: Event, venue: Venue | None, available: int, capacity: int) -> bytes:
    from PIL import Image, ImageDraw

    W, H = 1200, 630
    img = Image.new("RGB", (W, H), (10, 10, 18))
    d = ImageDraw.Draw(img)

    # subtle diagonal brand gradient (cyan -> indigo) baked into the background
    for y in range(H):
        t = y / H
        r = int(10 + 8 * (1 - t)); g = int(14 + 30 * (1 - t)); b = int(22 + 60 * (1 - t))
        d.line([(0, y), (W, y)], fill=(r, g, b))
    d.ellipse([-160, -160, 240, 240], fill=(13, 30, 50))
    d.ellipse([W - 260, H - 220, W + 120, H + 160], fill=(20, 16, 44))

    pad = 80
    # small drawn "ticket" mark + wordmark (no emoji — the base fonts have no
    # emoji glyphs, which would render as a tofu box on the share card).
    d.rounded_rectangle([pad, 74, pad + 26, 100], radius=5, fill=(34, 211, 238))
    d.text((pad + 40, 70), "TICKETFLOW", font=_font(34, bold=True), fill=(34, 211, 238))

    name_font = _font(76, bold=True)
    y = 180
    for line in _wrap(d, event.name, name_font, W - 2 * pad):
        d.text((pad, y), line, font=name_font, fill=(255, 255, 255))
        y += 92

    sub_font = _font(38)
    when = event.starts_at.strftime("%A, %d %B %Y")  # date only — avoids UTC-time confusion on the card
    place = f"{venue.name}, {venue.city}" if venue else "Live event"
    d.text((pad, y + 14), place, font=sub_font, fill=(203, 213, 225))
    d.text((pad, y + 70), when, font=sub_font, fill=(148, 163, 184))

    # availability pill-free footer line (kept as plain text per design rules)
    foot = _font(34, bold=True)
    label = f"{available} of {capacity} seats live · pick yours on an interactive map"
    d.text((pad, H - 90), label, font=foot, fill=(34, 211, 238))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
