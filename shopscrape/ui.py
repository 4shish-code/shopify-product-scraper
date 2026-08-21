from __future__ import annotations

import os
import shutil
import sys

from rich.console import Console
from rich.table import Table
from rich.theme import Theme
from rich.panel import Panel
from rich.text import Text

THEME = Theme({
    "ok": "bold green",
    "warn": "bold yellow",
    "err": "bold red",
    "dim": "grey62",
    "hi": "bold cyan",
    "key": "bold white",
})


def _width() -> int | None:
    env = os.environ.get("SHOPSCRAPE_WIDTH")
    if env and env.isdigit():
        return int(env)
    if sys.stdout.isatty():
        return None
    return max(shutil.get_terminal_size((130, 24)).columns, 130)


console = Console(theme=THEME, highlight=False, width=_width())


def banner(subtitle: str = "") -> None:
    art = Text()
    art.append("shopscrape", style="bold cyan")
    art.append("  ·  Shopify catalog → CSV\n", style="dim")
    if subtitle:
        art.append(subtitle, style="dim")
    console.print(Panel(art, border_style="cyan", padding=(0, 2)))


def table(title: str, columns: list[str], rows: list[list], *, styles: dict[int, str] | None = None) -> None:
    t = Table(title=title, title_style="bold", header_style="bold cyan",
              border_style="grey35", show_lines=False, pad_edge=False)
    styles = styles or {}
    for i, c in enumerate(columns):
        justify = "right" if styles.get(i) == "num" else "left"
        t.add_column(c, justify=justify, overflow="fold")
    for r in rows:
        t.add_row(*[Text(str(c)) if not isinstance(c, Text) else c for c in r])
    console.print(t)


def ok(msg: str) -> None:
    console.print(f"[ok]✓[/ok] {msg}")


def warn(msg: str) -> None:
    console.print(f"[warn]![/warn] {msg}")


def err(msg: str) -> None:
    console.print(f"[err]✗[/err] {msg}")


def info(msg: str) -> None:
    console.print(f"[dim]·[/dim] {msg}")


def kv(pairs: list[tuple[str, str]], title: str = "") -> None:
    t = Table.grid(padding=(0, 2))
    t.add_column(style="key", justify="right")
    t.add_column()
    for k, v in pairs:
        t.add_row(f"{k}:", str(v))
    console.print(Panel(t, title=title, border_style="grey35", padding=(0, 1)) if title else t)


def human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def money(v) -> str:
    try:
        return f"₹{float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"
