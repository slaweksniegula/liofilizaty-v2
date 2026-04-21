"""Rejestr adapterów sklepów. Dodaj tu nowy sklep po stworzeniu pliku."""

from .base import ProductHit, ShopAdapter
from .skalnik import SkalnikAdapter
from .sklep8a import Sklep8aAdapter

ADAPTERS: dict[str, type[ShopAdapter]] = {
    "skalnik": SkalnikAdapter,
    "sklep8a": Sklep8aAdapter,
    # Faza 2:
    # "wgl": WglAdapter,
    # "sportano": SportanoAdapter,
    # ...
}

__all__ = ["ADAPTERS", "ProductHit", "ShopAdapter"]
