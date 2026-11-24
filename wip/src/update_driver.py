"""Download the chromedriver that matches the installed Google Chrome.

Usage:
    just update-driver                    match the installed Chrome version
    just update-driver --latest           newest Stable driver
    just update-driver --version 157.0.8103.78
    just update-driver --force            download even if already up to date

Steps:
1. Read the installed Chrome version from the Windows registry.
2. Read the version of the driver CHROMEDRIVER_PATH (.env) points to.
3. Find the best matching build on Chrome for Testing
   (https://googlechromelabs.github.io/chrome-for-testing/):
   exact version → newest patch of the same build → newest of the same
   major version.
4. Download chromedriver-<platform>.zip into driver/<version>/.
5. Point CHROMEDRIVER_PATH in .env at the new driver.

Older driver folders are kept, so you can switch back by editing .env.
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

from utils import ui
from utils.ui import console, escape


SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SRC_DIR)
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")
ENV_EXAMPLE_FILE = os.path.join(PROJECT_ROOT, ".env.example")
DRIVER_ROOT = os.path.join(PROJECT_ROOT, "driver")

CFT_HOST = "https://googlechromelabs.github.io/chrome-for-testing"
CFT_KNOWN_GOOD = f"{CFT_HOST}/known-good-versions-with-downloads.json"
CFT_LAST_GOOD = f"{CFT_HOST}/last-known-good-versions-with-downloads.json"
CFT_PER_BUILD = f"{CFT_HOST}/latest-patch-versions-per-build-with-downloads.json"
CFT_PER_MILESTONE = f"{CFT_HOST}/latest-versions-per-milestone-with-downloads.json"

DRIVER_EXE = "chromedriver.exe"
ENV_KEY = "CHROMEDRIVER_PATH"
USER_AGENT = "wip-update-driver"

VERSION_RE = re.compile(r"\d+\.\d+\.\d+\.\d+")

# Registry locations that hold the installed Chrome (stable) version.
_CHROME_GUID = "{8A69D345-D564-463c-AFF1-A69D9E530F96}"
_CHROME_REGISTRY = [
    ("HKEY_CURRENT_USER", r"Software\Google\Chrome\BLBeacon", "version"),
    ("HKEY_LOCAL_MACHINE", rf"SOFTWARE\WOW6432Node\Google\Update\Clients\{_CHROME_GUID}", "pv"),
    ("HKEY_LOCAL_MACHINE", rf"SOFTWARE\Google\Update\Clients\{_CHROME_GUID}", "pv"),
    ("HKEY_CURRENT_USER", rf"Software\Google\Update\Clients\{_CHROME_GUID}", "pv"),
]


class DriverUpdateError(Exception):
    pass


# ============================================================
# VERSIONS
# ============================================================

def installed_chrome_version():
    """Installed Google Chrome version, or None if not found."""

    try:
        import winreg
    except ImportError:
        return None

    for hive_name, key_path, value_name in _CHROME_REGISTRY:
        try:
            with winreg.OpenKey(getattr(winreg, hive_name), key_path) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
        except OSError:
            continue

        match = VERSION_RE.search(str(value))
        if match:
            return match.group(0)

    return None


def driver_version(path):
    """Version reported by `chromedriver --version`, or None."""

    if not path or not os.path.isfile(path):
        return None

    try:
        output = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None

    match = VERSION_RE.search(output or "")
    return match.group(0) if match else None


def major_of(version):
    return version.split(".")[0] if version else None


def build_of(version):
    return ".".join(version.split(".")[:3]) if version else None


# ============================================================
# CHROME FOR TESTING
# ============================================================

def cft_platform():
    machine = platform.machine().lower()

    if machine in {"amd64", "x86_64", "arm64", "aarch64"}:
        # Chrome for Testing has no Windows arm64 build; win64 runs fine
        # under emulation.
        return "win64"

    return "win32"


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise DriverUpdateError(f"gagal membaca {url} ({error.code})") from None
    except urllib.error.URLError as error:
        raise DriverUpdateError(
            f"tidak bisa menghubungi Chrome for Testing ({error.reason})"
        ) from None


def _driver_url(entry):
    """chromedriver download URL for this platform in a CfT entry, or None."""

    for item in (entry or {}).get("downloads", {}).get("chromedriver", []):
        if item.get("platform") == cft_platform():
            return item.get("url")

    return None


def latest_stable():
    """(version, url) of the newest Stable chromedriver."""

    data = fetch_json(CFT_LAST_GOOD)
    entry = data.get("channels", {}).get("Stable")
    url = _driver_url(entry)

    if not entry or not url:
        raise DriverUpdateError("versi Stable terbaru tidak bisa dibaca")

    return entry["version"], url


def find_for(version):
    """(version, url, note) of the best chromedriver for a Chrome version.

    exact → newest patch of the same build → newest of the same major.
    """

    known = fetch_json(CFT_KNOWN_GOOD).get("versions", [])
    for entry in known:
        if entry.get("version") == version and _driver_url(entry):
            return version, _driver_url(entry), None

    per_build = fetch_json(CFT_PER_BUILD).get("builds", {})
    entry = per_build.get(build_of(version))
    if _driver_url(entry):
        return entry["version"], _driver_url(entry), f"build {build_of(version)}"

    per_major = fetch_json(CFT_PER_MILESTONE).get("milestones", {})
    entry = per_major.get(major_of(version))
    if _driver_url(entry):
        return entry["version"], _driver_url(entry), f"major {major_of(version)}"

    raise DriverUpdateError(
        f"tidak ada chromedriver untuk Chrome {version} di Chrome for Testing"
    )


# ============================================================
# .env
# ============================================================

def read_env_value(key):
    """Raw value of ``key`` in .env, or None."""

    if not os.path.isfile(ENV_FILE):
        return None

    with open(ENV_FILE, "r", encoding="utf-8-sig") as file:
        for line in file:
            stripped = line.strip()
            if stripped.startswith(f"{key}="):
                return stripped.split("=", 1)[1].strip().strip("\"'")

    return None


def resolve_project_path(value):
    if not value:
        return None

    path = os.path.expandvars(os.path.expanduser(value))

    if not os.path.isabs(path):
        path = os.path.join(PROJECT_ROOT, path)

    path = os.path.abspath(path)

    if os.path.isdir(path):
        path = os.path.join(path, DRIVER_EXE)

    return path


def write_env_value(key, value):
    """Set ``key="value"`` in .env, keeping every other line as it is."""

    if not os.path.isfile(ENV_FILE):
        if os.path.isfile(ENV_EXAMPLE_FILE):
            shutil.copyfile(ENV_EXAMPLE_FILE, ENV_FILE)
        else:
            open(ENV_FILE, "w", encoding="utf-8").close()

    with open(ENV_FILE, "rb") as file:
        raw = file.read()

    newline = "\r\n" if b"\r\n" in raw else "\n"
    lines = raw.decode("utf-8-sig").splitlines()

    new_line = f'{key}="{value}"'

    for index, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[index] = new_line
            break
    else:
        lines.append(new_line)

    with open(ENV_FILE, "w", encoding="utf-8", newline="") as file:
        file.write(newline.join(lines) + newline)


# ============================================================
# DOWNLOAD
# ============================================================

def download(url, destination):
    """Download ``url`` to ``destination`` with a spinner + progress."""

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    with urllib.request.urlopen(request, timeout=60) as response:

        total = int(response.headers.get("Content-Length") or 0)
        done = 0

        with open(destination, "wb") as file, ui.Activity(
            "[cyan]mengunduh[/cyan]", gutter=False
        ) as activity:

            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break

                file.write(chunk)
                done += len(chunk)

                size = f"{done / 1_048_576:.1f}"
                if total:
                    size += f" / {total / 1_048_576:.1f} MB"
                    size += f" · {done * 100 // total}%"
                else:
                    size += " MB"

                activity.update(f"[cyan]mengunduh[/cyan] [dim]{size}[/dim]")

    return done


def install(version, url, force=False):
    """Download and extract chromedriver into driver/<version>/.

    Returns the path of the extracted chromedriver.exe.
    """

    target_dir = os.path.join(DRIVER_ROOT, version)
    exe_path = os.path.join(target_dir, DRIVER_EXE)

    if os.path.isfile(exe_path) and not force:
        ui.field("folder", f"[dim]driver {version} sudah ada, tidak diunduh ulang[/dim]")
        return exe_path

    host = url.split("/")[2] if "://" in url else ""
    ui.field(
        "unduh",
        f"{escape(os.path.basename(url))} [dim]· {escape(host)}[/dim]",
    )

    os.makedirs(DRIVER_ROOT, exist_ok=True)

    # Download and extract into a temporary folder first, so a failed
    # download never leaves a half-finished driver folder behind.
    staging = tempfile.mkdtemp(prefix=".download-", dir=DRIVER_ROOT)

    try:
        started = time.monotonic()
        zip_path = os.path.join(staging, "chromedriver.zip")
        size = download(url, zip_path)

        ui.ok(
            "Terunduh",
            f"{size / 1_048_576:.1f} MB · "
            f"{ui.format_duration(time.monotonic() - started)}",
        )

        # The zip holds chromedriver-win64/{chromedriver.exe, LICENSE...}.
        # Flatten it so every file sits directly in driver/<version>/.
        files_dir = os.path.join(staging, "files")
        os.makedirs(files_dir)

        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                name = os.path.basename(member.filename)
                with archive.open(member) as src, open(
                    os.path.join(files_dir, name), "wb"
                ) as dst:
                    shutil.copyfileobj(src, dst)

        if not os.path.isfile(os.path.join(files_dir, DRIVER_EXE)):
            raise DriverUpdateError(f"{DRIVER_EXE} tidak ada di dalam zip")

        if os.path.isdir(target_dir):
            shutil.rmtree(target_dir)

        os.replace(files_dir, target_dir)

    except urllib.error.HTTPError as error:
        raise DriverUpdateError(f"unduhan gagal ({error.code}) untuk {url}") from None

    except urllib.error.URLError as error:
        raise DriverUpdateError(f"tidak bisa mengunduh driver ({error.reason})") from None

    finally:
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)

    return exe_path


# ============================================================
# MAIN
# ============================================================

def _version_label(version, missing):
    if version:
        return f"[bold white]{version}[/bold white]"
    return f"[yellow]{missing}[/yellow]"


def activate(exe_path, target):
    """Verify the driver at ``exe_path`` reports ``target`` and point
    CHROMEDRIVER_PATH in .env at it. Returns the relative path written."""

    installed = driver_version(exe_path)

    if installed != target:
        raise DriverUpdateError(
            f"{exe_path} melaporkan {installed or 'tidak diketahui'}, harusnya {target}"
        )

    relative = os.path.relpath(exe_path, PROJECT_ROOT).replace(os.sep, "/")
    write_env_value(ENV_KEY, relative)
    return relative


def check():
    """Pre-run check used by `just run`.

    Compares the installed Chrome with the driver in CHROMEDRIVER_PATH.
    Matching → continue. Different → switch to an already downloaded
    driver/<chrome>/ if there is one, otherwise download the matching
    driver, then update .env. Returns 0 to continue, 1 to stop.
    """

    started = time.monotonic()

    ui.section("cek driver")

    chrome = installed_chrome_version()
    current_path = resolve_project_path(read_env_value(ENV_KEY))
    current = driver_version(current_path)

    ui.field("chrome", _version_label(chrome, "tidak ditemukan"))
    ui.field("driver", _version_label(current, "belum ada / tidak terbaca"))

    if not chrome:
        console.print()
        ui.warn("Versi Chrome tidak terbaca; pengecekan driver dilewati.")
        return 0

    if current == chrome:
        console.print()
        ui.ok("Versi cocok", chrome)
        return 0

    try:

        # 1. A driver for this exact Chrome version is already downloaded.
        local_exe = os.path.join(DRIVER_ROOT, chrome, DRIVER_EXE)

        if driver_version(local_exe) == chrome:
            target, exe_path = chrome, local_exe
            ui.field("target", f"[bold white]{target}[/bold white] [dim](sudah ada di driver/)[/dim]")

        # 2. Ask Chrome for Testing for the best match.
        else:
            with ui.Activity(f"[cyan]mencari driver untuk[/cyan] {chrome}", gutter=False):
                target, url, note = find_for(chrome)

            ui.field("target", f"[bold white]{target}[/bold white]")

            if note:
                ui.field("catatan", f"[dim]{chrome} tidak ada · pakai terbaru {note}[/dim]")

            if current == target:
                console.print()
                ui.ok("Versi cocok", f"{target} [dim](driver terdekat untuk Chrome {chrome})[/dim]")
                return 0

            console.print()
            exe_path = install(target, url)

        relative = activate(exe_path, target)

    except (DriverUpdateError, OSError) as error:
        console.print()

        if current and major_of(current) == major_of(chrome):
            # Same major version still works with Selenium; don't block
            # the run just because the update could not be fetched.
            ui.warn(f"Driver tidak bisa diperbarui ({error}); lanjut pakai {current}.")
            return 0

        ui.fail("Driver tidak cocok dan gagal diperbarui", str(error))
        ui.finish_plain(started, success=False)
        return 1

    console.print()
    ui.ok("Driver diperbarui", f"{current or '-'} → [bold white]{target}[/bold white]")
    ui.field(".env", f'{ENV_KEY}="{escape(relative)}"')
    return 0


def main(argv=None):

    parser = argparse.ArgumentParser(
        description="Download the chromedriver matching the installed "
        "Google Chrome and point CHROMEDRIVER_PATH at it.",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--latest",
        action="store_true",
        help="download the newest Stable driver instead of matching Chrome",
    )
    group.add_argument(
        "--version",
        metavar="X.Y.Z.W",
        help="download the driver for this Chrome version",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="download again even if already up to date",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="pre-run check: compare Chrome and driver, update only if they differ",
    )

    args = parser.parse_args(argv)

    if args.check:
        return check()

    if args.version and not VERSION_RE.fullmatch(args.version.strip()):
        parser.error(f"versi tidak valid: {args.version!r}")

    started = time.monotonic()

    ui.banner("Update driver")

    # --------------------------------------------------------
    # Current state
    # --------------------------------------------------------

    ui.section("versi")

    chrome = installed_chrome_version()
    current_path = resolve_project_path(read_env_value(ENV_KEY))
    current = driver_version(current_path)

    try:
        with ui.Activity("[cyan]cek Chrome for Testing[/cyan]", gutter=False):
            latest, latest_url = latest_stable()
    except DriverUpdateError:
        latest = latest_url = None

    ui.field("chrome", _version_label(chrome, "tidak ditemukan"))
    ui.field("driver", _version_label(current, "belum ada / tidak terbaca"))
    ui.field(
        "stable",
        f"{latest} [dim](terbaru di Chrome for Testing)[/dim]"
        if latest else "[dim]tidak bisa dicek[/dim]",
    )
    ui.field("platform", cft_platform())

    if chrome and latest and major_of(chrome) != major_of(latest) and not args.latest:
        console.print(
            f"  {'':<10} [dim]Chrome belum update ke Stable terbaru; "
            "driver ikut versi Chrome.[/dim]"
        )

    # --------------------------------------------------------
    # Pick the version to install
    # --------------------------------------------------------

    ui.section("driver")

    try:

        if args.latest:
            if not latest:
                raise DriverUpdateError("versi Stable terbaru tidak bisa dibaca")
            target, url, note = latest, latest_url, None
        else:
            wanted = args.version.strip() if args.version else chrome
            if not wanted:
                raise DriverUpdateError(
                    "Google Chrome tidak ditemukan. Pakai --latest atau --version."
                )
            with ui.Activity(f"[cyan]mencari driver untuk[/cyan] {wanted}", gutter=False):
                target, url, note = find_for(wanted)

        ui.field("target", f"[bold white]{target}[/bold white]")

        if note:
            ui.field(
                "catatan",
                f"[dim]{wanted} tidak ada · pakai terbaru {note}[/dim]",
            )

        if current == target and not args.force:
            console.print()
            ui.ok("Driver sudah terbaru", target)
            ui.finish_plain(started)
            return 0

        console.print()
        exe_path = install(target, url, force=args.force)

    except DriverUpdateError as error:
        console.print()
        ui.fail(str(error))
        ui.finish_plain(started, success=False)
        return 1

    # --------------------------------------------------------
    # Verify and update .env
    # --------------------------------------------------------

    try:
        relative = activate(exe_path, target)
    except DriverUpdateError as error:
        ui.fail("Versi driver tidak sesuai", str(error))
        ui.finish_plain(started, success=False)
        return 1

    ui.section("hasil")

    ui.ok(
        "Driver diperbarui",
        f"{current or '-'} → [bold white]{target}[/bold white]",
    )
    console.print()
    ui.field("folder", escape(os.path.relpath(os.path.dirname(exe_path), PROJECT_ROOT)))
    ui.field(".env", f'{ENV_KEY}="{escape(relative)}"')

    if chrome and major_of(chrome) != major_of(target):
        console.print()
        ui.warn(
            f"Chrome {chrome} dan driver {target} beda versi utama; "
            "Selenium bisa gagal sampai Chrome di-update."
        )

    ui.finish_plain(started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
