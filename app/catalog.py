from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from typing import Iterable


DEFAULT_CATALOG_URL = (
    "https://tcp-us-prod-rnd.shl.com/voiceRater/shl-ai-hiring/"
    "shl_product_catalog.json"
)

KEY_TO_CODE = {
    "Ability & Aptitude": "A",
    "Assessment Exercises": "E",
    "Biodata & Situational Judgment": "B",
    "Competencies": "C",
    "Development & 360": "D",
    "Personality & Behavior": "P",
    "Simulations": "S",
    "Knowledge & Skills": "K",
}


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9+.#]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class Product:
    entity_id: str
    name: str
    url: str
    test_type: str
    keys: tuple[str, ...]
    duration: str
    languages: tuple[str, ...]
    job_levels: tuple[str, ...]
    description: str

    @property
    def text(self) -> str:
        return " ".join(
            [
                self.name,
                self.description,
                " ".join(self.keys),
                " ".join(self.languages),
                " ".join(self.job_levels),
            ]
        )

    @property
    def norm_name(self) -> str:
        return normalize(self.name)

    @property
    def norm_text(self) -> str:
        return normalize(self.text)


class CatalogError(RuntimeError):
    pass


class CatalogClient:
    def __init__(self, url: str | None = None, ttl_seconds: int = 6 * 60 * 60):
        self.url = url or os.getenv("SHL_CATALOG_URL", DEFAULT_CATALOG_URL)
        self.ttl_seconds = ttl_seconds
        self._products: list[Product] = []
        self._loaded_at = 0.0
        self.last_error = ""

    def get_products(self) -> list[Product]:
        now = time.time()
        if self._products and now - self._loaded_at < self.ttl_seconds:
            return self._products
        try:
            self._products = self._fetch()
            self._loaded_at = now
            self.last_error = ""
        except Exception as exc:  # pragma: no cover - exercised in hosted env
            self.last_error = str(exc)
            if not self._products:
                raise CatalogError(f"Could not load SHL catalog: {exc}") from exc
        return self._products

    def ready(self) -> bool:
        try:
            return bool(self.get_products())
        except CatalogError:
            return False

    def _fetch(self) -> list[Product]:
        request = urllib.request.Request(
            self.url,
            headers={"User-Agent": "shl-assessment-recommender/1.0"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw, strict=False)
        products = [self._to_product(item) for item in data if item.get("status") == "ok"]
        if not products:
            raise CatalogError("catalog returned no usable products")
        return products

    def _to_product(self, item: dict) -> Product:
        keys = tuple(item.get("keys") or [])
        codes = [KEY_TO_CODE[key] for key in keys if key in KEY_TO_CODE]
        return Product(
            entity_id=str(item.get("entity_id") or ""),
            name=item.get("name") or "",
            url=item.get("link") or "",
            test_type=",".join(codes),
            keys=keys,
            duration=item.get("duration") or "",
            languages=tuple(item.get("languages") or []),
            job_levels=tuple(item.get("job_levels") or []),
            description=item.get("description") or "",
        )

    def find_by_name(self, name: str) -> Product | None:
        products = self.get_products()
        target = normalize(name)
        for product in products:
            if product.norm_name == target:
                return product
        for product in products:
            if target and (target in product.norm_name or product.norm_name in target):
                return product
        return None

    def products_by_names(self, names: Iterable[str]) -> list[Product]:
        found: list[Product] = []
        seen: set[str] = set()
        for name in names:
            product = self.find_by_name(name)
            if product and product.url not in seen:
                found.append(product)
                seen.add(product.url)
        return found
