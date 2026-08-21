from __future__ import annotations

import re
from dataclasses import dataclass

from .fetcher import Fetcher, FetchError

SIGNATURES = [
    ("shopify",     re.compile(r"cdn\.shopify\.com|Shopify\.shop|/cdn/shop/", re.I)),
    ("woocommerce", re.compile(r"woocommerce|wc-ajax", re.I)),
    ("opencart",    re.compile(r"index\.php\?route=|catalog/view/theme", re.I)),
    ("magento",     re.compile(r"Magento|mage/cookies|static/version", re.I)),
    ("bigcommerce", re.compile(r"cdn\d*\.bigcommerce\.com", re.I)),
    ("wix",         re.compile(r"static\.parastorage\.com|wixstatic", re.I)),
    ("squarespace", re.compile(r"squarespace\.com|static1\.squarespace", re.I)),
    ("drupal",      re.compile(r"/sites/default/files|Drupal\.settings", re.I)),
    ("wordpress",   re.compile(r"wp-content|wp-includes", re.I)),
]


@dataclass
class Detection:
    domain: str
    platform: str = "unknown"
    products_json: bool = False
    product_sample: str = ""
    total_hint: int | None = None
    reachable: bool = False
    note: str = ""

    @property
    def supported(self) -> bool:
        return self.platform == "shopify" and self.products_json


def detect(domain: str, fetcher: Fetcher) -> Detection:
    d = Detection(domain=domain)

    try:
        data = fetcher.get(f"https://{domain}/products.json",
                           params={"limit": 5}, expect_json=True)
        items = data.get("products") if isinstance(data, dict) else None
        if isinstance(items, list):
            d.reachable = True
            d.products_json = True
            d.platform = "shopify"
            if items:
                d.product_sample = items[0].get("title", "")[:80]
            else:
                d.note = "Endpoint returned 0 products (store may be empty or password-protected)."
            return d
    except (FetchError, Exception):
        pass

    try:
        resp = fetcher.get(f"https://{domain}")
        d.reachable = True
        html = resp.text[:400_000]
        for name, pattern in SIGNATURES:
            if pattern.search(html):
                d.platform = name
                break
        if d.platform == "shopify":
            d.note = "Shopify detected but /products.json is unavailable or password-protected."
        elif d.platform == "unknown":
            d.note = "Platform could not be detected."
        else:
            d.note = f"Detected {d.platform} (only Shopify is currently supported)."
    except Exception as exc:
        d.note = f"Unreachable: {exc}"

    return d
