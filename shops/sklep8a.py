"""
Adapter dla 8a.pl.

Strategia:
 1. GET https://8a.pl/szukaj?controller=search&search_query=<query>
    (8a używa PrestaShop-a; wyszukiwarka na parametrze `search_query`)
 2. Parsuje listę produktów z klasy .product-miniature / .js-product-miniature
 3. Dla najlepszego dopasowania zwraca: tytuł, URL, cenę, dostępność

UWAGA: scraping może się zepsuć gdy 8a zmieni markup. Selektory napisane
defensywnie — próbują kilku wariantów. Przy pierwszym realnym runie wystarczy
zweryfikować że `search()` coś zwraca; jeśli nie — otwórz w przeglądarce
https://8a.pl/szukaj?search_query=real+turmat i porównaj klasy z kodem.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import List, Optional

from bs4 import BeautifulSoup, Tag

from .base import ProductHit, ShopAdapter, parse_price_pln

log = logging.getLogger(__name__)


class Sklep8aAdapter(ShopAdapter):
    shop_id = "sklep8a"
    base_url = "https://8a.pl"

    SEARCH_URL = "https://8a.pl/szukaj?controller=search&search_query={q}"

    # Markery "produkt niedostępny" występujące w HTML karty produktu na 8a.pl
    UNAVAILABLE_MARKERS = (
        "chwilowo niedostępny",
        "niedostępny",
        "brak w magazynie",
        "zapytaj o dostępność",
    )

    def search(self, query: str) -> List[ProductHit]:
        url = self.SEARCH_URL.format(q=urllib.parse.quote(query))
        html = self.get(url)
        if not html:
            log.warning("8a: pusty HTML dla '%s'", query)
            return []

        soup = BeautifulSoup(html, "lxml")
        hits: List[ProductHit] = []

        # Próba 1: typowy PrestaShop — kafelki .product-miniature
        tiles = soup.select(".product-miniature, .js-product-miniature, article.product")
        # Próba 2: bardziej ogólne — cokolwiek z data-id-product
        if not tiles:
            tiles = soup.select("[data-id-product]")
        # Próba 3: szukaj po linku na /product albo bezpośrednio na slug
        if not tiles:
            tiles = soup.select("div.product, li.product, div.item")

        for tile in tiles[:20]:  # top 20 wyników wystarczy
            hit = self._parse_tile(tile)
            if hit:
                hits.append(hit)

        log.info("8a: %d hitów dla '%s'", len(hits), query)
        return hits

    def _parse_tile(self, tile: Tag) -> Optional[ProductHit]:
        # --- tytuł + URL ---
        link = (
            tile.select_one("h2 a, h3 a, .product-title a, a.product-name, a.thumbnail")
            or tile.find("a", href=True)
        )
        if not link:
            return None

        title = (link.get_text(strip=True) or link.get("title", "")).strip()
        href = link.get("href", "")
        if not title or not href:
            return None

        # Upewnij się że URL jest absolutny
        if href.startswith("/"):
            href = self.base_url + href
        elif not href.startswith("http"):
            href = f"{self.base_url}/{href}"

        # Filtrujemy tylko strony produktowe (liofilizat-... na slugu)
        if "/kategorie/" in href or "/marki/" in href or "/brand/" in href:
            return None

        # --- cena ---
        price_elem = (
            tile.select_one(".price, .product-price, [itemprop='price'], span.regular-price")
        )
        price_text = price_elem.get_text(" ", strip=True) if price_elem else ""
        # Fallback: szukaj w meta
        if not price_text:
            meta_price = tile.select_one("meta[itemprop='price']")
            if meta_price:
                price_text = meta_price.get("content", "")
        price = parse_price_pln(price_text)

        # --- dostępność ---
        tile_text_low = tile.get_text(" ", strip=True).lower()
        available = price is not None and not any(
            m in tile_text_low for m in self.UNAVAILABLE_MARKERS
        )
        # Dodatkowo, jeśli jest klasa .product-unavailable / out-of-stock — niedostępny
        if tile.select_one(".product-unavailable, .out-of-stock, .unavailable"):
            available = False

        return ProductHit(
            title=title, url=href, price_pln=price, available=available
        )
