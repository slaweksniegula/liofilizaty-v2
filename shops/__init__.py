"""Rejestr adapterów sklepów. Dodaj tu nowy sklep po stworzeniu pliku."""

from .base import ProductHit, ShopAdapter
from .fourcamping import FourCampingAdapter
from .skalnik import SkalnikAdapter
from .sklep8a import Sklep8aAdapter
from .sportano import SportanoAdapter
from .sewel import SewelAdapter
from .wgl import WglAdapter

ADAPTERS: dict[str, type[ShopAdapter]] = {
    "skalnik": SkalnikAdapter,
    "sklep8a": Sklep8aAdapter,
    "wgl": WglAdapter,
    "sportano": SportanoAdapter,
    "sewel": SewelAdapter,
    "4camping": FourCampingAdapter,
}

__all__ = ["ADAPTERS", "ProductHit", "ShopAdapter"]
