"""FastAPI-app: ruter, sikkerhet og bakgrunnsjobb."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import time
from collections import defaultdict, deque
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .config import Settings, load_settings
from .fetch import CalendarStore

log = logging.getLogger("besok")
STATIC = Path(__file__).parent / "static"

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "Cache-Control": "no-store",
}


class RateLimiter:
    """Glidende vindu per nøkkel, i minnet."""

    def __init__(self, limit: int, window_s: float):
        self.limit = limit
        self.window = window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self.hits[key]
        while q and q[0] <= now - self.window:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        return len(self._prune(key, time.monotonic())) >= self.limit

    def hit(self, key: str) -> bool:
        """Registrer et treff. Returnerer True hvis grensen er overskredet."""
        now = time.monotonic()
        q = self._prune(key, now)
        if len(q) >= self.limit:
            return True
        q.append(now)
        return False


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "ukjent"


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def create_app(settings: Settings | None = None, store: CalendarStore | None = None) -> FastAPI:
    settings = settings or load_settings()
    store = store or CalendarStore(settings)
    api_limiter = RateLimiter(60, 60)
    admin_fail_limiter = RateLimiter(10, 3600)
    basic = HTTPBasic(auto_error=False)

    async def refresh_loop() -> None:
        while True:
            try:
                await store.refresh()
            except Exception as exc:  # skal aldri drepe løkka
                log.error("Uventet feil i henting: %s", type(exc).__name__)
            await asyncio.sleep(settings.refresh_minutes * 60)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(refresh_loop()) if settings.start_background else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.url.path.startswith("/api/") and api_limiter.hit(client_ip(request)):
            resp = JSONResponse({"detail": "For mange forespørsler"}, status_code=429)
        else:
            resp = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            resp.headers[k] = v
        return resp

    # ---------- tilgangskontroll ----------

    def require_visitor(k: str | None = None) -> None:
        if not k or not _same(k, settings.visitor_key):
            raise HTTPException(status_code=404, detail="Not Found")

    def require_admin(request: Request, creds: HTTPBasicCredentials | None = Depends(basic)) -> None:
        ip = client_ip(request)
        if admin_fail_limiter.blocked(ip):
            raise HTTPException(status_code=429, detail="For mange mislykkede innlogginger")
        ok = (
            creds is not None
            and _same(creds.username, settings.admin_user)
            and _same(creds.password, settings.admin_password)
        )
        if not ok:
            admin_fail_limiter.hit(ip)
            raise HTTPException(
                status_code=401, detail="Innlogging kreves", headers={"WWW-Authenticate": 'Basic realm="besok-admin"'}
            )

    # ---------- besøkende ----------

    @app.get("/", dependencies=[Depends(require_visitor)])
    async def index():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    @app.get("/static/modes.js")
    async def modes_js():
        return FileResponse(STATIC / "modes.js", media_type="text/javascript")

    @app.get("/api/nights", dependencies=[Depends(require_visitor)])
    async def api_nights():
        return {
            "updated_at": store.updated_at,
            "contact": settings.contact_email,
            "nights": store.visitor_nights(),
        }

    # ---------- admin ----------

    @app.get("/admin", dependencies=[Depends(require_admin)])
    async def admin():
        return FileResponse(STATIC / "admin.html", media_type="text/html")

    @app.get("/api/admin/nights", dependencies=[Depends(require_admin)])
    async def api_admin_nights(request: Request):
        # spec bruker ?from=&to= (to er eksklusiv); "from" er reservert i Python, så les query direkte
        q = request.query_params
        today = store.today()
        try:
            first = date.fromisoformat(q.get("from")) if q.get("from") else today.replace(day=1)
            last = date.fromisoformat(q.get("to")) if q.get("to") else (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Ugyldig dato, bruk ÅÅÅÅ-MM-DD")
        count = (last - first).days
        if not 0 < count <= 400:
            raise HTTPException(status_code=400, detail="Ugyldig periode")
        return {
            "updated_at": store.updated_at,
            "today": today.isoformat(),
            "sources": store.source_status(),
            "nights": store.nights(first, count, with_reasons=True),
        }

    @app.post("/api/admin/refresh", dependencies=[Depends(require_admin)])
    async def api_admin_refresh():
        await store.refresh()
        return {"updated_at": store.updated_at, "sources": store.source_status()}

    # ---------- diverse ----------

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "last_success": store.last_success()}

    @app.get("/robots.txt")
    async def robots():
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    return app


def build() -> FastAPI:
    """Inngangspunkt for uvicorn (--factory)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
