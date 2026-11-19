"""Single-origin entrypoint for hosts without nginx in front (e.g. Render).

On AWS, nginx routes traffic (see deploy/nginx.prod.conf). This module rebuilds
the same routing inside one ASGI app, so one web service serves everything:

  /api/*                        -> the TicketFlow API (mounted: docs at /api/docs)
  /e/*, /og/*, /sitemap.xml,
  /robots.txt                   -> server-rendered share pages (backend, unprefixed)
  everything else               -> the React build, with SPA fallback to index.html

The AWS deployment keeps using nginx + `app.main:app`; nothing here changes it.
"""
from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from .main import app as api_app
from .routers import pages

DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


class SPAStaticFiles(StaticFiles):
    """Serve built assets; unknown paths (client-side routes) get index.html."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Starlette does not run a mounted sub-app's lifespan, so run the API's here:
    # it starts the hold sweeper, the waitroom admitter and the realtime broker.
    async with api_app.router.lifespan_context(api_app):
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(pages.router)  # share pages live at the root, as with nginx
app.mount("/api", api_app)
if DIST_DIR.is_dir():
    app.mount("/", SPAStaticFiles(directory=DIST_DIR, html=True), name="spa")
