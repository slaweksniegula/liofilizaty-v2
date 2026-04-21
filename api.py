"""
api.py — cienka warstwa REST API wokół istniejących scraperów.

Wystawia endpointy dla n8n (i innych klientów):

    GET  /                      — health check
    GET  /products              — lista produktów z config.yaml
    GET  /shops                 — lista włączonych sklepów
    GET  /prices/today          — ceny z dzisiaj (wszystkie produkty × sklepy)
    GET  /prices/history?days=N — historia N ostatnich dni
    GET  /deals                 — TYLKO produkty które dziś są okazją
    POST /scrape                — uruchomienie scrapingu (w tle, async)
    POST /report/pdf            — generuje PDF i zwraca binarnie
    GET  /report/latest         — zwraca ostatni PDF binarnie

Wszystkie scrapery i logika już istnieją w:
  - scraper.py  (funkcja run)
  - storage.py  (klasa PriceDB)
  - report.py   (build_pdf, analyze_today)

Ten plik to czysta warstwa HTTP — żadna logika biznesowa tu nie wchodzi.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from pathlib import Path
from typing import Optional

import yaml
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from report import analyze_today, build_pdf
from scraper import run as run_scraper
from storage import PriceDB

# ──────────────────────────────────────────────────────── konfiguracja

ROOT = Path(__file__).parent
# Ścieżki konfigurowalne przez env — dzięki temu w Dockerze wolumen z danymi
# siedzi w /app/data, a lokalnie po prostu w projekcie.
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT)))
DB_PATH = DATA_DIR / "prices.db"
REPORTS_DIR = DATA_DIR / "raporty"
CONFIG_PATH = ROOT / "config.yaml"

# API key — jeśli ustawiony, każde żądanie musi mieć nagłówek X-API-Key.
# Puste = bez zabezpieczenia (OK do lokalnego testu; NIE do publicznego deploya).
API_KEY = os.getenv("API_KEY", "")

REPORTS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("api")

# ──────────────────────────────────────────────────────── aplikacja

app = FastAPI(
    title="Liofilizaty Tracker API",
    description="Scrapery cen liofilizatów + generator raportów PDF.",
    version="2.0.0",
)

# CORS — żeby n8n Cloud / inne serwisy mogły wołać
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Middleware: API key check (jeśli ustawiony)
@app.middleware("http")
async def verify_api_key(request, call_next):
    # Pomijamy health check i docs
    if request.url.path in ("/", "/docs", "/openapi.json", "/redoc"):
        return await call_next(request)
    if API_KEY and request.headers.get("X-API-Key") != API_KEY:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing X-API-Key header"},
        )
    return await call_next(request)


def _load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _db() -> PriceDB:
    return PriceDB(DB_PATH)


# ──────────────────────────────────────────────────────── endpointy

@app.get("/")
def root():
    """Health check — używane przez uptime monitoring i smoke test."""
    return {
        "status": "ok",
        "service": "liofilizaty-tracker",
        "version": "2.0.0",
        "db_exists": DB_PATH.exists(),
        "reports_dir": str(REPORTS_DIR),
    }


@app.get("/products")
def list_products():
    """Lista produktów z config.yaml."""
    cfg = _load_config()
    return {"products": cfg["products"]}


@app.get("/shops")
def list_shops():
    """Lista sklepów — z flagą `enabled`."""
    cfg = _load_config()
    return {"shops": cfg["shops"]}


@app.get("/prices/today")
def prices_today():
    """
    Ceny z dzisiaj per produkt, per sklep.
    Odpowiedź jest gotowa do wrzucenia do n8n bez dalszego parsowania.
    """
    cfg = _load_config()
    db = _db()
    today = dt.date.today()

    result = []
    for prod in cfg["products"]:
        pid = prod["id"]
        by_shop = db.latest_by_shop(pid, today)
        shops = []
        for shop_id, row in by_shop.items():
            shop_meta = cfg["shops"].get(shop_id, {})
            shops.append({
                "shop_id": shop_id,
                "shop_name": shop_meta.get("display_name", shop_id),
                "price_pln": row["price_pln"],
                "available": bool(row["available"]),
                "url": row["product_url"],
                "title": row["product_title"],
            })
        result.append({
            "product_id": pid,
            "product_name": prod["name"],
            "brand": prod.get("brand"),
            "weight_g": prod.get("weight_g"),
            "shops": shops,
        })
    return {"date": today.isoformat(), "products": result}


@app.get("/prices/history")
def prices_history(days: int = Query(15, ge=1, le=90)):
    """Pełna historia ostatnich N dni, wszystkie produkty, wszystkie sklepy."""
    cfg = _load_config()
    db = _db()
    today = dt.date.today()

    result = []
    for prod in cfg["products"]:
        pid = prod["id"]
        rows = db.history(pid, days, today=today)
        series: dict[str, list] = {}
        for r in rows:
            series.setdefault(r["shop_id"], []).append({
                "date": r["date"],
                "price_pln": r["price_pln"],
                "available": bool(r["available"]),
            })
        result.append({
            "product_id": pid,
            "product_name": prod["name"],
            "series_by_shop": series,
        })
    return {"days": days, "as_of": today.isoformat(), "products": result}


@app.get("/deals")
def deals(threshold_pct: float = Query(None)):
    """
    Produkty które DZIŚ są okazją (cena < (1 - threshold/100) * średnia 7-dniowa).
    Jeśli threshold_pct nie podano, używamy wartości z config.yaml.
    """
    cfg = _load_config()
    db = _db()
    today = dt.date.today()
    threshold = threshold_pct if threshold_pct is not None else float(
        cfg["report"]["deal_threshold_pct"]
    )
    history_days = int(cfg["report"]["history_days"])

    deals_list = []
    for prod in cfg["products"]:
        pid = prod["id"]
        rows = db.history(pid, history_days, today=today)
        a = analyze_today(rows, cfg["shops"], today, threshold)
        if a["is_deal"] and a["cheapest_price"] is not None and a["avg_7d"]:
            shop_meta = cfg["shops"].get(a["cheapest_shop"], {})
            discount = (a["avg_7d"] - a["cheapest_price"]) / a["avg_7d"] * 100
            today_info = a["today_by_shop"].get(a["cheapest_shop"], {})
            deals_list.append({
                "product_id": pid,
                "product_name": prod["name"],
                "brand": prod.get("brand"),
                "shop_id": a["cheapest_shop"],
                "shop_name": shop_meta.get("display_name", a["cheapest_shop"]),
                "price_pln": a["cheapest_price"],
                "avg_7d_pln": a["avg_7d"],
                "discount_pct": round(discount, 1),
                "url": today_info.get("url"),
            })

    deals_list.sort(key=lambda d: d["discount_pct"], reverse=True)
    return {
        "date": today.isoformat(),
        "threshold_pct": threshold,
        "count": len(deals_list),
        "deals": deals_list,
    }


@app.post("/scrape")
def trigger_scrape(background_tasks: BackgroundTasks):
    """
    Uruchamia scraping w tle. Zwraca natychmiast (202 Accepted).
    n8n może potem czekać X minut i odpytać /prices/today.

    Jeśli chcesz synchroniczny scrape (czekanie aż skończy), wywołaj /scrape/sync.
    """
    background_tasks.add_task(
        _scrape_with_cwd, dry_run=False, only_shops=[], only_product=None,
    )
    return {
        "status": "started",
        "started_at": dt.datetime.now().isoformat(timespec="seconds"),
        "hint": "Odczekaj ok. 2 min i zapytaj /prices/today lub /deals",
    }


@app.post("/scrape/sync")
def trigger_scrape_sync():
    """Synchroniczny scraping — blokuje dopóki się nie skończy. Dla debugowania."""
    rc = _scrape_with_cwd(dry_run=False, only_shops=[], only_product=None)
    return {"status": "ok" if rc == 0 else "error", "return_code": rc}


@app.post("/report/pdf")
def generate_pdf():
    """
    Generuje raport PDF na dziś.
    Zwraca ścieżkę i URL do pobrania (plik jest w wolumenie, n8n go pobierze przez /report/latest).
    """
    cfg = _load_config()
    db = _db()
    today = dt.date.today()

    out = REPORTS_DIR / f"{today.isoformat()}.pdf"
    build_pdf(out, cfg, db, today)

    # Kopia jako latest.pdf
    latest = REPORTS_DIR / "latest.pdf"
    latest.write_bytes(out.read_bytes())

    return {
        "status": "ok",
        "date": today.isoformat(),
        "filename": out.name,
        "size_bytes": out.stat().st_size,
        "download_url": "/report/latest",
    }


@app.get("/report/latest")
def download_latest():
    """Zwraca PDF `latest.pdf` binarnie. n8n używa tego do Gmail/Telegram attachment."""
    latest = REPORTS_DIR / "latest.pdf"
    if not latest.exists():
        raise HTTPException(404, "Brak raportu — uruchom najpierw POST /report/pdf")
    return FileResponse(
        path=latest,
        media_type="application/pdf",
        filename=f"liofilizaty-{dt.date.today().isoformat()}.pdf",
    )


# ──────────────────────────────────────────────────────── helpers


def _scrape_with_cwd(dry_run: bool, only_shops: list, only_product: Optional[str]) -> int:
    """Uruchamia scraping z poprawnym CWD żeby ścieżki się zgadzały."""
    try:
        os.chdir(ROOT)
        return run_scraper(dry_run=dry_run, only_shops=only_shops, only_product=only_product)
    except Exception as e:
        log.exception("Błąd w scrape: %s", e)
        return 1
