from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import click
from rich.progress import (BarColumn, Progress, SpinnerColumn, TextColumn,
                           TimeElapsedColumn)

from . import __version__
from .columns import PROFILES, PROFILE_HELP
from .config import Config, ConfigError, Site, coerce_setting
from .detect import detect
from .exporter import (build_rows, split_by_size, validate, write_csv,
                       write_image_manifest, write_json, write_xlsx)
from .fetcher import Fetcher
from .models import Product
from .source import SourceError, build_source
from .store import Store
from .transform import Filters, Rules, dedupe
from .ui import (banner, console, err, human_bytes, info, kv, money, ok,
                 table, warn)

CTX = dict(help_option_names=["-h", "--help"], max_content_width=100)


def _cfg(ctx) -> Config:
    return ctx.obj["cfg"]


def _fetcher(cfg: Config, verbose: bool = False) -> Fetcher:
    s = cfg.settings
    return Fetcher(delay=s.delay, timeout=s.timeout, retries=s.retries,
                   user_agent=s.user_agent or None, proxy=s.proxy or None,
                   verbose=verbose) if s.user_agent else Fetcher(
        delay=s.delay, timeout=s.timeout, retries=s.retries,
        proxy=s.proxy or None, verbose=verbose)


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M")


def _die(msg: str, code: int = 1):
    err(msg)
    sys.exit(code)


@click.group(context_settings=CTX, invoke_without_command=True)
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              help="Path to config.yml (default: ~/.shopscrape/config.yml)")
@click.option("-q", "--quiet", is_flag=True, help="Suppress banner.")
@click.version_option(__version__, "-V", "--version", prog_name="shopctl")
@click.pass_context
def cli(ctx, config_path, quiet):
    ctx.ensure_object(dict)
    try:
        ctx.obj["cfg"] = Config.load(config_path)
    except ConfigError as exc:
        _die(str(exc))
    ctx.obj["quiet"] = quiet

    if ctx.invoked_subcommand is None:
        if not quiet:
            banner(f"v{__version__}   ·   {len(ctx.obj['cfg'].sites)} sites registered")
        click.echo(ctx.get_help())


@cli.group()
def sites():
    pass


@sites.command("list")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.pass_context
def sites_list(ctx, as_json):
    cfg = _cfg(ctx)
    if not cfg.sites:
        warn("No sites registered. Add one:  shopctl sites add <domain>")
        return

    if as_json:
        import json as _j
        from dataclasses import asdict
        click.echo(_j.dumps([asdict(s) for s in cfg.sites.values()], indent=2))
        return

    store = Store(cfg.db_file())
    counts = {r["site_key"]: r["products"] for r in store.summary()}
    store.close()

    rows = []
    for s in cfg.sites.values():
        rows.append([
            s.key,
            s.domain,
            s.name,
            s.platform,
            "[ok]on[/ok]" if s.enabled else "[dim]off[/dim]",
            str(counts.get(s.key, "—")),
            ", ".join(s.collections) if s.collections else "[dim]all[/dim]",
        ])
    from rich.text import Text
    rows = [[Text.from_markup(str(c)) for c in r] for r in rows]
    table("Registered sites", ["KEY", "DOMAIN", "NAME", "PLATFORM", "ON", "IN DB", "COLLECTIONS"], rows)
    info(f"config: {cfg.path}")


@sites.command("add")
@click.argument("domain")
@click.option("--key", help="Identifier key for CLI commands.")
@click.option("--name", default="", help="Display name.")
@click.option("--no-verify", is_flag=True, help="Skip platform check.")
@click.option("--force", is_flag=True, help="Force addition without validation.")
@click.option("--vendor", default="", help="Override vendor column on export.")
@click.option("--tag-prefix", default="", help="Prefix every scraped tag.")
@click.option("--collection", "collections", multiple=True,
              help="Only scrape specific collection handles.")
