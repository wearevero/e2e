import os
import time
import re
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import numbers
from utils import ui
from utils.komponen_utils import create_driver, login, generate_urls, collect_data, get_tanggal_input

# Folder tujuan penyimpanan file. Bisa dioverride lewat variabel OUTPUT_DIR di .env
OUTPUT_DIR = os.getenv("OUTPUT_DIR", r"D:\Work\CORE\WIP\KRIDO\WIP TEMPLATE")


def save_to_excel_with_number_format(data, filename):
    """Menyimpan data ke Excel dengan format number yang benar sesuai format asli dari web"""
    if not data:
        return

    wb = Workbook()
    ws = wb.active

    for row in data:
        ws.append(row)

    for row_idx in range(1, ws.max_row + 1):
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row=row_idx, column=col_idx)

            if cell.value and str(cell.value).strip():
                cell_value_str = str(cell.value).strip()

                if is_numeric_value(cell_value_str):
                    cleaned_value = cell_value_str.replace(',', '')

                    try:
                        numeric_value = float(cleaned_value)
                        cell.value = numeric_value

                        if '.' in cell_value_str:
                            decimal_places = len(cell_value_str.split('.')[-1])

                            if decimal_places == 1:
                                cell.number_format = '0.0'
                            elif decimal_places == 2:
                                cell.number_format = '0.00'
                            elif decimal_places == 3:
                                cell.number_format = '0.000'
                            else:
                                cell.number_format = '0.' + '0' * decimal_places
                        else:
                            if numeric_value == int(numeric_value):
                                cell.number_format = '0'
                            else:
                                cell.number_format = '0.00'

                    except (ValueError, TypeError):
                        pass

    # Simpan file
    wb.save(filename)


def is_numeric_value(value_str):
    """Mengecek apakah string adalah nilai numerik"""
    cleaned = value_str.replace(',', '')

    pattern = r'^-?\d+\.?\d*$'

    return bool(re.match(pattern, cleaned))


def main():
    started = time.monotonic()
    success = False

    ui.banner("Komponen")

    input_tanggal = get_tanggal_input()
    komponen_urls = generate_urls("laporan/komponen_cetak", input_tanggal)

    ui.section("sesi")
    ui.field("laporan", "[bold white]Komponen[/bold white]")
    ui.field("tanggal", f"[bold white]{input_tanggal}[/bold white]")
    ui.field("bagian", f"{len(komponen_urls)}")
    ui.field("output", f"[dim]{OUTPUT_DIR}[/dim]")

    ui.section("browser")

    try:
        driver = create_driver()
        login(driver)

        ui.section("scraping")
        komponen_data = collect_data(driver, komponen_urls, "KOMPONEN")

        ui.section("hasil")

        if not komponen_data:
            ui.no_data()
            return

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        filename = os.path.join(OUTPUT_DIR, f"komponen-{input_tanggal}.xlsx")

        save_to_excel_with_number_format(komponen_data, filename)

        if os.path.exists(filename):
            df_verifikasi = pd.read_excel(filename, header=None)
            ui.saved(filename, len(df_verifikasi))
            success = True
        else:
            ui.fail("Gagal menyimpan file", filename)

    except Exception as e:
        ui.crashed(e)

    finally:
        ui.finish(started, success)


if __name__ == "__main__":
    main()
