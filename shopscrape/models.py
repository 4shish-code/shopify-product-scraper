from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(html: str | None) -> str:
    if not html:
        return ""
    text = _TAG_RE.sub(" ", html)
    for ent, rep in (
        ("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", '"'), ("&#39;", "'"), ("&rsquo;", "'"), ("&ndash;", "-"),
    ):
        text = text.replace(ent, rep)
    return _WS_RE.sub(" ", text).strip()


def _money(v: Any) -> str:
    if v in (None, "", "0.00") and v != "0.00":
        return ""
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return ""


@dataclass(slots=True)
class Image:
    src: str = ""
    position: int = 1
    alt: str = ""
    width: int | None = None
    height: int | None = None
    variant_ids: list[int] = field(default_factory=list)

    def sized(self, width: int | None) -> str:
        if not width or not self.src or "cdn.shopify.com" not in self.src:
            return self.src
        joiner = "&" if "?" in self.src else "?"
        return f"{self.src}{joiner}width={width}"


@dataclass(slots=True)
class Variant:
    id: int | None = None
    title: str = ""
    sku: str = ""
    barcode: str = ""
    price: str = ""
    compare_at_price: str = ""
    option1: str = ""
    option2: str = ""
    option3: str = ""
    grams: int = 0
    available: bool = True
    taxable: bool = True
    requires_shipping: bool = True
    position: int = 1
    image_src: str = ""

    @property
    def is_default(self) -> bool:
        return self.title in ("", "Default Title")

    @property
    def on_sale(self) -> bool:
        try:
            return bool(self.compare_at_price) and float(self.compare_at_price) > float(self.price)
        except (TypeError, ValueError):
            return False

    @property
    def discount_pct(self) -> float:
        if not self.on_sale:
            return 0.0
        cap, p = float(self.compare_at_price), float(self.price)
        return round((cap - p) / cap * 100, 1) if cap else 0.0


@dataclass(slots=True)
class Product:
    id: int | None = None
    handle: str = ""
    title: str = ""
    body_html: str = ""
    vendor: str = ""
    product_type: str = ""
    tags: list[str] = field(default_factory=list)
    published_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    option_names: list[str] = field(default_factory=list)
    variants: list[Variant] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    site_key: str = ""
    site_domain: str = ""
    source_url: str = ""

    @property
    def price_min(self) -> str:
        prices = [float(v.price) for v in self.variants if v.price]
        return f"{min(prices):.2f}" if prices else ""

    @property
    def price_max(self) -> str:
        prices = [float(v.price) for v in self.variants if v.price]
        return f"{max(prices):.2f}" if prices else ""

    @property
    def in_stock(self) -> bool:
        return any(v.available for v in self.variants)

    @property
    def image_count(self) -> int:
        return len(self.images)

    @property
    def plain_description(self) -> str:
        return strip_html(self.body_html)

    def to_dict(self) -> dict:
        return asdict(self)


def variant_from_shopify(raw: dict, images_by_id: dict[int, str]) -> Variant:
    vid = raw.get("id")
    img = ""
    fi = raw.get("featured_image")
    if isinstance(fi, dict):
        img = fi.get("src") or ""
    if not img and vid in images_by_id:
        img = images_by_id[vid]
    return Variant(
        id=vid,
        title=raw.get("title") or "",
        sku=(raw.get("sku") or "").strip(),
        barcode=(raw.get("barcode") or "").strip(),
        price=_money(raw.get("price")),
        compare_at_price=_money(raw.get("compare_at_price")),
        option1=raw.get("option1") or "",
        option2=raw.get("option2") or "",
        option3=raw.get("option3") or "",
        grams=int(raw.get("grams") or 0),
        available=bool(raw.get("available", True)),
        taxable=bool(raw.get("taxable", True)),
        requires_shipping=bool(raw.get("requires_shipping", True)),
        position=int(raw.get("position") or 1),
        image_src=img,
    )


def product_from_shopify(raw: dict, site_key: str, domain: str) -> Product:
    images: list[Image] = []
    images_by_variant: dict[int, str] = {}
    for i, im in enumerate(raw.get("images") or [], start=1):
        src = im.get("src") or ""
        vids = [int(v) for v in (im.get("variant_ids") or [])]
        images.append(Image(
            src=src,
            position=int(im.get("position") or i),
            alt=(im.get("alt") or "").strip(),
            width=im.get("width"),
            height=im.get("height"),
            variant_ids=vids,
        ))
        for v in vids:
            images_by_variant.setdefault(v, src)

    images.sort(key=lambda x: x.position)

    opts = [o.get("name", "") for o in (raw.get("options") or [])]
    handle = raw.get("handle") or ""

    return Product(
        id=raw.get("id"),
        handle=handle,
        title=(raw.get("title") or "").strip(),
        body_html=raw.get("body_html") or "",
        vendor=(raw.get("vendor") or "").strip(),
        product_type=(raw.get("product_type") or "").strip(),
        tags=[t.strip() for t in (raw.get("tags") or []) if t and t.strip()],
        published_at=raw.get("published_at") or "",
        created_at=raw.get("created_at") or "",
        updated_at=raw.get("updated_at") or "",
        option_names=opts,
        variants=[variant_from_shopify(v, images_by_variant) for v in (raw.get("variants") or [])],
        images=images,
        site_key=site_key,
        site_domain=domain,
        source_url=f"https://{domain}/products/{handle}" if handle else "",
    )