@click.pass_context
def sites_add(ctx, domain, key, name, no_verify, force, vendor, tag_prefix, collections):
    cfg = _cfg(ctx)
    platform = "shopify"

    from .config import normalize_domain
    try:
        domain = normalize_domain(domain)
    except ConfigError as exc:
        _die(str(exc))

    for existing in cfg.sites.values():
        if existing.domain == domain:
            _die(f"{domain} is already registered as '{existing.key}'.")

    if not no_verify:
        with _fetcher(cfg) as f:
            with console.status(f"Checking {domain} …", spinner="dots"):
                d = detect(domain, f)
        if d.supported:
            ok(f"{d.domain} — Shopify confirmed" + (f"  (e.g. “{d.product_sample}”)" if d.product_sample else ""))
        else:
            err(f"{d.domain} — {d.note or 'not a supported Shopify store'}")
            if d.platform not in ("unknown", "shopify"):
                info(f"Detected platform: {d.platform}.")
            if not force:
                info("Use --force to add anyway or --no-verify to skip.")
                sys.exit(2)
            platform = d.platform if d.platform != "unknown" else "shopify"
            warn("Added with --force.")

    try:
        site = cfg.add(domain, key=key, name=name, platform=platform,
                       vendor_override=vendor, tag_prefix=tag_prefix,
                       collections=list(collections))
    except ConfigError as exc:
        _die(str(exc))

    cfg.save()
    ok(f"Added '[hi]{site.key}[/hi]' → {site.domain}")
    info(f"Next:  shopctl scrape --site {site.key}")


@sites.command("remove")
@click.argument("key")
@click.option("--purge", is_flag=True, help="Delete scraped data for this site.")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation.")
@click.pass_context
def sites_remove(ctx, key, purge, yes):
    cfg = _cfg(ctx)
    try:
        site = cfg.get(key)
    except ConfigError as exc:
        _die(str(exc))
    if not yes and not click.confirm(f"Remove '{site.key}' ({site.domain})?"):
        return
    cfg.remove(site.key)
    cfg.save()
    ok(f"Removed '{site.key}'")
    if purge:
        store = Store(cfg.db_file())
        n = store.purge(site.key)
        store.close()
        ok(f"Purged {n} products from database")


@sites.command("set")
@click.argument("key")
@click.option("--enable/--disable", default=None, help="Toggle enabled status.")
@click.option("--name", default=None)
@click.option("--vendor", default=None, help="Vendor override on export.")
@click.option("--tag-prefix", default=None)
@click.option("--add-tag", "add_tags", multiple=True, help="Append tag on export.")
@click.option("--clear-tags", is_flag=True)
@click.option("--collection", "collections", multiple=True, help="Limit to specific collections.")
@click.option("--all-collections", is_flag=True, help="Clear collection filter.")
@click.option("--notes", default=None)
@click.pass_context
def sites_set(ctx, key, enable, name, vendor, tag_prefix, add_tags, clear_tags,
              collections, all_collections, notes):
    cfg = _cfg(ctx)
    try:
        s = cfg.get(key)
    except ConfigError as exc:
        _die(str(exc))

    changed = []
    if enable is not None:
        s.enabled = enable; changed.append(f"enabled={enable}")
    if name is not None:
        s.name = name; changed.append("name")
    if vendor is not None:
        s.vendor_override = vendor; changed.append("vendor_override")
    if tag_prefix is not None:
        s.tag_prefix = tag_prefix; changed.append("tag_prefix")
    if clear_tags:
        s.extra_tags = []; changed.append("extra_tags cleared")
    if add_tags:
        s.extra_tags = list(dict.fromkeys(s.extra_tags + list(add_tags))); changed.append("extra_tags")
    if all_collections:
        s.collections = []; changed.append("collections cleared")
    if collections:
        s.collections = list(collections); changed.append("collections")
    if notes is not None:
        s.notes = notes; changed.append("notes")

    if not changed:
        warn("Nothing to update.")
        return
    cfg.save()
    ok(f"Updated '{s.key}' — {', '.join(changed)}")


