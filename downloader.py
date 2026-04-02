from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright
import shutil
import time
import pandas as pd
import hashlib
import re

URL = "https://precoscombustiveis.dgeg.gov.pt/estatistica/postos/#download"

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "raw"
PROCESSED_DIR = BASE_DIR / "processed_daily"
PANEL_DIR = BASE_DIR / "panel"
LOG_DIR = BASE_DIR / "logs"

for d in [RAW_DIR, PROCESSED_DIR, PANEL_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

TODAY = datetime.now().strftime("%Y-%m-%d")
RUN_TS = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

RAW_FILE = RAW_DIR / f"{TODAY}_dgeg_postos_raw.csv"
PROCESSED_FILE = PROCESSED_DIR / f"{TODAY}_dgeg_postos_processed.csv"
MAIN_DATA_CSV = PANEL_DIR / "main_data.csv"
MAIN_DATA_PARQUET = PANEL_DIR / "main_data.parquet"
RUN_LOG = LOG_DIR / "download_log.csv"

COOKIE_BUTTONS = [
    "NÃO OBRIGADO!",
    "Não obrigado!",
    "NAO OBRIGADO!",
]

TARGET_LABELS = [
    "Gasolina simples 95",
    "Gasolina especial 98",
    "Gasóleo simples",
    "Gasóleo especial",
]

FUEL_MAP = {
    "Gasolina simples 95": "gasoline_95",
    "Gasolina especial 98": "gasoline_98",
    "Gasóleo simples": "diesel_regular",
    "Gasóleo especial": "diesel_premium",
}

def normalize_text(x: str) -> str:
    if pd.isna(x):
        return ""
    x = str(x).strip().lower()
    x = re.sub(r"\s+", " ", x)
    return x

def save_download(download_path: str, final_path: Path):
    src = Path(download_path)
    if final_path.exists():
        final_path.unlink()
    shutil.move(str(src), str(final_path))
    print(f"Saved raw file to: {final_path}")

def close_cookies(page):
    for text in COOKIE_BUTTONS:
        try:
            page.get_by_text(text, exact=True).click(timeout=3000)
            print(f"Closed cookies with: {text}")
            time.sleep(1)
            return
        except:
            pass
    print("Cookie popup not found or already closed")

def clean_price(price_text):
    if pd.isna(price_text):
        return None
    s = str(price_text).replace("€", "").replace(" ", "").replace(",", ".").strip()
    return float(s)

def build_station_id(row):
    key = "||".join([
        normalize_text(row.get("Nome", "")),
        normalize_text(row.get("Marca", "")),
        f"{float(row.get('Latitude')):.5f}" if pd.notna(row.get("Latitude")) else "",
        f"{float(row.get('Longitude')):.5f}" if pd.notna(row.get("Longitude")) else "",
    ])
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]

def build_row_hash(row):
    key = "||".join([
        str(row.get("snapshot_date", "")),
        str(row.get("station_id", "")),
        str(row.get("fuel_type", "")),
        str(row.get("price_eur", "")),
    ])
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]

def process_downloaded_file(raw_file: Path, processed_file: Path):
    df = pd.read_csv(raw_file, sep=";", encoding="utf-8-sig")

    # zachowaj oryginalne kolumny tekstowe
    df["price_raw"] = df["Preco"]
    df["fuel_type_raw"] = df["Combustivel"]
    df["brand_raw"] = df["Marca"]
    df["station_name_raw"] = df["Nome"]
    df["address_raw"] = df["Morada"]

    # snapshot date = dzień pobrania, nie DataAtualizacao
    df["snapshot_date"] = pd.to_datetime(TODAY).date()
    df["downloaded_at"] = RUN_TS

    # parsed columns
    df["price_eur"] = df["Preco"].apply(clean_price)
    df["price_update_ts"] = pd.to_datetime(df["DataAtualizacao"], errors="coerce")
    df["latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")

    # normalized dimensions
    df["station_name"] = df["Nome"].astype(str).str.strip()
    df["brand"] = df["Marca"].astype(str).str.strip()
    df["fuel_type"] = df["Combustivel"].map(FUEL_MAP).fillna(df["Combustivel"])
    df["fuel_type_label"] = df["Combustivel"].astype(str).str.strip()
    df["station_type"] = df["TipoPosto"].astype(str).str.strip()
    df["municipality"] = df["Municipio"].astype(str).str.strip()
    df["district"] = df["Distrito"].astype(str).str.strip()
    df["address"] = df["Morada"].astype(str).str.strip()
    df["locality"] = df["Localidade"].astype(str).str.strip()
    df["postcode"] = df["CodPostal"].astype(str).str.strip()

    df["station_name_norm"] = df["station_name"].apply(normalize_text)
    df["brand_norm"] = df["brand"].apply(normalize_text)
    df["address_norm"] = df["address"].apply(normalize_text)

    # IDs
    df["station_id"] = df.apply(build_station_id, axis=1)
    df["station_fuel_id"] = df["station_id"] + "_" + df["fuel_type"].astype(str)

    # source tracking
    df["source_file"] = raw_file.name

    # final column order
    final_cols = [
        "snapshot_date",
        "downloaded_at",
        "price_update_ts",
        "station_id",
        "station_fuel_id",
        "station_name",
        "brand",
        "fuel_type",
        "fuel_type_label",
        "station_type",
        "price_eur",
        "municipality",
        "district",
        "address",
        "locality",
        "postcode",
        "latitude",
        "longitude",
        "station_name_norm",
        "brand_norm",
        "address_norm",
        "price_raw",
        "source_file",
    ]

    df = df[final_cols].copy()
    df["row_hash"] = df.apply(build_row_hash, axis=1)

    df.to_csv(processed_file, index=False, encoding="utf-8-sig")
    print(f"Saved processed file to: {processed_file}")
    return df

