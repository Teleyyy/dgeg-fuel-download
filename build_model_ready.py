from pathlib import Path
import pandas as pd
import numpy as np

BASE_DIR = Path(__file__).resolve().parent
PANEL_DIR = BASE_DIR / "panel"
MODEL_DIR = BASE_DIR / "model_ready"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

MAIN_DATA = PANEL_DIR / "main_data.parquet"
MODEL_CSV = MODEL_DIR / "main_data_model_ready.csv"
MODEL_PARQUET = MODEL_DIR / "main_data_model_ready.parquet"

def main():
    df = pd.read_parquet(MAIN_DATA).copy()

    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"], errors="coerce")
    df["price_update_ts"] = pd.to_datetime(df["price_update_ts"], errors="coerce")
    df["price_eur"] = pd.to_numeric(df["price_eur"], errors="coerce")

    df = df.sort_values(["station_id", "fuel_type", "snapshot_date"]).reset_index(drop=True)

    # lags within station x fuel
    group_keys = ["station_id", "fuel_type"]

    df["price_lag_1"] = df.groupby(group_keys)["price_eur"].shift(1)
    df["price_change_1d"] = df["price_eur"] - df["price_lag_1"]
    df["changed_price_today"] = np.where(df["price_change_1d"].fillna(0).abs() > 1e-12, 1, 0)

    # FE helpers
    df["day_id"] = df["snapshot_date"].astype("category").cat.codes
    df["brand_id"] = df["brand"].astype("category").cat.codes
    df["district_id"] = df["district"].astype("category").cat.codes
    df["municipality_id"] = df["municipality"].astype("category").cat.codes
    df["fuel_id"] = df["fuel_type"].astype("category").cat.codes

    # local contemporaneous mean in municipality x fuel x day
    grp = ["snapshot_date", "municipality", "fuel_type"]

    df["municipality_fuel_day_mean_price"] = df.groupby(grp)["price_eur"].transform("mean")
    df["municipality_fuel_day_station_count"] = df.groupby(grp)["station_id"].transform("count")

    # mean of others only
    df["municipality_fuel_day_mean_other"] = np.where(
        df["municipality_fuel_day_station_count"] > 1,
        (
            df["municipality_fuel_day_mean_price"] * df["municipality_fuel_day_station_count"]
            - df["price_eur"]
        ) / (df["municipality_fuel_day_station_count"] - 1),
        np.nan
    )

    df["price_deviation_from_municipality_mean"] = df["price_eur"] - df["municipality_fuel_day_mean_price"]
    df["price_deviation_from_municipality_others"] = df["price_eur"] - df["municipality_fuel_day_mean_other"]

    # station activity
    df["station_day_count"] = df.groupby(["station_id", "snapshot_date"])["fuel_type"].transform("count")

    # clean final ordering
    front_cols = [
        "snapshot_date",
        "station_id",
        "station_fuel_id",
        "station_name",
        "brand",
        "fuel_type",
        "price_eur",
        "price_lag_1",
        "price_change_1d",
        "changed_price_today",
        "municipality",
        "district",
        "latitude",
        "longitude",
        "municipality_fuel_day_mean_price",
        "municipality_fuel_day_mean_other",
        "price_deviation_from_municipality_mean",
        "price_deviation_from_municipality_others",
        "municipality_fuel_day_station_count",
        "day_id",
        "brand_id",
        "district_id",
        "municipality_id",
        "fuel_id",
    ]

    other_cols = [c for c in df.columns if c not in front_cols]
    df = df[front_cols + other_cols]

    df.to_csv(MODEL_CSV, index=False, encoding="utf-8-sig")
    df.to_parquet(MODEL_PARQUET, index=False)

    print(f"Saved model-ready CSV: {MODEL_CSV}")
    print(f"Saved model-ready Parquet: {MODEL_PARQUET}")
    print(f"Rows: {len(df)}")

if __name__ == "__main__":
    main()