@sites.command("collections")
@click.argument("key")
@click.pass_context
def sites_collections(ctx, key):
    cfg = _cfg(ctx)
    try:
        site = cfg.get(key)
    except ConfigError as exc:
        _die(str(exc))

    with _fetcher(cfg) as f:
        src = build_source(site, f)
        with console.status(f"Fetching collections from {site.domain} …", spinner="dots"):
            cols = src.collections()

    if not cols:
        warn("No public collections found.")
        return
    rows = [[c.get("handle", ""), c.get("title", ""), str(c.get("products_count", "—"))] for c in cols]
    rows.sort(key=lambda r: -(int(r[2]) if r[2].isdigit() else 0))
    table(f"Collections — {site.domain}", ["HANDLE", "TITLE", "PRODUCTS"], rows)


@cli.command()
@click.argument("targets", nargs=-1)
@click.option("--site", "site_opts", multiple=True, help="Site key (repeatable).")
@click.option("--limit", type=int, default=0, help="Max products per site.")
@click.option("--delay", type=float, default=None, help="Delay between requests.")
@click.option("--page-size", type=int, default=None, help="Products per request (max 250).")
@click.option("--dry-run", is_flag=True, help="Count products without saving.")
@click.option("--no-store", is_flag=True, help="Fetch but skip database store.")
@click.option("-v", "--verbose", is_flag=True, help="Verbose request logs.")
@click.pass_context
def scrape(ctx, targets, site_opts, limit, delay, page_size, dry_run, no_store, verbose):
    cfg = _cfg(ctx)
    keys = list(site_opts) + list(targets)
    try:
        chosen = cfg.resolve(keys)
    except ConfigError as exc:
        _die(str(exc))
    if not chosen:
        _die("No sites selected.")

    if delay is not None:
        cfg.settings.delay = delay
    if page_size is not None:
        cfg.settings.page_size = page_size

    if not ctx.obj["quiet"]:
        banner(f"scraping {len(chosen)} site(s)" + ("  ·  dry run" if dry_run else ""))

    store = None if (dry_run or no_store) else Store(cfg.db_file())
    fetcher = _fetcher(cfg, verbose)
    t0 = time.time()
    results: list[list] = []
    grand_total = 0
    failures = 0

    progress = Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold]{task.fields[site]:<14}[/bold]"),
        BarColumn(bar_width=26, complete_style="green"),
        TextColumn("{task.fields[status]}"),
        TimeElapsedColumn(),
        console=console, transient=False,
    )

    with progress, fetcher:
        for site in chosen:
            task = progress.add_task("scrape", total=None, site=site.key,
                                     status="[dim]connecting…[/dim]")
            run_id = store.start_run(site.key, site.domain) if store else -1
            got: list[Product] = []
            before = fetcher.stats["requests"]

            try:
                src = build_source(site, fetcher, page_size=cfg.settings.page_size,
                                   max_pages=cfg.settings.max_pages, limit=limit)

                def _tick(page, count, _t=task, _p=progress):
                    _p.update(_t, status=f"[dim]page {page} · {count} products[/dim]")

                for p in src.iter_products(on_page=_tick):
                    got.append(p)
                    if len(got) % 25 == 0:
                        progress.update(task, status=f"[dim]{len(got)} products[/dim]")

                nvar = sum(len(p.variants) for p in got)
                nimg = sum(len(p.images) for p in got)
                reqs = fetcher.stats["requests"] - before

                if store:
                    new, upd = store.upsert(got, run_id)
                    store.finish_run(run_id, products=len(got), variants=nvar,
                                     images=nimg, requests=reqs, status="ok")
                    detail = f"[ok]{len(got)}[/ok] products  [dim]({new} new, {upd} updated)[/dim]"
                else:
                    detail = f"[ok]{len(got)}[/ok] products  [dim](not stored)[/dim]"

                progress.update(task, status=detail, total=1, completed=1)
                results.append([site.key, str(len(got)), str(nvar), str(nimg), str(reqs), "[ok]ok[/ok]"])
                grand_total += len(got)

            except (SourceError, Exception) as exc:
                failures += 1
                msg = str(exc).split("\n")[0][:70]
                progress.update(task, status=f"[err]failed[/err] [dim]{msg}[/dim]", total=1, completed=1)
                results.append([site.key, "0", "0", "0", "—", "[err]failed[/err]"])
                if store:
                    store.finish_run(run_id, status="failed", error=str(exc)[:500])
                if verbose:
                    console.print_exception()

    from rich.text import Text
    table("Scrape summary",
          ["SITE", "PRODUCTS", "VARIANTS", "IMAGES", "REQUESTS", "STATUS"],
          [[Text.from_markup(str(c)) for c in r] for r in results])

    kv([
        ("Total products", f"{grand_total:,}"),
        ("HTTP requests", f"{fetcher.stats['requests']:,}  ({fetcher.stats['retries']} retries)"),
        ("Downloaded", human_bytes(fetcher.stats["bytes"])),
        ("Elapsed", f"{time.time() - t0:.1f}s"),
        ("Database", str(cfg.db_file()) if store else "not written"),
    ], title="Run")

    if store:
        store.close()
    if failures:
        warn(f"{failures} site(s) failed. Run 'shopctl doctor' to check.")
    elif not dry_run and grand_total:
        info(f"Next:  shopctl export --site {chosen[0].key}")
    if failures == len(chosen):
        sys.exit(1)


