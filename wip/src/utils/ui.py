"""Terminal layout for the WIP scrapers.

Every line the scrapers print goes through here so the look stays
consistent across filling.py, loss.py and komponen.py:

    ── sesi ───────────────────────────────

      laporan    Loss
      tanggal    2026-11-16

    ┌ LOSS                          15 bagian
    │
    │   ✓   1/15   CUTTING 2        12 baris
    │   ·   2/15   TAMBAH PART      kosong
    │   ‼   3/15   RE-CASTING       halaman error
    │
    └ ■ selesai   14/15 bagian   245 baris   1m02s
"""

import os
import sys
import time

from datetime import datetime

from rich.console import Console
from rich.live import Live
from rich.markup import escape
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text


def _force_utf8(stream):
    """Make redirected output UTF-8 so symbols like ✓ ✗ · never crash.

    When output is not a terminal (e.g. piped to a log file), Rich falls
    back to the stream encoding, which on Windows is often cp1252.
    """

    reconfigure = getattr(stream, "reconfigure", None)

    if reconfigure is None:
        return

    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        pass


_force_utf8(sys.stdout)
_force_utf8(sys.stderr)


console = Console()


AUTHOR = "yuxxeun"
TAGLINE = "Routine scraper · Selenium / Chrome → Excel"

# Width of rules and block headers. Kept modest so the layout looks the
# same on wide terminals.
LAYOUT_WIDTH = 64

GUTTER = "[dim]│[/dim]"


def _width():
    return max(30, min(console.width, LAYOUT_WIDTH))


def format_duration(seconds):
    """Format seconds as '1h02m', '8m03s' or '12s'."""

    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)

    if hours:
        return f"{hours}h{minutes:02d}m"

    if minutes:
        return f"{minutes}m{secs:02d}s"

    return f"{secs}s"


def first_line(text, limit=70):
    """Shorten long Selenium messages to a single readable line."""

    text = str(text or "").strip()
    line = text.splitlines()[0] if text else ""

    if len(line) > limit:
        line = line[: limit - 1] + "…"

    return line


# ============================================================
# BANNER
# ============================================================

_LETTERS = {
    "W": [
        "██╗    ██╗",
        "██║    ██║",
        "██║ █╗ ██║",
        "██║███╗██║",
        "╚███╔███╔╝",
        " ╚══╝╚══╝ ",
    ],
    "I": [
        "██╗",
        "██║",
        "██║",
        "██║",
        "██║",
        "╚═╝",
    ],
    "P": [
        "██████╗ ",
        "██╔══██╗",
        "██████╔╝",
        "██╔═══╝ ",
        "██║     ",
        "╚═╝     ",
    ],
}


def banner(report, word="WIP"):
    """Print the big WIP logo, author and the report being run."""

    rows = [
        "".join(_LETTERS[ch][row] for ch in word)
        for row in range(6)
    ]

    console.print()

    if console.width >= len(rows[0]) + 2:

        for row in rows:
            text = Text("  ")
            for char in row:
                # Solid blocks bright, box-drawing "shadow" darker.
                text.append(
                    char,
                    style="bold cyan" if char == "█" else "dark_cyan",
                )
            console.print(text, no_wrap=True, overflow="crop")

    else:
        console.print(f"  [bold cyan]{word}[/bold cyan]")

    console.print()
    console.print(
        f"  [dim]by[/dim] [bold white]{AUTHOR}[/bold white]"
        f"   [dim]·[/dim]   [bold cyan]{escape(report)}[/bold cyan]"
    )
    console.print(f"  [dim]{TAGLINE}[/dim]")


# ============================================================
# SECTIONS & FIELDS
# ============================================================

def section(title):
    """── title ─────────────────────"""

    label = f"── {title} "
    fill = "─" * max(4, _width() - len(label))

    console.print()
    console.print(f"[dim]{label}{fill}[/dim]")
    console.print()


def field(label, value):
    """  label      value"""

    console.print(f"  [dim]{label:<10}[/dim] {value}")


def ok(message, detail=""):
    """  ✓  message  detail"""

    suffix = f"   [dim]{detail}[/dim]" if detail else ""
    console.print(f"  [green]✓[/green]  {message}{suffix}")


def fail(message, detail=""):
    """  ✗  message
         detail"""

    console.print(f"  [red]✗[/red]  {message}")

    if detail:
        console.print(f"     [dim]{escape(first_line(detail))}[/dim]")


def warn(message):
    console.print(f"  [yellow]![/yellow]  {message}")


def ask_date():
    """Ask for a YYYY-MM-DD date; empty input means today."""

    today = datetime.today().strftime("%Y-%m-%d")

    console.print()

    while True:

        value = console.input(
            f"  [cyan]?[/cyan] [bold]tanggal[/bold] "
            f"[dim](YYYY-MM-DD · enter = {today})[/dim] [cyan]›[/cyan] "
        ).strip()

        if not value:
            return today

        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            console.print(
                f"    [red]✗[/red] [dim]format salah: {escape(value)}[/dim]"
            )


# ============================================================
# SCRAPE BLOCK
# ============================================================

def _counter(number, total):
    width = len(str(total))
    return f"{number:>{width}}/{total}"


def block_header(name, right=""):
    """
    ┌ LOSS                          15 bagian
    │
    """

    gap = " " * max(2, _width() - 2 - len(name) - len(right))

    console.print(
        f"[dim]┌[/dim] [bold white]{escape(name)}[/bold white]"
        f"{gap}[dim]{escape(right)}[/dim]",
        no_wrap=True,
        overflow="crop",
    )
    console.print(GUTTER)


