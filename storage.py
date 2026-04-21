"""
Warstwa bazy danych — SQLite, bardzo prosta.

Schema:
    prices(
        product_id  TEXT,     -- np. "rt_reindeer_stew"
        shop_id     TEXT,     -- np. "skalnik"
        date        DATE,     -- ISO 'YYYY-MM-DD'
        price_pln   REAL,     -- NULL jeśli nie znaleziono / niedostępny
        available   INTEGER,  -- 0/1
        product_url TEXT,     -- link do strony produktu w sklepie
        product_title TEXT,   -- tytuł jaki zwrócił sklep (do weryfikacji)
        PRIMARY KEY (product_id, shop_id, date)
    )

Zapis dnia jest idempotentny — run dwukrotnie w ciągu dnia nadpisze wiersz.
"""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    product_id    TEXT NOT NULL,
    shop_id       TEXT NOT NULL,
    date          TEXT NOT NULL,
    price_pln     REAL,
    available     INTEGER NOT NULL,
    product_url   TEXT,
    product_title TEXT,
    PRIMARY KEY (product_id, shop_id, date)
);

CREATE INDEX IF NOT EXISTS idx_prices_product_date
    ON prices(product_id, date);
"""


class PriceDB:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._ensure_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)

    def upsert(
        self,
        product_id: str,
        shop_id: str,
        date: dt.date,
        price_pln: Optional[float],
        available: bool,
        product_url: Optional[str],
        product_title: Optional[str],
    ) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO prices
                    (product_id, shop_id, date, price_pln, available,
                     product_url, product_title)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_id, shop_id, date) DO UPDATE SET
                    price_pln = excluded.price_pln,
                    available = excluded.available,
                    product_url = excluded.product_url,
                    product_title = excluded.product_title
                """,
                (
                    product_id,
                    shop_id,
                    date.isoformat(),
                    price_pln,
                    int(available),
                    product_url,
                    product_title,
                ),
            )

    def history(
        self,
        product_id: str,
        days: int,
        today: Optional[dt.date] = None,
    ) -> List[sqlite3.Row]:
        """Zwraca wiersze od (today - days + 1) do today, wszystkie sklepy."""
        today = today or dt.date.today()
        since = (today - dt.timedelta(days=days - 1)).isoformat()
        with self._conn() as c:
            cur = c.execute(
                """
                SELECT shop_id, date, price_pln, available, product_url, product_title
                FROM prices
                WHERE product_id = ? AND date >= ?
                ORDER BY date ASC, shop_id ASC
                """,
                (product_id, since),
            )
            return list(cur.fetchall())

    def latest_by_shop(
        self,
        product_id: str,
        today: Optional[dt.date] = None,
    ) -> dict[str, sqlite3.Row]:
        """Najnowszy odczyt (na `today`) per sklep dla danego produktu."""
        today = today or dt.date.today()
        with self._conn() as c:
            cur = c.execute(
                """
                SELECT shop_id, date, price_pln, available, product_url, product_title
                FROM prices
                WHERE product_id = ? AND date = ?
                """,
                (product_id, today.isoformat()),
            )
            return {row["shop_id"]: row for row in cur.fetchall()}
