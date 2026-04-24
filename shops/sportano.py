"""
Adapter dla Sportano.pl.

Strategia: ładuje katalog ze stron marki (travellunch ~4 prod., trek-n-eat ~15 prod.).
Każda karta produktu zawiera JSON w atrybucie data-product (name, finalPrice, stockStatus).
Katalog cache'owany w pamięci.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import List, Optional

from bs4 import BeautifulSoup

from .base import ProductHit, ShopAdapter

log = logging.getLogger(__name__)

BASE_URL = "https://sportano.pl"

BRAND_URLS = [
    "https://sportano.pl/marki/travellunch",
    "https://sportano.pl/marki/trek-n-eat",
]


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


class SportanoAdapter(ShopAdapter):
    shop_id = "sportano"
    base_url = BASE_URL

    def __init__(self) -> None:
        super().__init__()
        self._catalog: Optional[list[ProductHit]] = None

    def _load_catalog(self) -> list[ProductHit]:
        if self._catalog is not None:
            return self._catalog

        hits: list[ProductHit] = []
        seen_urls: set[str] = set()

        for brand_url in BRAND_URLS:
            html = self.get(brand_url)
            if not html:
                log.warning("Sportano: nie można załadować %s", brand_url)
                continue

            soup = BeautifulSoup(html, "lxml")
            cards = soup.select(".product-card[data-product]")
            for card in cards:
                try:
                    data = json.loads(card["data-product"])
                except (KeyError, json.JSONDecodeError):
                    continue

                attrs = data.get("attributes", {})
                name = attrs.get("name", "")
                if not name:
                    name_el = card.select_one(".product-card__name")
                    name = name_el.get_text(strip=True) if name_el else ""

                link = card.select_one("a[href]")
                href = link["href"] if link else ""
                if not href:
                    continue
                if not href.startswith("http"):
                    href = BASE_URL + href
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                price_raw = data.get("finalPrice") or data.get("price")
                price = float(price_raw) if price_raw is not None else None

                available = bool(data.get("stockStatus", False))
                if price is None:
                    available = False

                hits.append(ProductHit(title=name, url=href, price_pln=price, available=available))

        log.info("Sportano: załadowano %d produktów z katalogu", len(hits))
        self._catalog = hits
        return self._catalog

    def search(self, query: str) -> List[ProductHit]:
        catalog = self._load_catalog()
        scored = [(hit, _score(query, hit.title)) for hit in catalog]
        scored = [(hit, s) for hit, s in scored if s >= 0.6]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [hit for hit, _ in scored[:5]]
