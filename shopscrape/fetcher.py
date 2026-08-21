from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field

import requests
from requests.adapters import HTTPAdapter

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    pass


@dataclass
class RateLimiter:
    delay: float = 0.6
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _last: float = field(default=0.0, repr=False)

    def wait(self) -> None:
        if self.delay <= 0:
            return
        with self._lock:
            gap = time.monotonic() - self._last
            if gap < self.delay:
                time.sleep(self.delay - gap)
            self._last = time.monotonic()


class Fetcher:
    def __init__(
        self,
        *,
        delay: float = 0.6,
        timeout: float = 30.0,
        retries: int = 4,
        user_agent: str = DEFAULT_UA,
        proxy: str | None = None,
        verbose: bool = False,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.verbose = verbose
        self.limiter = RateLimiter(delay)
        self.stats = {"requests": 0, "retries": 0, "bytes": 0, "errors": 0}

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        })
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        adapter = HTTPAdapter(pool_connections=16, pool_maxsize=16, max_retries=0)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def get(self, url: str, *, params: dict | None = None, expect_json: bool = False):
        last_exc: Exception | None = None

        for attempt in range(self.retries + 1):
            self.limiter.wait()
            try:
                self.stats["requests"] += 1
                resp = self.session.get(url, params=params, timeout=self.timeout, allow_redirects=True)
                self.stats["bytes"] += len(resp.content or b"")

                if resp.status_code in RETRY_STATUS:
                    raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                if resp.status_code == 404:
                    raise FetchError(f"404 Not Found: {url}")
                resp.raise_for_status()

                if expect_json:
                    ctype = resp.headers.get("Content-Type", "")
                    if "json" not in ctype.lower():
                        raise FetchError(
                            f"Expected JSON but got '{ctype or 'unknown'}' from {url}."
                        )
                    return resp.json()
                return resp

            except FetchError:
                self.stats["errors"] += 1
                raise
            except Exception as exc:
                last_exc = exc
                if attempt >= self.retries:
                    break
                self.stats["retries"] += 1
                sleep_for = self._backoff(exc, attempt)
                if self.verbose:
                    print(f"  retry {attempt + 1}/{self.retries} in {sleep_for:.1f}s — {exc}")
                time.sleep(sleep_for)

        self.stats["errors"] += 1
        raise FetchError(f"Failed after {self.retries} retries: {url} — {last_exc}")

    def _backoff(self, exc: Exception, attempt: int) -> float:
        resp = getattr(exc, "response", None)
        if resp is not None:
            ra = resp.headers.get("Retry-After")
            if ra:
                try:
                    return min(float(ra), 60.0)
                except ValueError:
                    pass
        return min(2.0 ** attempt + random.uniform(0, 0.75), 30.0)

    def close(self) -> None:
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