@cli.command()
@click.argument("targets", nargs=-1)
@click.option("--site", "site_opts", multiple=True, help="Site key (repeatable).")
@click.option("-o", "--output", type=click.Path(path_type=Path), help="Output file path.")
@click.option("-p", "--profile", type=click.Choice(list(PROFILES)), default=None,
              help="Column profile (default: shopify-import).")
@click.option("-f", "--format", "fmt", type=click.Choice(["csv", "xlsx", "json"]), default="csv")
@click.option("--split-by-site", is_flag=True, help="Write one file per site.")
@click.option("--max-rows", type=int, default=0, help="Split output into chunks of N rows.")
@click.option("--images-manifest", is_flag=True, help="Export images manifest CSV.")
@click.option("--query", default="", help="Filter by title substring.")
@click.option("--vendor", default="", help="Filter by vendor.")
@click.option("--type", "ptype", default="", help="Filter by product type.")
@click.option("--tag", default="", help="Filter by tag.")
@click.option("--min-price", type=float, default=None)
@click.option("--max-price", type=float, default=None)
@click.option("--in-stock", is_flag=True, help="Only in-stock products.")
@click.option("--with-images", is_flag=True, help="Only products with images.")
@click.option("--exclude", default="", help="Exclude regex pattern on title.")
@click.option("--limit", type=int, default=0, help="Cap product count.")
@click.option("--markup", type=float, default=None, help="Price multiplier factor.")
@click.option("--round-to", type=click.Choice(["", "int", "0.99", "9", "10"]), default=None,
              help="Price rounding style.")
@click.option("--vendor-as", default="", help="Override vendor name.")
@click.option("--add-tag", "add_tags", multiple=True, help="Append extra tag.")
@click.option("--title-prefix", default="")
@click.option("--title-suffix", default="")
@click.option("--status", type=click.Choice(["Active", "Draft", "Archived"]), default=None,
              help="Shopify product status.")
@click.option("--image-width", type=int, default=None, help="Shopify image width parameter.")
@click.option("--dedupe-by", type=click.Choice(["none", "handle", "title"]), default="none",
              help="Deduplication key.")
