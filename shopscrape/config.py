from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from urllib.parse import urlparse

import yaml

APP_NAME = "shopscrape"
DEFAULT_HOME = Path(os.environ.get("SHOPSCRAPE_HOME", Path.home() / ".shopscrape"))
CONFIG_PATH = Path(os.environ.get("SHOPSCRAPE_CONFIG", DEFAULT_HOME / "config.yml"))

_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class ConfigError(Exception):
    pass


def normalize_domain(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        raise ConfigError("Empty domain.")
    if "://" not in s:
        s = "https://" + s
    host = (urlparse(s).hostname or "").lower()
    if not host:
        raise ConfigError(f"Could not parse a hostname from {raw!r}")
    if host.startswith("www."):
        host = host[4:]
    return host


def slug_from_domain(domain: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", domain.split(".")[0].lower()) or "site"


@dataclass
class Site:
    key: str
    domain: str
    name: str = ""
    platform: str = "shopify"
    enabled: bool = True
    vendor_override: str = ""
    tag_prefix: str = ""
    extra_tags: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self):
        self.key = (self.key or "").strip().lower()
        if not _KEY_RE.match(self.key):
            raise ConfigError(
                f"Invalid site key {self.key!r}: use lowercase letters, digits, '-' or '_'."
            )
        self.domain = normalize_domain(self.domain)
        self.name = self.name or self.domain

    @property
    def base_url(self) -> str:
        return f"https://{self.domain}"


@dataclass
class Settings:
    delay: float = 0.6
    timeout: float = 30.0
    retries: int = 4
    page_size: int = 250
    max_pages: int = 400
    user_agent: str = ""
    proxy: str = ""
    output_dir: str = "exports"
    db_path: str = ""
    default_profile: str = "shopify-import"
    image_width: int = 0
    published_status: str = "Active"
    inventory_policy: str = "DENY"
    inventory_tracker: str = "shopify"
    fulfillment_service: str = "manual"
    default_qty_in_stock: int = 0
    price_multiplier: float = 1.0
    price_round: str = ""


@dataclass
class Config:
    settings: Settings = field(default_factory=Settings)
    sites: dict[str, Site] = field(default_factory=dict)
    path: Path = CONFIG_PATH

    @classmethod
    def load(cls, path: Path | None = None, *, create: bool = True) -> "Config":
        p = Path(path or CONFIG_PATH)
        if not p.exists():
            cfg = cls(path=p)
            if create:
                cfg.save()
            return cfg

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        s = Settings(**{k: v for k, v in (data.get("settings") or {}).items()
                        if k in Settings.__dataclass_fields__})
        sites: dict[str, Site] = {}
        for item in data.get("sites") or []:
            allowed = {k: v for k, v in item.items() if k in Site.__dataclass_fields__}
            site = Site(**allowed)
            sites[site.key] = site
        return cls(settings=s, sites=sites, path=p)

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "settings": asdict(self.settings),
            "sites": [asdict(s) for s in self.sites.values()],
        }
        header = (
            "# shopscrape configuration\n"
            "# Edit by hand or use:  shopctl sites add / set / remove\n"
            "# Docs:                 shopctl --help\n\n"
        )
        self.path.write_text(header + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
                             encoding="utf-8")
        return self.path

    def add(self, domain: str, *, key: str | None = None, name: str = "",
            platform: str = "shopify", **kw) -> Site:
        dom = normalize_domain(domain)
        for existing in self.sites.values():
            if existing.domain == dom:
                raise ConfigError(f"{dom} is already registered as '{existing.key}'.")
        k = (key or slug_from_domain(dom)).lower()
        base, n = k, 2
        while k in self.sites:
            k = f"{base}{n}"
            n += 1
        site = Site(key=k, domain=dom, name=name or dom, platform=platform, **kw)
        self.sites[k] = site
        return site

    def remove(self, key: str) -> Site:
        site = self.get(key)
        del self.sites[site.key]
        return site

    def get(self, key: str) -> Site:
        k = key.strip().lower()
        if k in self.sites:
            return self.sites[k]
        try:
            dom = normalize_domain(k)
        except ConfigError:
            dom = None
        if dom:
            for s in self.sites.values():
                if s.domain == dom:
                    return s
        raise ConfigError(f"Unknown site {key!r}. Run 'shopctl sites list' to see registered sites.")

    def resolve(self, keys: tuple[str, ...] | list[str] | None, *, only_enabled: bool = True) -> list[Site]:
        if not keys or (len(keys) == 1 and keys[0].lower() == "all"):
            pool = list(self.sites.values())
            return [s for s in pool if s.enabled] if only_enabled else pool
        out, seen = [], set()
        for k in keys:
            for part in str(k).split(","):
                part = part.strip()
                if not part:
                    continue
                site = self.get(part)
                if site.key not in seen:
                    seen.add(site.key)
                    out.append(site)
        return out

    @property
    def home(self) -> Path:
        return self.path.parent

    def db_file(self) -> Path:
        if self.settings.db_path:
            return Path(self.settings.db_path).expanduser()
        return self.home / "catalog.db"

    def out_dir(self) -> Path:
        p = Path(self.settings.output_dir).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        p.mkdir(parents=True, exist_ok=True)
        return p


SETTING_TYPES = {f: Settings.__dataclass_fields__[f].type for f in Settings.__dataclass_fields__}


def coerce_setting(field_name: str, value: str):
    if field_name not in Settings.__dataclass_fields__:
        raise ConfigError(
            f"Unknown setting {field_name!r}. Valid: {', '.join(sorted(Settings.__dataclass_fields__))}"
        )
    current = getattr(Settings(), field_name)
    if isinstance(current, bool):
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return str(value)
