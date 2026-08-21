from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field

from .config import Settings, Site
from .models import Product


@dataclass
class Filters:
    query: str = ""
    vendor: str = ""
    ptype: str = ""
    tag: str = ""
    min_price: float | None = None
    max_price: float | None = None
    in_stock_only: bool = False
    with_images_only: bool = False
    exclude: str = ""
    limit: int = 0

    def apply(self, products: list[Product]) -> list[Product]:
        out = products

        if self.query:
            q = self.query.lower()
            out = [p for p in out if q in p.title.lower()]
        if self.vendor:
            v = self.vendor.lower()
            out = [p for p in out if v in (p.vendor or "").lower()]
        if self.ptype:
            t = self.ptype.lower()
            out = [p for p in out if t in (p.product_type or "").lower()]
        if self.tag:
            t = self.tag.lower()
            out = [p for p in out if any(t in tag.lower() for tag in p.tags)]
        if self.exclude:
            rx = re.compile(self.exclude, re.I)
            out = [p for p in out if not rx.search(p.title)]
        if self.in_stock_only:
            out = [p for p in out if p.in_stock]
        if self.with_images_only:
            out = [p for p in out if p.images]
        if self.min_price is not None:
            out = [p for p in out if p.price_min and float(p.price_min) >= self.min_price]
        if self.max_price is not None:
            out = [p for p in out if p.price_max and float(p.price_max) <= self.max_price]
        if self.limit:
            out = out[: self.limit]
        return out

    def describe(self) -> str:
        bits = []
        for label, val in (("q", self.query), ("vendor", self.vendor), ("type", self.ptype),
                           ("tag", self.tag), ("exclude", self.exclude)):
            if val:
                bits.append(f"{label}={val}")
        if self.min_price is not None:
            bits.append(f"min={self.min_price}")
        if self.max_price is not None:
            bits.append(f"max={self.max_price}")
        if self.in_stock_only:
            bits.append("in-stock")
        if self.with_images_only:
            bits.append("with-images")
        if self.limit:
            bits.append(f"limit={self.limit}")
        return ", ".join(bits) or "none"


def _round_price(value: float, mode: str) -> float:
    if not mode:
        return round(value, 2)
    if mode == "int":
        return float(round(value))
    if mode == "0.99":
        return float(math.floor(value)) + 0.99 if value >= 1 else round(value, 2)
    if mode == "9":
        base = math.floor(value / 10) * 10
        return float(base + 9)
    if mode == "10":
        return float(round(value / 10) * 10)
    return round(value, 2)


@dataclass
class Rules:
    price_multiplier: float = 1.0
    price_round: str = ""
    vendor_override: str = ""
    add_tags: list[str] = field(default_factory=list)
    tag_prefix: str = ""
    title_prefix: str = ""
    title_suffix: str = ""
    strip_vendor_from_title: bool = False
    status: str = "Active"
    published: bool = True
    image_width: int = 0

    @classmethod
    def from_settings(cls, s: Settings, site: Site | None = None, **overrides) -> "Rules":
        r = cls(
            price_multiplier=s.price_multiplier,
            price_round=s.price_round,
            status=s.published_status,
            image_width=s.image_width,
        )
        if site:
            r.vendor_override = site.vendor_override or ""
            r.tag_prefix = site.tag_prefix or ""
            r.add_tags = list(site.extra_tags)
        for k, v in overrides.items():
            if v not in (None, "", [], 0) or isinstance(v, bool):
                setattr(r, k, v)
        return r

    def apply(self, p: Product) -> Product:
        p = copy.deepcopy(p)

        if self.vendor_override:
            p.vendor = self.vendor_override
        if self.strip_vendor_from_title and p.vendor:
            p.title = re.sub(rf"^{re.escape(p.vendor)}\s*[-–|:]?\s*", "", p.title, flags=re.I).strip()
        if self.title_prefix:
            p.title = f"{self.title_prefix}{p.title}"
        if self.title_suffix:
            p.title = f"{p.title}{self.title_suffix}"

        if self.tag_prefix:
            p.tags = [f"{self.tag_prefix}{t}" for t in p.tags]
        if self.add_tags:
            p.tags = list(dict.fromkeys(p.tags + self.add_tags))

        if self.price_multiplier and self.price_multiplier != 1.0:
            for v in p.variants:
                if v.price:
                    v.price = f"{_round_price(float(v.price) * self.price_multiplier, self.price_round):.2f}"
                if v.compare_at_price:
                    v.compare_at_price = (
                        f"{_round_price(float(v.compare_at_price) * self.price_multiplier, self.price_round):.2f}"
                    )
        elif self.price_round:
            for v in p.variants:
                if v.price:
                    v.price = f"{_round_price(float(v.price), self.price_round):.2f}"

        return p


def dedupe(products: list[Product], key: str = "handle") -> tuple[list[Product], int]:
    if key == "none":
        return products, 0
    seen: set[str] = set()
    out, dropped = [], 0
    for p in products:
        k = (p.handle if key == "handle" else re.sub(r"\W+", "", p.title.lower()))
        if k in seen:
            dropped += 1
            continue
        seen.add(k)
        out.append(p)
    return out, dropped