@click.option("--no-validate", is_flag=True, help="Skip format validation.")
@click.pass_context
def export(ctx, targets, site_opts, output, profile, fmt, split_by_site, max_rows,
           images_manifest, query, vendor, ptype, tag, min_price, max_price, in_stock,
           with_images, exclude, limit, markup, round_to, vendor_as, add_tags,
           title_prefix, title_suffix, status, image_width, dedupe_by, no_validate):
    cfg = _cfg(ctx)
    profile = profile or cfg.settings.default_profile
    keys = list(site_opts) + list(targets)

    try:
        chosen = cfg.resolve(keys, only_enabled=False)
    except ConfigError as exc:
        _die(str(exc))

    store = Store(cfg.db_file())
    products = store.load([s.key for s in chosen] if keys else None)
    store.close()

    if not products:
        _die("No products found in database. Run 'shopctl scrape all' first.")

    s = cfg.settings
    if status:
        s.published_status = status
    if image_width is not None:
        s.image_width = image_width

    filters = Filters(query=query, vendor=vendor, ptype=ptype, tag=tag,
                      min_price=min_price, max_price=max_price,
                      in_stock_only=in_stock, with_images_only=with_images,
                      exclude=exclude, limit=limit)
    before = len(products)
    products = filters.apply(products)
    if not products:
        _die(f"No products matched filters ({filters.describe()}).")

    products, dropped = dedupe(products, dedupe_by)

    by_site: dict[str, list[Product]] = {}
    for p in products:
        by_site.setdefault(p.site_key, []).append(p)

    if not ctx.obj["quiet"]:
        banner(f"export · {profile} · {fmt}")

    kv([
        ("Profile", f"{profile} — {PROFILE_HELP[profile]}"),
        ("Sites", ", ".join(sorted(by_site))),
        ("Products", f"{len(products):,}" + (f"  [dim](filtered from {before:,})[/dim]" if before != len(products) else "")),
        ("Filters", filters.describe()),
        ("Deduped", f"{dropped} removed by {dedupe_by}" if dropped else "off"),
        ("Status", s.published_status),
    ], title="Plan")

    ts = _stamp()
    out_dir = cfg.out_dir()
    written: list[tuple[Path, int]] = []

    groups = list(by_site.items()) if split_by_site else [("all" if len(by_site) > 1 else next(iter(by_site)), products)]

    for label, items in groups:
        site_cfg = cfg.sites.get(label)
        rules = Rules.from_settings(s, site_cfg)
        if markup is not None:
            rules.price_multiplier = markup
        if round_to is not None:
            rules.price_round = round_to
        if vendor_as:
            rules.vendor_override = vendor_as
        if add_tags:
            rules.add_tags = list(dict.fromkeys(rules.add_tags + list(add_tags)))
        rules.title_prefix = title_prefix
        rules.title_suffix = title_suffix

        prepared = [rules.apply(p) for p in items]

        if fmt == "json":
            path = Path(output) if (output and len(groups) == 1) else out_dir / f"{label}-{ts}.json"
            write_json(prepared, path)
            written.append((path, len(prepared)))
            continue

        rows, stats = build_rows(prepared, profile, s)

        if not no_validate:
            problems = validate(rows, profile)
            for p_ in problems:
                warn(p_)
            if problems and profile.startswith("shopify"):
                info("Use --no-validate to bypass format checks.")

        chunks = split_by_size(rows, max_rows)
        for ci, chunk in enumerate(chunks, start=1):
            suffix = f"-part{ci}" if len(chunks) > 1 else ""
            if output and len(groups) == 1 and len(chunks) == 1:
                path = Path(output)
            else:
                ext = "xlsx" if fmt == "xlsx" else "csv"
                path = out_dir / f"{label}-{profile}-{ts}{suffix}.{ext}"
            if fmt == "xlsx":
                write_xlsx(chunk, path, profile)
            else:
                write_csv(chunk, path, profile)
            written.append((path, len(chunk)))

        console.print(
            f"  [dim]{label}:[/dim] {stats.products} products → "
            f"[hi]{stats.rows}[/hi] rows  "
            f"[dim]({stats.variants} variants, {stats.images} images)[/dim]"
        )
        gaps = []
        if stats.missing_price:
            gaps.append(f"{stats.missing_price} without price")
        if stats.missing_sku:
            gaps.append(f"{stats.missing_sku} without SKU")
        if stats.missing_image:
            gaps.append(f"{stats.missing_image} without images")
        if gaps:
            console.print(f"  [dim]  gaps: {', '.join(gaps)}[/dim]")

    if images_manifest:
        mpath = out_dir / f"images-{ts}.csv"
        _, n = write_image_manifest(products, mpath)
        written.append((mpath, n))

    console.print()
    from rich.text import Text
    table("Files written",
          ["FILE", "ROWS", "SIZE"],
          [[Text(str(p)), Text(f"{n:,}"), Text(human_bytes(p.stat().st_size))] for p, n in written])

    if profile in ("shopify-import", "shopify-legacy") and fmt == "csv":
        info("Import via Shopify Admin → Products → Import")


