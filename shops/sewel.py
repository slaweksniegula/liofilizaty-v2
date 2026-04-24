"""
Adapter dla Sewel.pl.

Strategia: ładuje katalog z podstron marki (Travellunch ma 18 produktów).
Trek'n Eat — sewel.pl nie prowadzi tej marki (brak w katalogu).
Katalog cache'owany w pamięci.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import List, Optional

from bs4 import BeautifulSoup

from .base import ProductHit, ShopAdapter, parse_price_pln

log = logging.getLogger(__name__)

BASE_URL = "https://sewel.pl"

BRAND_URLS = {
    "travellunch": "http://sewel.pl/firm-pol-1406122405-Travellunch.html",
}


def _normalize(text: str) -> set[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\(\d+\)", " ", text)
    return set(re.findall(r"[a-z]{3,}", text))


def _score(query: str, name: str) -> float:
    q = _normalize(query)
    n = _normalize(name)
    if not q:
        return 0.0
    return len(q & n) / len(q)


class SewelAdapter(ShopAdapter):
    shop_id = "sewel"
    base_url = BASE_URL

    def __init__(self) -> None:
        super().__init__()
        self._catalog: Optional[list[ProductHit]] = None

    def _load_catalog(self) -> list[ProductHit]:
        if self._catalog is not None:
            return self._catalog

        hits: list[ProductHit] = []
        for brand, url in BRAND_URLS.items():
            html = self.get(url)
            if not html:
                log.warning("Sewel: nie można załadować %s", url)
                continue
            soup = BeautifulSoup(html, "lxml")
            for tile in soup.select(".product[data-product_id]"):
                name_el = tile.select_one("h3 a.product__name, a.product__name")
                if not name_el:
                    continue
                title = name_el.get_text(strip=True)
                href = name_el.get("href", "")
                if not title or not href:
                    continue
                if href.startswith("/"):
                    href = BASE_URL + href

                price_el = tile.select_one("strong.price.--main")
                price_text = price_el.get_text(" ", strip=True) if price_el else ""
                price = parse_price_pln(price_text)

                tile_text = tile.get_text(" ", strip=True).lower()
                unavailable = any(m in tile_text for m in ("niedostępny", "brak", "out of stock"))
                available = price is not None and not unavailable

                hits.append(ProductHit(title=title, url=href, price_pln=price, available=available))

        log.info("Sewel: załadowano %d produktów z katalogu", len(hits))
        self._catalog = hits
        return self._catalog

    def search(self, query: str) -> List[ProductHit]:
        catalog = self._load_catalog()
        scored = [(hit, _score(query, hit.title)) for hit in catalog]
        scored = [(hit, s) for hit, s in scored if s >= 0.6]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [hit for hit, _ in scored[:5]]