def _item(icon, number, total, name, detail, name_style=""):
    label = f"{escape(name):<20}"
    if name_style:
        label = f"[{name_style}]{label}[/{name_style}]"

    console.print(
        f"{GUTTER}   {icon}  [dim]{_counter(number, total)}[/dim]   "
        f"{label} {detail}",
        no_wrap=True,
        overflow="ellipsis",
    )


def item_ok(number, total, name, rows):
    _item("[green]✓[/green]", number, total, name, f"[dim]{rows} baris[/dim]")


def item_empty(number, total, name):
    _item("[dim]·[/dim]", number, total, name, "[dim]kosong[/dim]", "dim")


def item_warn(number, total, name, reason):
    _item(
        "[yellow]‼[/yellow]", number, total, name,
        f"[yellow]{escape(reason)}[/yellow]",
    )


def item_fail(number, total, name, reason):
    _item(
        "[red]✗[/red]", number, total, name,
        f"[dim]{escape(first_line(reason, 50))}[/dim]", "red",
    )


def block_note(message, icon="!", color="yellow"):
    """│        ! message"""

    console.print(
        f"{GUTTER}        [{color}]{icon}[/{color}]  [dim]{message}[/dim]",
        no_wrap=True,
        overflow="ellipsis",
    )


def block_footer(done, total, rows, empty, failed, duration):
    """
    │
    └ ■ selesai   14/15 bagian   245 baris   1 kosong   1m02s
    """

    if failed:
        color, label = "yellow", "sebagian"
    elif rows:
        color, label = "green", "selesai"
    else:
        color, label = "yellow", "kosong"

    extras = []
    if empty:
        extras.append(f"[dim]{empty} kosong[/dim]")
    if failed:
        extras.append(f"[red]{failed} gagal[/red]")

    console.print(GUTTER)
    console.print(
        f"[dim]└[/dim] [{color}]■ {label}[/{color}]   "
        f"[bold white]{done}/{total} bagian[/bold white]   "
        f"[bold white]{rows}[/bold white] baris   "
        + ("   ".join(extras) + "   " if extras else "")
        + f"[dim]{format_duration(duration)}[/dim]",
        no_wrap=True,
        overflow="ellipsis",
    )


# ============================================================
# ACTIVITY SPINNER
# ============================================================

class Activity:
    """Animated line showing what is happening right now.

    │   ⠋ memuat CUTTING 2 · 1/15

    It disappears when stopped, so only the permanent lines remain.
    """

    def __init__(self, markup="", gutter=True):

        self._prefix = f"{GUTTER}   " if gutter else "  "
        self._spinner = Spinner("dots", style="cyan")

        # Keep the activity on one line: long labels are cut with "…"
        # instead of wrapping, which would leave stray lines behind.
        grid = Table.grid()
        grid.add_column(no_wrap=True, width=4 if gutter else 2)
        grid.add_column(no_wrap=True, overflow="ellipsis")
        grid.add_row(Text.from_markup(self._prefix), self._spinner)

        self._live = Live(
            grid,
            console=console,
            transient=True,
            refresh_per_second=12.5,
        )

        self.update(markup)

    def update(self, markup):
        text = Text.from_markup(markup)
        text.no_wrap = True
        text.truncate(max(10, console.width - 7), overflow="ellipsis")
        self._spinner.update(text=text)

    def __enter__(self):
        self._live.start()
        return self

    def __exit__(self, *exc):
        self._live.stop()


# ============================================================
# RESULT
# ============================================================

def no_data():
    fail("Tidak ada data yang terkumpul")
    console.print("     [dim]· tanggal mungkin belum ada record[/dim]")
    console.print("     [dim]· struktur halaman mungkin berubah[/dim]")
    console.print("     [dim]· koneksi timeout / halaman gagal dimuat[/dim]")


def saved(filename, rows):
    size_kb = os.path.getsize(filename) / 1024

    ok("File tersimpan")
    console.print()
    field("file", f"[bold white]{escape(os.path.basename(filename))}[/bold white]")
    field("baris", f"[bold white]{rows}[/bold white]")
    field("ukuran", f"{size_kb:.1f} KB")
    field("folder", f"[dim]{escape(os.path.dirname(filename))}[/dim]")


def crashed(error):
    fail("Terjadi kesalahan", str(error))

    if "chromedriver" in str(error).lower() or "session not created" in str(error).lower():
        console.print(
            "     [yellow]→[/yellow] versi driver mungkin tidak cocok, jalankan "
            "[bold cyan]just update-driver[/bold cyan]"
        )

    console.print()
    console.print_exception(max_frames=4)


def finish_plain(started_at, success=True):
    """Closing line for tools that don't leave a browser open."""

    duration = format_duration(time.monotonic() - started_at)

    console.print()

    if success:
        console.print(f"[green]✓[/green] Selesai · [dim]{duration}[/dim]")
    else:
        console.print(f"[red]✗[/red] Gagal · [dim]{duration}[/dim]")

    console.print()


def finish(started_at, success):
    duration = format_duration(time.monotonic() - started_at)

    console.print()

    if success:
        console.print(
            f"[green]✓[/green] Selesai · [dim]{duration} · "
            "browser dibiarkan terbuka untuk dicek manual[/dim]"
        )
    else:
        console.print(
            f"[yellow]![/yellow] Selesai dengan masalah · [dim]{duration} · "
            "cek pesan di atas[/dim]"
        )

    console.print()