@cli.command()
@click.option("--site", "site_opts", multiple=True)
@click.option("--top", type=int, default=10, help="Top N entries.")
@click.pass_context
def stats(ctx, site_opts, top):
    cfg = _cfg(ctx)
    store = Store(cfg.db_file())
    rows = store.summary()
    if not rows:
        store.close()
        _die("Database is empty. Run 'shopctl scrape all' first.")

    from rich.text import Text
    body, tp, tv, ti = [], 0, 0, 0
    for r in rows:
        tp += r["products"]; tv += r["variants"] or 0; ti += r["images"] or 0
        pct = (r["in_stock"] or 0) / r["products"] * 100 if r["products"] else 0
        body.append([
            r["site_key"], f"{r['products']:,}", f"{r['variants'] or 0:,}",
            f"{r['images'] or 0:,}", f"{pct:.0f}%",
            f"{money(r['min_price'])} – {money(r['max_price'])}",
            (r["last_seen"] or "")[:16].replace("T", " "),
        ])
    body.append(["[bold]TOTAL[/bold]", f"[bold]{tp:,}[/bold]", f"[bold]{tv:,}[/bold]",
                 f"[bold]{ti:,}[/bold]", "", "", ""])
    table("Catalog", ["SITE", "PRODUCTS", "VARIANTS", "IMAGES", "IN STOCK", "PRICE RANGE", "LAST SCRAPE"],
          [[Text.from_markup(str(c)) for c in r] for r in body])

    keys = [s.key for s in cfg.resolve(site_opts, only_enabled=False)] if site_opts else None
    products = store.load(keys)
    store.close()

    from collections import Counter
    vend = Counter(p.vendor or "—" for p in products).most_common(top)
    typs = Counter(p.product_type or "—" for p in products).most_common(top)
    tags = Counter(t for p in products for t in p.tags).most_common(top)

    if vend:
        table(f"Top {top} vendors", ["VENDOR", "PRODUCTS"], [[k, f"{v:,}"] for k, v in vend])
    if typs:
        table(f"Top {top} product types", ["TYPE", "PRODUCTS"], [[k, f"{v:,}"] for k, v in typs])
    if tags:
        table(f"Top {top} tags", ["TAG", "PRODUCTS"], [[k, f"{v:,}"] for k, v in tags])

    no_img = sum(1 for p in products if not p.images)
    no_sku = sum(1 for p in products for v in p.variants if not v.sku)
    on_sale = sum(1 for p in products for v in p.variants if v.on_sale)
    multi = sum(1 for p in products if len(p.variants) > 1)
    kv([
        ("Products without images", f"{no_img:,}"),
        ("Variants without SKU", f"{no_sku:,}"),
        ("Variants on sale", f"{on_sale:,}"),
        ("Products with variants", f"{multi:,}"),
    ], title="Data quality")