def update_main_data(new_df: pd.DataFrame):
    if MAIN_DATA_PARQUET.exists():
        old_df = pd.read_parquet(MAIN_DATA_PARQUET)
        combined = pd.concat([old_df, new_df], ignore_index=True)
    elif MAIN_DATA_CSV.exists():
        old_df = pd.read_csv(MAIN_DATA_CSV)
        combined = pd.concat([old_df, new_df], ignore_index=True)
    else:
        combined = new_df.copy()

    combined["snapshot_date"] = pd.to_datetime(combined["snapshot_date"], errors="coerce").dt.date
    combined["price_update_ts"] = pd.to_datetime(combined["price_update_ts"], errors="coerce")

    combined = combined.drop_duplicates(
        subset=["snapshot_date", "station_id", "fuel_type"],
        keep="last"
    ).reset_index(drop=True)

    combined = combined.sort_values(["snapshot_date", "fuel_type", "station_id"]).reset_index(drop=True)

    combined.to_csv(MAIN_DATA_CSV, index=False, encoding="utf-8-sig")
    combined.to_parquet(MAIN_DATA_PARQUET, index=False)

    print(f"Updated main_data: {len(combined)} rows")
    return combined

def write_run_log(status: str, raw_rows=None, panel_rows=None, note=""):
    log_row = pd.DataFrame([{
        "run_ts": RUN_TS,
        "snapshot_date": TODAY,
        "status": status,
        "raw_rows": raw_rows,
        "panel_rows_after": panel_rows,
        "note": note,
    }])

    if RUN_LOG.exists():
        old = pd.read_csv(RUN_LOG)
        out = pd.concat([old, log_row], ignore_index=True)
    else:
        out = log_row

    out.to_csv(RUN_LOG, index=False, encoding="utf-8-sig")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=200)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            time.sleep(5)

            close_cookies(page)
            time.sleep(2)

            fuel_select = page.locator("select").first

            options = fuel_select.locator("option").evaluate_all(
                """els => els.map(e => ({
                    value: e.value,
                    text: (e.textContent || '').trim()
                }))"""
            )

            values_to_select = []
            for target in TARGET_LABELS:
                matched = None
                for opt in options:
                    if opt["text"].strip().lower() == target.lower():
                        matched = opt["value"]
                        break
                if matched:
                    values_to_select.append(matched)
                else:
                    print(f"NOT FOUND: {target}")

            if len(values_to_select) != 4:
                raise Exception("Nie znalazłem wszystkich 4 paliw w dropdownie.")

            fuel_select.select_option(value=values_to_select)
            print("Selected 4 fuels")
            time.sleep(2)

            page.get_by_role("button", name="Procurar").click(timeout=10000)
            print("Clicked Procurar")
            time.sleep(5)

            with page.expect_download(timeout=30000) as download_info:
                page.get_by_text("Exportar para CSV", exact=True).click(timeout=10000)

            download = download_info.value
            temp_path = download.path()
            save_download(temp_path, RAW_FILE)

            new_df = process_downloaded_file(RAW_FILE, PROCESSED_FILE)
            panel_df = update_main_data(new_df)

            write_run_log(
                status="ok",
                raw_rows=len(new_df),
                panel_rows=len(panel_df),
                note="download + process + panel update successful"
            )

        except Exception as e:
            write_run_log(status="error", note=str(e))
            raise

        finally:
            context.close()
            browser.close()

if __name__ == "__main__":
    main()