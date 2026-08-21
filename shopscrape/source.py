from __future__ import annotations

from collections.abc import Iterator, Callable

from .config import Site
from .fetcher import Fetcher, FetchError
from .models import Product, product_from_shopify


class SourceError(RuntimeError):
    pass


class ShopifySource:
    platform = "shopify"

    def __init__(self, site: Site, fetcher: Fetcher, *, page_size: int = 250,
                 max_pages: int = 400, limit: int = 0):
        self.site = site
        self.fetcher = fetcher
        self.page_size = max(1, min(int(page_size), 250))
        self.max_pages = max_pages
        self.limit = limit
        self.pages_read = 0

    def collections(self) -> list[dict]:
        try:
            data = self.fetcher.get(f"{self.site.base_url}/collections.json",
                                    params={"limit": 250}, expect_json=True)
            return data.get("collections", []) or []
        except Exception:
            return []

    def count(self) -> int:
        total, page = 0, 1
        while page <= self.max_pages:
            data = self._page(page)
            n = len(data)
            total += n
            if n < self.page_size:
                break
            page += 1
        return total

    def iter_products(self, *, on_page: Callable[[int, int], None] | None = None) -> Iterator[Product]:
        if self.site.collections:
            yield from self._iter_collections(on_page)
        else:
            yield from self._iter_all(on_page)

    def _iter_all(self, on_page) -> Iterator[Product]:
        seen: set[int] = set()
        page, emitted = 1, 0
        while page <= self.max_pages:
            raws = self._page(page)
            if not raws:
                break
            for raw in raws:
                pid = raw.get("id")
                if pid in seen:
                    continue
                seen.add(pid)
                yield product_from_shopify(raw, self.site.key, self.site.domain)
                emitted += 1
                if self.limit and emitted >= self.limit:
                    return
            if on_page:
                on_page(page, emitted)
            if len(raws) < self.page_size:
                break
            page += 1

    def _iter_collections(self, on_page) -> Iterator[Product]:
        seen: set[int] = set()
        emitted = 0
        for handle in self.site.collections:
            page = 1
            while page <= self.max_pages:
                url = f"{self.site.base_url}/collections/{handle}/products.json"
                try:
                    data = self.fetcher.get(url, params={"limit": self.page_size, "page": page},
                                            expect_json=True)
                except FetchError as exc:
                    raise SourceError(f"{self.site.key}: collection '{handle}' failed — {exc}") from exc
                raws = data.get("products", []) or []
                self.pages_read += 1
                if not raws:
                    break
                for raw in raws:
                    pid = raw.get("id")
                    if pid in seen:
                        continue
                    seen.add(pid)
                    yield product_from_shopify(raw, self.site.key, self.site.domain)
                    emitted += 1
                    if self.limit and emitted >= self.limit:
                        return
                if on_page:
                    on_page(self.pages_read, emitted)
                if len(raws) < self.page_size:
                    break
                page += 1

    def _page(self, page: int) -> list[dict]:
        url = f"{self.site.base_url}/products.json"
        try:
            data = self.fetcher.get(url, params={"limit": self.page_size, "page": page},
                                    expect_json=True)
        except FetchError as exc:
            raise SourceError(
                f"{self.site.key} ({self.site.domain}): {exc}\n"
                "  Hint: run 'shopctl doctor' to check whether this store exposes /products.json."
            ) from exc
        self.pages_read += 1
        return data.get("products", []) or []


SOURCES: dict[str, type] = {
    "shopify": ShopifySource,
}


def build_source(site: Site, fetcher: Fetcher, **kw):
    cls = SOURCES.get(site.platform)
    if cls is None:
        raise SourceError(
            f"No adapter for platform '{site.platform}' (site '{site.key}'). "
            f"Supported: {', '.join(sorted(SOURCES))}."
        )
    return cls(site, fetcher, **kw)
