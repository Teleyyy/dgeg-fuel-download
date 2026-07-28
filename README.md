# dgeg-fuel-download

[![Daily DGEG Download](https://github.com/Teleyyy/dgeg-fuel-download/actions/workflows/daily.yml/badge.svg)](https://github.com/Teleyyy/dgeg-fuel-download/actions/workflows/daily.yml)

Daily scraper and processing pipeline that turns Portuguese fuel-station price listings into a station-by-fuel-by-day panel dataset.

## Overview

The Portuguese energy regulator DGEG publishes current fuel prices per station at
[precoscombustiveis.dgeg.gov.pt](https://precoscombustiveis.dgeg.gov.pt/estatistica/postos/#download).
The site exposes only a current snapshot, with no historical export. This repository
takes one snapshot per day and appends it to a cumulative panel, so that price
changes over time can be observed at the level of an individual station.

Four fuel types are collected: `gasoline_95`, `gasoline_98`, `diesel_regular` and
`diesel_premium` (Gasolina simples 95, Gasolina especial 98, Gasóleo simples,
Gasóleo especial). A daily snapshot is roughly 10,000 station-fuel rows.

## Pipeline

`downloader.py`:

1. Opens the DGEG statistics page with headless Chromium and dismisses the cookie banner.
2. Selects the four target fuels in the dropdown, submits the search and triggers the
   CSV export, saving the download to `raw/<date>_dgeg_postos_raw.csv`.
3. Parses the semicolon-separated source file (`Nome`, `Marca`, `Combustivel`, `Preco`,
   `Municipio`, `Distrito`, `Latitude`, `Longitude`, ...): prices are converted from
   `"2,029 €"` to float, coordinates and update timestamps are coerced to numeric/datetime,
   and text dimensions are trimmed and normalised.
4. Derives a stable `station_id` as an MD5 hash of normalised name, brand and coordinates
   rounded to five decimals, plus `station_fuel_id` and a `row_hash`. Writes
   `processed_daily/<date>_dgeg_postos_processed.csv`.
5. Appends the snapshot to the panel, de-duplicates on
   `(snapshot_date, station_id, fuel_type)` keeping the latest, sorts and writes
   `panel/main_data.{csv,parquet}`. Every run appends a status row to `logs/download_log.csv`.

`build_model_ready.py` reads the panel and adds analysis columns: within
station-by-fuel lags and daily price changes, a `changed_price_today` flag, integer
codes for fixed effects (day, brand, district, municipality, fuel), municipality-by-fuel-by-day
mean prices including a leave-one-out mean, and deviations from those means. Output goes to
`model_ready/main_data_model_ready.{csv,parquet}`.

## Stack

Python 3.11, Playwright (Chromium), pandas, NumPy, pyarrow, GitHub Actions.

## Automation

`.github/workflows/daily.yml` runs on a `10 12 * * *` cron (12:10 UTC) and can also be
triggered manually via `workflow_dispatch`. The job installs the dependencies and the
Chromium browser, runs both scripts, and commits the new raw, processed, panel, model-ready
and log files back to `main`.

## Repository structure

| Path | Contents |
| --- | --- |
| `raw/` | One unmodified CSV export per day |
| `processed_daily/` | One cleaned and typed CSV per day |
| `panel/` | Cumulative station-by-fuel-by-day panel |
| `model_ready/` | Panel plus lags, group means and fixed-effect codes |
| `logs/` | Append-only run log (timestamp, status, row counts) |

The panel and model-ready CSVs are generated locally but excluded from Git, since they
exceed GitHub's file-size limits; the Parquet equivalents are committed instead.

## Running locally

```bash
pip install -r requirements.txt
python -m playwright install chromium
python downloader.py
python build_model_ready.py
```

`build_model_ready.py` requires `panel/main_data.parquet`, so it must run after at least
one successful `downloader.py` run.

## Limitations

- The scraper depends on the current DGEG page structure (the fuel dropdown, the search
  button and the CSV export control). A redesign or a change to the export schema will
  break the run; failures are recorded in `logs/download_log.csv`.
- `snapshot_date` is the collection date, not the date a price actually changed. The
  source's own `DataAtualizacao` field is preserved separately and can be considerably older.
- `station_id` is derived from name, brand and coordinates. If the source corrects any of
  these, the station is treated as new and its history does not carry over.
- Only the four listed fuels are collected; LPG and other products are out of scope.
- Every run commits the new daily files and rewrites both cumulative Parquet files in full,
  so repository size grows steadily with the length of the panel.
