"""
Adapter dla Skalnik.pl.

Strategia:
 1. GET https://www.skalnik.pl/wyszukiwanie-zaawansowane?q=<query>
    (alternatywnie https://www.skalnik.pl/search.php?q=<query> jeśli to zadziała)
 2. Parsuje listę produktów z .product-list-item / .product-wrapper
 3. Dla najlepszego dopasowania zwraca: tytuł, URL, cenę, dostępność

Tak jak w 8a, selektory pisane defensywnie. Przy pierwszym runie zweryfikuj
że search() coś zwraca; jeśli nie, otwórz URL wyszukiwarki Skalnika
w przeglądarce i porównaj klasy produktów z kodem.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import List, Optional

from bs4 import BeautifulSoup, Tag

from .base import ProductHit, ShopAdapter, parse_price_pln

log = logging.getLogger(__name__)


class SkalnikAdapter(ShopAdapter):
    shop_id = "skalnik"
    base_url = "https://www.skalnik.pl"

    SEARCH_URLS = (
        "https://www.skalnik.pl/catalogsearch/result/?q={q}",
    )

    UNAVAILABLE_MARKERS = (
        "produkt niedostępny",
        "chwilowo niedostępny",
        "niedostępny",
        "brak w magazynie",
        "powiadom o dostępności",
    )

    def search(self, query: str) -> List[ProductHit]:
        q = urllib.parse.quote(query)
        html: Optional[str] = None
        for template in self.SEARCH_URLS:
            url = template.format(q=q)
            html = self.get(url)
            if html and ("product" in html.lower() or "liofilizat" in html.lower()):
                break
        if not html:
            log.warning("Skalnik: pusty HTML dla '%s'", query)
            return []

        soup = BeautifulSoup(html, "lxml")
        hits: List[ProductHit] = []

        # Skalnik używa (na czas pisania) klas typu .product-list, .product-wrapper,
        # .product-item. Próbujemy kilku wariantów.
        tiles = soup.select(
            ".product-wrapper, .product-list-item, .product-item, "
            "li.product, article.product, div.product-grid-item"
        )
        if not tiles:
            # Fallback: każdy element z linkiem do /product_info lub /p/
            tiles = [
                a.find_parent(["div", "li", "article"]) or a
                for a in soup.select("a[href*='/product'], a[href*='/p/']")
            ]

        seen_urls = set()
        for tile in tiles[:20]:
            if not isinstance(tile, Tag):
                continue
            hit = self._parse_tile(tile)
            if hit and hit.url not in seen_urls:
                seen_urls.add(hit.url)
                hits.append(hit)

        log.info("Skalnik: %d hitów dla '%s'", len(hits), query)
        return hits

    def _parse_tile(self, tile: Tag) -> Optional[ProductHit]:
        link = (
            tile.select_one(
                "h2 a, h3 a, .product-title a, .product-name a, a.name, a.thumbnail"
            )
            or tile.find("a", href=True)
        )
        if not link:
            return None

        title = (link.get_text(strip=True) or link.get("title", "")).strip()
        href = link.get("href", "")
        if not title or not href:
            return None

        if href.startswith("/"):
            href = self.base_url + href
        elif not href.startswith("http"):
            href = f"{self.base_url}/{href}"

        # Filtruj kategorie (na Skalniku kategorie mają /sprzet-turystyczny/... w URL)
        if "/sprzet-turystyczny/" in href and href.count("/") < 6:
            return None

        # --- cena ---
        price_elem = tile.select_one(
            ".price, .product-price, .current-price, "
            "[itemprop='price'], span.regular-price, .price-new"
        )
        price_text = price_elem.get_text(" ", strip=True) if price_elem else ""
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
        if tile.select_one(".product-unavailable, .out-of-stock, .unavailable, .notify-me"):
            available = False

        return ProductHit(
            title=title, url=href, price_pln=price, available=available
        )
