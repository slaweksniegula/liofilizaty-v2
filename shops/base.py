"""
Klasa bazowa dla adapterów sklepów.

Każdy sklep dziedziczy po ShopAdapter i implementuje search(query) — metoda
ma zwrócić listę znalezionych produktów (ProductHit) lub pustą listę.

ProductHit to dataclass z polami:
    title      — tytuł produktu wyświetlany w sklepie
    url        — link do strony produktu
    price_pln  — cena w złotówkach (float), None = brak ceny / niedostępny
    available  — True / False (czy "dodaj do koszyka" jest aktywne)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

import requests

log = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.4 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass
class ProductHit:
    title: str
    url: str
    price_pln: Optional[float]
    available: bool

    def as_row(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "price_pln": self.price_pln,
            "available": self.available,
        }


class ShopAdapter:
    """Bazowa klasa adaptera sklepu. Dziedzicz i zaimplementuj `search()`."""

    shop_id: str = "base"
    base_url: str = ""
    request_delay_s: float = 2.0
    timeout_s: int = 20
    max_retries: int = 3

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._last_request_at: float = 0.0

    # ------------------------------------------------------------------ HTTP
    def get(self, url: str) -> Optional[str]:
        """GET z retry, rate-limitem i rozsądnym User-Agent."""
        self._rate_limit()
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout_s)
                if resp.status_code == 200:
                    return resp.text
                if resp.status_code in (403, 429, 503):
                    log.warning(
                        "%s: %s zwrócił %s, próba %d/%d",
                        self.shop_id, url, resp.status_code, attempt, self.max_retries,
                    )
                    time.sleep(2 ** attempt)
                    continue
                log.warning("%s: %s zwrócił %s", self.shop_id, url, resp.status_code)
                return None
            except requests.RequestException as e:
                log.warning(
                    "%s: błąd sieci przy %s (%s), próba %d/%d",
                    self.shop_id, url, e, attempt, self.max_retries,
                )
                time.sleep(2 ** attempt)
        return None

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_at
        if elapsed < self.request_delay_s:
            time.sleep(self.request_delay_s - elapsed)
        self._last_request_at = time.time()

    # --------------------------------------------------------------- PUBLIC
    def search(self, query: str) -> List[ProductHit]:
        """Zaimplementuj w podklasie: zwróć listę hitów dla frazy."""
        raise NotImplementedError

    def find_best_match(self, search_terms: List[str]) -> Optional[ProductHit]:
        """
        Próbuje kolejno każdą frazę z listy. Zwraca PIERWSZY hit z dostępną ceną,
        albo pierwszy hit w ogóle jeśli nic dostępnego. None jeśli zero wyników.
        """
        first_hit: Optional[ProductHit] = None
        for term in search_terms:
            hits = self.search(term)
            if not hits:
                continue
            if first_hit is None:
                first_hit = hits[0]
            for hit in hits:
                if hit.price_pln is not None and hit.available:
                    return hit
        return first_hit


# --------------------------------------------------------------- utilities
def parse_price_pln(text: str) -> Optional[float]:
    """
    Parsuje cenę z polskiego formatu: '149,90 zł', '1 299,00 zł', '149.90 PLN',
    'Aktualna cena 49,90 zł'. Zwraca float albo None.
    """
    import re

    if not text:
        return None
    # Weź pierwszą liczbę z opcjonalną spacją tysięczną i przecinkiem/kropką
    m = re.search(r"(\d[\d\s ]*[.,]\d{2})", text.replace("\xa0", " "))
    if not m:
        # Fallback: liczba bez groszy (rzadko, ale bywa)
        m = re.search(r"(\d[\d\s ]{1,6})\s*(?:zł|PLN)", text.replace("\xa0", " "), re.I)
        if not m:
            return None
    raw = m.group(1).replace(" ", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None
