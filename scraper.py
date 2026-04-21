#!/usr/bin/env python3
"""
scraper.py — codzienne odpytywanie sklepów i zapis do SQLite.

Użycie:
    python scraper.py                 # pełny run: scrap + zapis
    python scraper.py --dry-run       # scrap i wypisz wyniki, bez zapisu do DB
    python scraper.py --shops 8a      # tylko wybrane sklepy (po przecinku)
    python scraper.py --product rt_reindeer_stew   # tylko jeden produkt

Wyjście:
    - prices.db (SQLite z historią)
    - STDOUT: log + podsumowanie

Ten skrypt jest myślą przewodnią: wszystko co ciekawe dzieje się w
shops/*.py (adapterach) i storage.py. Tutaj tylko orkiestracja.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
from pathlib import Path
from typing import List

import yaml

from shops import ADAPTERS
from storage import PriceDB

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.yaml"
# DB_PATH można podmienić przez zmienną środowiskową DATA_DIR — to pozwala
# trzymać bazę w wolumenie Dockera poza katalogiem aplikacji.
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT)))
DB_PATH = DATA_DIR / "prices.db"


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run(dry_run: bool, only_shops: List[str], only_product: str | None) -> int:
    log = logging.getLogger("scraper")
    cfg = load_config()

    # Przygotuj adaptery tylko dla włączonych sklepów
    enabled_shops = {
        sid: data for sid, data in cfg["shops"].items() if data.get("enabled", False)
    }
    if only_shops:
        enabled_shops = {k: v for k, v in enabled_shops.items() if k in only_shops}
    if not enabled_shops:
        log.error("Brak włączonych sklepów w config.yaml (lub --shops nic nie wybrał)")
        return 1

    adapters = {}
    for shop_id in enabled_shops:
        adapter_cls = ADAPTERS.get(shop_id)
        if not adapter_cls:
            log.warning("Brak adaptera dla shop_id='%s' — pomijam", shop_id)
            continue
        adapters[shop_id] = adapter_cls()

    products = cfg["products"]
    if only_product:
        products = [p for p in products if p["id"] == only_product]
        if not products:
            log.error("Nie znaleziono produktu '%s' w config.yaml", only_product)
            return 1

    db = PriceDB(DB_PATH) if not dry_run else None
    today = dt.date.today()

    log.info(
        "Start runu: %d produktów × %d sklepów = %d zapytań",
        len(products), len(adapters), len(products) * len(adapters),
    )
    if dry_run:
        log.info("*** DRY RUN — nic nie zapisuje do bazy ***")

    summary_rows: list[dict] = []

    for prod in products:
        pid = prod["id"]
        log.info("─── Produkt: %s (%s)", pid, prod["name"])

        for shop_id, adapter in adapters.items():
            try:
                hit = adapter.find_best_match(prod["search_terms"])
            except Exception as e:
                log.exception("Błąd w adapterze %s: %s", shop_id, e)
                hit = None

            if hit is None:
                log.info("  %-10s NIE ZNALEZIONO", shop_id)
                if db:
                    db.upsert(pid, shop_id, today, None, False, None, None)
                summary_rows.append(
                    {"product": pid, "shop": shop_id, "price": None,
                     "available": False, "title": None}
                )
                continue

            flag = "✓" if hit.available else "✗"
            price_str = f"{hit.price_pln:.2f} zł" if hit.price_pln else "—"
            log.info(
                "  %-10s %s  %-8s  %s",
                shop_id, flag, price_str, hit.title[:60],
            )
            if db:
                db.upsert(
                    pid, shop_id, today,
                    hit.price_pln, hit.available,
                    hit.url, hit.title,
                )
            summary_rows.append(
                {"product": pid, "shop": shop_id, "price": hit.price_pln,
                 "available": hit.available, "title": hit.title}
            )

    # Krótkie podsumowanie na koniec
    log.info("═══ KONIEC ═══")
    found = sum(1 for r in summary_rows if r["price"] is not None)
    log.info("Znaleziono ceny: %d / %d zapytań", found, len(summary_rows))

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Scraper liofilizatów")
    ap.add_argument("--dry-run", action="store_true",
                    help="Nie zapisuj do bazy")
    ap.add_argument("--shops", default="",
                    help="Lista shop_id po przecinku (pusta = wszystkie włączone)")
    ap.add_argument("--product", default=None,
                    help="Tylko jeden produkt po id (np. rt_reindeer_stew)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    setup_logging(args.verbose)
    only_shops = [s.strip() for s in args.shops.split(",") if s.strip()]
    return run(args.dry_run, only_shops, args.product)


if __name__ == "__main__":
    sys.exit(main())