@cli.command()
@click.argument("term")
@click.option("--site", "site_opts", multiple=True)
@click.option("-n", type=int, default=5, help="Matches count.")
@click.pass_context
def inspect(ctx, term, site_opts, n):
    cfg = _cfg(ctx)
    store = Store(cfg.db_file())
    keys = [s.key for s in cfg.resolve(site_opts, only_enabled=False)] if site_opts else None
    products = store.load(keys)
    store.close()

    t = term.lower()
    hits = [p for p in products if t in p.title.lower() or t in p.handle.lower()][:n]
    if not hits:
        _die(f"No product matching '{term}'.")

    for p in hits:
        kv([
            ("Site", f"{p.site_key}  ({p.site_domain})"),
            ("Title", p.title),
            ("Handle", p.handle),
            ("Vendor", p.vendor or "—"),
            ("Type", p.product_type or "—"),
            ("Tags", ", ".join(p.tags) or "—"),
            ("Price", f"{money(p.price_min)}" + (f" – {money(p.price_max)}" if p.price_min != p.price_max else "")),
            ("In stock", "yes" if p.in_stock else "no"),
            ("URL", p.source_url),
        ], title=p.title[:70])

        if p.variants:
            table("Variants",
                  ["#", "TITLE", "SKU", "PRICE", "COMPARE-AT", "DISC%", "STOCK", "GRAMS"],
                  [[str(i), v.title or "—", v.sku or "—", money(v.price),
                    money(v.compare_at_price) if v.compare_at_price else "—",
                    f"{v.discount_pct}%" if v.on_sale else "—",
                    "yes" if v.available else "no", str(v.grams)]
                   for i, v in enumerate(p.variants, 1)])

        if p.images:
            table(f"Images ({len(p.images)})", ["POS", "URL"],
                  [[str(i.position), i.src] for i in p.images])
        else:
            warn("No images on this product.")

        desc = p.plain_description
        if desc:
            console.print(f"[dim]{desc[:400]}{'…' if len(desc) > 400 else ''}[/dim]\n")


@cli.command()
@click.option("--site", default=None, help="Filter by site.")
@click.option("--top", type=int, default=25)
@click.pass_context
def diff(ctx, site, top):
    cfg = _cfg(ctx)
    store = Store(cfg.db_file())
    key = cfg.get(site).key if site else None
    changes = store.price_changes(key, top)
    store.close()

    if not changes:
        info("No price changes recorded yet.")
        return

    from rich.text import Text
    rows = []
    for c in changes:
        pct = c["pct"] or 0
        arrow = "[err]▲[/err]" if pct > 0 else "[ok]▼[/ok]"
        rows.append([
            c["site_key"], (c["title"] or "")[:44], c["sku"] or "—",
            money(c["old_price"]), money(c["new_price"]),
            f"{arrow} {abs(pct):.1f}%", (c["seen_at"] or "")[:16].replace("T", " "),
        ])
    table("Price changes", ["SITE", "PRODUCT", "SKU", "WAS", "NOW", "CHANGE", "SEEN"],
          [[Text.from_markup(str(c)) for c in r] for r in rows])


@cli.command()
@click.option("--site", default=None)
@click.option("-n", type=int, default=15)
@click.pass_context
def runs(ctx, site, n):
    cfg = _cfg(ctx)
    store = Store(cfg.db_file())
    key = cfg.get(site).key if site else None
    rs = store.runs(n, key)
    store.close()
    if not rs:
        info("No runs recorded yet.")
        return

    from rich.text import Text
    rows = []
    for r in rs:
        st = "[ok]ok[/ok]" if r["status"] == "ok" else (
            "[warn]running[/warn]" if r["status"] == "running" else "[err]failed[/err]")
        dur = ""
        if r["finished_at"] and r["started_at"]:
            try:
                d = datetime.fromisoformat(r["finished_at"]) - datetime.fromisoformat(r["started_at"])
                dur = f"{d.total_seconds():.0f}s"
            except ValueError:
                pass
        rows.append([str(r["id"]), r["site_key"], (r["started_at"] or "")[:16].replace("T", " "),
                     dur, f"{r['products']:,}", f"{r['variants']:,}", f"{r['images']:,}", st])
    table("Scrape runs", ["ID", "SITE", "STARTED", "TOOK", "PRODUCTS", "VARIANTS", "IMAGES", "STATUS"],
          [[Text.from_markup(str(c)) for c in r] for r in rows])


