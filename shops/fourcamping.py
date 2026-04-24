"""
Adapter dla 4camping.pl.

Strategia: ładuje katalog prowiantu turystycznego z podziałem na strony.
Każda karta produktu zawiera JSON w atrybucie data-product (name, url,
producerName, unitPriceWithVat). Filtruje po producerName = Travellunch / Trek'n Eat.
Katalog cache'owany w pamięci.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import List, Optional
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from .base import ProductHit, ShopAdapter

log = logging.getLogger(__name__)

BASE_URL = "https://www.4camping.pl"
CATALOG_URLS = [
    "https://www.4camping.pl/c/wyposazenie/gotowanie-i-zywnosc/prowiant-turystyczny/dania-glowne/",
    "https://www.4camping.pl/c/wyposazenie/gotowanie-i-zywnosc/prowiant-turystyczny/sniadania-desry/",
    "https://www.4camping.pl/c/wyposazenie/gotowanie-i-zywnosc/prowiant-turystyczny/zupy-instant/",
]
TARGET_PRODUCERS = {"travellunch", "trek'n eat", "trekn eat", "trek n eat"}


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


class FourCampingAdapter(ShopAdapter):
    shop_id = "4camping"
    base_url = BASE_URL
    request_delay_s = 1.5

    def __init__(self) -> None:
        super().__init__()
        self._catalog: Optional[list[ProductHit]] = None

    def _load_catalog(self) -> list[ProductHit]:
        if self._catalog is not None:
            return self._catalog

        hits: list[ProductHit] = []
        seen_urls: set[str] = set()

        for cat_url in CATALOG_URLS:
            html = self.get(cat_url)
            if not html:
                continue

            soup = BeautifulSoup(html, "lxml")
            cards = soup.select("article.product-card[data-product]")
            cat_found = 0

            for card in cards:
                try:
                    data = json.loads(card["data-product"])
                except (KeyError, json.JSONDecodeError):
                    continue

                producer = data.get("producerName", "").lower()
                if not any(t in producer for t in TARGET_PRODUCERS):
                    continue

                url_path = data.get("url", "")
                if not url_path:
                    continue
                full_url = BASE_URL + url_path if url_path.startswith("/") else url_path
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)
                cat_found += 1

                name = data.get("name", "")
                price_raw = data.get("unitPriceWithVat")
                price = float(price_raw) if price_raw is not None else None

                hits.append(ProductHit(title=name, url=full_url, price_pln=price, available=price is not None))

            log.debug("4camping: %s — %d pasujących", cat_url.split("/")[-2], cat_found)

        log.info("4camping: załadowano %d produktów z katalogu", len(hits))
        self._catalog = hits
        return self._catalog

    def search(self, query: str) -> List[ProductHit]:
        catalog = self._load_catalog()
        scored = [(hit, _score(query, hit.title)) for hit in catalog]
        scored = [(hit, s) for hit, s in scored if s >= 0.6]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [hit for hit, _ in scored[:5]]
