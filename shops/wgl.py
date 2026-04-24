"""
Adapter dla WGL.pl (wspinanie.pl).

Strategia: ładuje cały katalog żywności liofilizowanej (51 produktów, 1 strona)
z /category/zywnosc-liofilizowana-1410 i dopasowuje po nazwie.
Katalog jest cache'owany w pamięci na czas trwania procesu.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import List, Optional

from bs4 import BeautifulSoup

from .base import ProductHit, ShopAdapter, parse_price_pln

log = logging.getLogger(__name__)

CATALOG_URL = "https://www.wgl.pl/category/zywnosc-liofilizowana-1410"
BASE_URL = "https://www.wgl.pl"
TARGET_BRANDS = ("real turmat",)


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


class WglAdapter(ShopAdapter):
    shop_id = "wgl"
    base_url = BASE_URL

    def __init__(self) -> None:
        super().__init__()
        self._catalog: Optional[list[ProductHit]] = None

    def _load_catalog(self) -> list[ProductHit]:
        if self._catalog is not None:
            return self._catalog

        html = self.get(CATALOG_URL)
        if not html:
            log.warning("WGL: nie można załadować katalogu")
            self._catalog = []
            return self._catalog

        soup = BeautifulSoup(html, "lxml")
        hits: list[ProductHit] = []

        for tile in soup.select(".product.thumbnail"):
            link = tile.select_one("p.name a.product_name, .name a")
            if not link:
                continue
            title = link.get_text(strip=True)
            href = link.get("href", "")
            if not title or not href:
                continue
            if not any(b in title.lower() for b in TARGET_BRANDS):
                continue
            if href.startswith("/"):
                href = BASE_URL + href
            elif not href.startswith("http"):
                href = f"{BASE_URL}/{href}"

            price_el = tile.select_one(".box-price .price.nowrap, .price.nowrap")
            price_text = price_el.get_text(" ", strip=True) if price_el else ""
            price = parse_price_pln(price_text)

            basket_btn = tile.select_one("a.basket_add_link")
            available = price is not None and basket_btn is not None and "basket_disabled" not in basket_btn.get("class", [])

            hits.append(ProductHit(title=title, url=href, price_pln=price, available=available))

        log.info("WGL: załadowano %d produktów z katalogu", len(hits))
        self._catalog = hits
        return self._catalog

    def search(self, query: str) -> List[ProductHit]:
        catalog = self._load_catalog()
        scored = [(hit, _score(query, hit.title)) for hit in catalog]
        scored = [(hit, s) for hit, s in scored if s >= 0.6]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [hit for hit, _ in scored[:5]]
