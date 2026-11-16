import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from dotenv import load_dotenv
from utils import ui

load_dotenv()

WEB_URL = os.getenv("WEB_URL")
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
CHROMEDRIVER_PATH = os.getenv("CHROMEDRIVER_PATH")


def create_driver():
    with ui.Activity("[cyan]membuka Chrome[/cyan] [dim]· chromedriver[/dim]", gutter=False):
        chrome_options = Options()
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
        service = Service(CHROMEDRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=chrome_options)

    ui.ok("Chrome siap", f"v{driver.capabilities.get('browserVersion', '?')}")
    return driver


def login(driver):
    started = time.monotonic()

    try:
        with ui.Activity(f"[cyan]login[/cyan] [dim]· {WEB_URL}[/dim]", gutter=False):
            driver.get(WEB_URL)
            time.sleep(2)

            driver.find_element(By.NAME, "email").send_keys(EMAIL)
            driver.find_element(By.NAME, "password").send_keys(PASSWORD)
            driver.find_element(By.TAG_NAME, "form").submit()
            time.sleep(2)

        ui.ok(
            f"Login sebagai [bold white]{EMAIL}[/bold white]",
            ui.format_duration(time.monotonic() - started),
        )
    except Exception as e:
        ui.fail("Login gagal", str(e))
        raise


def highlight_rows(driver, rows, duration=1.5):
    """Highlight sekaligus semua baris <tr> yang ingin di-copy"""
    try:
        driver.execute_script(
            """
            const rows = arguments[0];
            for (const row of rows) {
                row.style.border = '2px solid red';
                row.style.backgroundColor = 'yellow';
            }
        """,
            rows,
        )

        time.sleep(duration)

        driver.execute_script(
            """
            const rows = arguments[0];
            for (const row of rows) {
                row.style.border = '';
                row.style.backgroundColor = '';
            }
        """,
            rows,
        )
    except Exception as e:
        ui.block_note(f"highlight dilewati · {ui.first_line(e, 50)}", icon="·", color="dim")


def extract_table_data(driver):
    """Mengambil data dari tabel utama dan highlight semua baris yang akan diambil sekaligus"""
    selectors = [
        "td.judul > table > tbody",
        "table > tbody",
        ".judul table tbody",
        "table tbody",
    ]

    table = None
    for selector in selectors:
        try:
            table = driver.find_element(By.CSS_SELECTOR, selector)
            break
        except:
            continue

    if not table:
        return []

    try:
        rows = table.find_elements(By.TAG_NAME, "tr")

        if len(rows) <= 2:
            return []

        data_rows = rows[1:-1]

        if data_rows:
            highlight_rows(driver, data_rows, duration=1.5)

        data = []
        for row in data_rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if cols:
                row_data = [col.text.strip() for col in cols]
                data.append(row_data)

        return data

    except Exception as e:
        ui.block_note(f"gagal ambil tabel · {ui.first_line(e, 50)}", icon="✗", color="red")
        return []


def collect_data(driver, urls_dict, jenis):
    all_data = []
    original_tab = driver.current_window_handle
    total = len(urls_dict)
    started = time.monotonic()
    done = empty = failed = 0

    ui.block_header(jenis, f"{total} bagian")

    with ui.Activity() as activity:
        for i, (bagian, url) in enumerate(urls_dict.items(), start=1):
            activity.update(f"[cyan]memuat[/cyan] {bagian} [dim]· {i}/{total}[/dim]")

            if i == 1:
                driver.get(url)
            else:
                driver.execute_script("window.open('');")
                driver.switch_to.window(driver.window_handles[-1])
                driver.get(url)

            time.sleep(2)

            try:
                time.sleep(1)
                if "error" in driver.page_source.lower() or "404" in driver.title:
                    ui.item_warn(i, total, bagian, "halaman error")
                    failed += 1
                    continue
            except Exception as e:
                ui.item_fail(i, total, bagian, f"gagal dimuat · {e}")
                failed += 1
                continue

            activity.update(f"[cyan]mengambil tabel[/cyan] {bagian} [dim]· {i}/{total}[/dim]")
            data = extract_table_data(driver)

            if data:
                for row in data:
                    # Buang 2 kolom terakhir (BAGIAN & TANGGAL) karena tidak dibutuhkan
                    all_data.append(row[:-2] + [bagian])
                ui.item_ok(i, total, bagian, len(data))
                done += 1
            else:
                ui.item_empty(i, total, bagian)
                empty += 1

    driver.switch_to.window(original_tab)

    ui.block_footer(
        done=done + empty,
        total=total,
        rows=len(all_data),
        empty=empty,
        failed=failed,
        duration=time.monotonic() - started,
    )

    return all_data


def generate_urls(base_path, tanggal):
    bagian_mapping = {
        "CUTTING 2": 7,
        "TAMBAH PART": 125,
        "RE-CASTING": 101,
        "REPAIR PART": 126,
        "ILCA": 103,
        "STRIPING": 9,
        "PENDING": 15,
        "PERBAIKAN": 16,
        "RANGKAI 1": 12,
        "SEGONG REPAIR": 2,
        "FILLLING1": 13,
        "FILLING 2": 17,
        "POLISHING 1": 100,
        "POLISHING 2": 11,
        "POLISHING CVD": 122,
    }

    urls = {}
    for bagian, bagian_id in bagian_mapping.items():
        urls[bagian] = f"{WEB_URL}/{base_path}?d={tanggal}&s=&b={bagian_id}&m=all"
    return urls


def get_tanggal_input():
    """Meminta input tanggal dari user, default ke hari ini"""
    return ui.ask_date()