@cli.command()
@click.option("--site", "site_opts", multiple=True)
@click.pass_context
def doctor(ctx, site_opts):
    cfg = _cfg(ctx)
    chosen = cfg.resolve(site_opts, only_enabled=False)
    if not ctx.obj["quiet"]:
        banner(f"checking {len(chosen)} site(s)")

    from rich.text import Text
    rows, bad = [], 0
    with _fetcher(cfg) as f:
        for s in chosen:
            with console.status(f"Checking {s.domain} …", spinner="dots"):
                d = detect(s.domain, f)
            if d.supported:
                verdict, note = "[ok]healthy[/ok]", d.product_sample or ""
            else:
                bad += 1
                verdict, note = "[err]problem[/err]", d.note
            rows.append([s.key, s.domain, d.platform, verdict, note[:52]])

    table("Health check", ["SITE", "DOMAIN", "PLATFORM", "STATUS", "NOTE"],
          [[Text.from_markup(str(c)) for c in r] for r in rows])
    if bad:
        warn(f"{bad} site(s) need attention.")
    else:
        ok("All sites are reachable and expose /products.json")


@cli.group("config")
def config_grp():
    pass


@config_grp.command("show")
@click.pass_context
def config_show(ctx):
    cfg = _cfg(ctx)
    from dataclasses import asdict
    kv([(k, str(v) if v != "" else "[dim](unset)[/dim]") for k, v in asdict(cfg.settings).items()],
       title=f"Settings — {cfg.path}")
    info(f"Database: {cfg.db_file()}")
    info(f"Exports:  {cfg.out_dir()}")


@config_grp.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx, key, value):
    cfg = _cfg(ctx)
    try:
        setattr(cfg.settings, key, coerce_setting(key, value))
    except (ConfigError, ValueError) as exc:
        _die(str(exc))
    cfg.save()
    ok(f"{key} = {getattr(cfg.settings, key)}")


@config_grp.command("path")
@click.pass_context
def config_path_cmd(ctx):
    click.echo(_cfg(ctx).path)


@config_grp.command("profiles")
def config_profiles():
    table("Export profiles", ["PROFILE", "COLUMNS", "DESCRIPTION"],
          [[k, str(len(v)), PROFILE_HELP[k]] for k, v in PROFILES.items()])


@cli.command()
@click.option("--site", default=None, help="Purge only this site.")
@click.option("--all", "all_sites", is_flag=True, help="Purge every site.")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation.")
@click.pass_context
def purge(ctx, site, all_sites, yes):
    cfg = _cfg(ctx)
    if site and all_sites:
        err("Use either --site or --all, not both.")
        sys.exit(2)
    if not site and not all_sites:
        err("Specify --all or --site <key>.")
        sys.exit(2)
    key = cfg.get(site).key if site else None
    what = f"site '{key}'" if key else "ALL sites"
    if not yes and not click.confirm(f"Delete scraped data for {what}?"):
        return
    store = Store(cfg.db_file())
    n = store.purge(key)
    store.close()
    ok(f"Deleted {n:,} products")


def main():
    try:
        cli(obj={})
    except KeyboardInterrupt:
        console.print("\n[warn]Interrupted.[/warn]")
        sys.exit(130)


if __name__ == "__main__":
    main()
