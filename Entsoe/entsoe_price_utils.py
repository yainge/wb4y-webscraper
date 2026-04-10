from __future__ import annotations

from pathlib import Path
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


MTU_COLUMN = "MTU (CET/CEST)"
PRICE_COLUMN = "Day-ahead Price (EUR/MWh)"
MTU_DATETIME_FORMAT = "%d/%m/%Y %H:%M:%S"
TIMEZONE_SUFFIX_RE = re.compile(r"\s*\((?:CET|CEST)\)")


def clean_mtu_text(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .str.replace(TIMEZONE_SUFFIX_RE, "", regex=True)
        .str.strip()
    )


def parse_mtu_start_end(mtu_series: pd.Series) -> tuple[pd.Series, pd.Series]:
    parts = clean_mtu_text(mtu_series).str.split(" - ", n=1, expand=True)
    if parts.shape[1] != 2:
        raise ValueError("Expected MTU values in 'start - end' format.")

    start_time = pd.to_datetime(
        parts[0],
        format=MTU_DATETIME_FORMAT,
        errors="coerce",
    )
    end_time = pd.to_datetime(
        parts[1],
        format=MTU_DATETIME_FORMAT,
        errors="coerce",
    )
    return start_time, end_time


def _finalize_raw_prices(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    data = df.copy()
    data = data.dropna(subset=["mtu", "price_eur_mwh"])

    start_time, end_time = parse_mtu_start_end(data["mtu"])
    data["source_start_time"] = start_time
    data["source_end_time"] = end_time
    data["price_eur_mwh"] = pd.to_numeric(data["price_eur_mwh"], errors="coerce")
    data["price_eur_kwh"] = data["price_eur_mwh"] / 1000.0
    data["source_file"] = source_name

    data = data.dropna(
        subset=["source_start_time", "source_end_time", "price_eur_kwh"]
    ).reset_index(drop=True)
    return data[
        [
            "source_start_time",
            "source_end_time",
            "price_eur_mwh",
            "price_eur_kwh",
            "source_file",
        ]
    ]


def load_entsoe_excel_prices(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    df = pd.read_excel(
        path,
        skiprows=7,
        header=None,
        usecols=[0, 1],
        names=["mtu", "price_eur_mwh"],
    )
    return _finalize_raw_prices(df, path.name)


def load_entsoe_csv_prices(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    df = pd.read_csv(
        path,
        usecols=[MTU_COLUMN, PRICE_COLUMN],
    ).rename(
        columns={
            MTU_COLUMN: "mtu",
            PRICE_COLUMN: "price_eur_mwh",
        }
    )
    return _finalize_raw_prices(df, path.name)


def expected_year_periods(year: int) -> int:
    return len(
        pd.date_range(
            start=f"{year}-01-01 00:00:00",
            end=f"{year + 1}-01-01 00:00:00",
            freq="15min",
            inclusive="left",
        )
    )


def quarter_hour_index_for_year(year: int) -> pd.DatetimeIndex:
    return pd.date_range(
        start=f"{year}-01-01 00:00:00",
        end=f"{year + 1}-01-01 00:00:00",
        freq="15min",
        inclusive="left",
    )


def build_year_timeseries(
    raw_prices: pd.DataFrame,
    year: int,
    area: str = "BZN|NL",
    source_year: int | None = None,
) -> pd.DataFrame:
    timeline = quarter_hour_index_for_year(year)
    if len(raw_prices) != len(timeline):
        raise ValueError(
            f"Expected {len(timeline)} quarter-hour values for {year}, "
            f"but found {len(raw_prices)}."
        )

    series = pd.DataFrame(
        {
            "timestamp": timeline,
            "price_eur_kwh": raw_prices["price_eur_kwh"].to_numpy(),
            "year": year,
            "area": area,
            "source_year": source_year if source_year is not None else year,
        }
    )
    return series


def build_partial_year_timeseries(
    raw_prices: pd.DataFrame,
    year: int,
    area: str = "BZN|NL",
    source_year: int | None = None,
) -> pd.DataFrame:
    timeline = quarter_hour_index_for_year(year)
    n_observed = min(len(raw_prices), len(timeline))
    prices = [pd.NA] * len(timeline)
    if n_observed:
        prices[:n_observed] = raw_prices["price_eur_kwh"].iloc[:n_observed].tolist()

    return pd.DataFrame(
        {
            "timestamp": timeline,
            "price_eur_kwh": pd.Series(prices, dtype="Float64"),
            "year": year,
            "area": area,
            "source_year": source_year if source_year is not None else year,
        }
    )


def write_year_parquet(df: pd.DataFrame, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    return output_path


def read_year_parquet(path: str | Path) -> pd.DataFrame:
    return pd.read_parquet(path).sort_values("timestamp").reset_index(drop=True)


def to_legacy_parquet_schema(df: pd.DataFrame) -> pd.DataFrame:
    legacy = df[["timestamp", "price_eur_kwh"]].copy()
    legacy["ts_utc"] = pd.to_datetime(legacy["timestamp"], utc=True)
    legacy["price"] = pd.to_numeric(legacy["price_eur_kwh"], errors="coerce")
    legacy = legacy[["ts_utc", "price"]].sort_values("ts_utc").reset_index(drop=True)
    return legacy


def write_legacy_year_parquet(df: pd.DataFrame, output_path: str | Path) -> Path:
    legacy = to_legacy_parquet_schema(df)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    legacy.to_parquet(output_path, index=False)
    return output_path


def read_legacy_year_parquet(path: str | Path, year: int | None = None) -> pd.DataFrame:
    legacy = pd.read_parquet(path).sort_values("ts_utc").reset_index(drop=True)
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(legacy["ts_utc"]).dt.tz_convert("UTC").dt.tz_localize(None),
            "price_eur_kwh": pd.to_numeric(legacy["price"], errors="coerce"),
        }
    )
    if year is None and not frame.empty:
        year = int(frame["timestamp"].dt.year.mode().iloc[0])
    frame["year"] = year
    frame["area"] = "BZN|NL"
    frame["source_year"] = year
    return frame.sort_values("timestamp").reset_index(drop=True)


def build_summary_table(year_frames: dict[int, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for year, frame in sorted(year_frames.items()):
        rows.append(
            {
                "year": year,
                "rows": len(frame),
                "missing": int(frame["price_eur_kwh"].isna().sum()),
                "start": frame["timestamp"].min(),
                "end": frame["timestamp"].max(),
                "min_eur_kwh": frame["price_eur_kwh"].min(),
                "max_eur_kwh": frame["price_eur_kwh"].max(),
                "mean_eur_kwh": frame["price_eur_kwh"].mean(),
            }
        )
    return pd.DataFrame(rows)


def _add_time_features(frame: pd.DataFrame) -> pd.DataFrame:
    enriched = frame.copy()
    enriched["month"] = enriched["timestamp"].dt.month
    enriched["day_of_week"] = enriched["timestamp"].dt.dayofweek
    enriched["quarter_hour"] = (
        enriched["timestamp"].dt.hour * 4 + enriched["timestamp"].dt.minute // 15
    )
    return enriched


def _seasonal_baseline(history: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    return (
        history.groupby(keys, dropna=False)["price_eur_kwh"]
        .median()
        .rename("baseline_value")
        .reset_index()
    )


def _apply_random_residuals(
    target: pd.DataFrame,
    history: pd.DataFrame,
    random_seed: int = 42,
    noise_scale: float = 0.35,
    smooth_window: int = 8,
) -> pd.DataFrame:
    rng = np.random.default_rng(random_seed)
    residual_keys = ["month", "day_of_week", "quarter_hour"]

    baseline = _seasonal_baseline(history, residual_keys)
    history_with_baseline = history.merge(baseline, on=residual_keys, how="left")
    history_with_baseline["residual"] = (
        history_with_baseline["price_eur_kwh"] - history_with_baseline["baseline_value"]
    )

    residual_pool = (
        history_with_baseline.groupby(residual_keys, dropna=False)["residual"]
        .apply(lambda s: list(s.dropna()))
        .rename("residual_pool")
        .reset_index()
    )

    target = target.merge(residual_pool, on=residual_keys, how="left")

    sampled_residuals = np.zeros(len(target), dtype=float)
    for idx, pool in enumerate(target["residual_pool"]):
        if isinstance(pool, list) and pool:
            sampled_residuals[idx] = rng.choice(pool)

    if smooth_window > 1:
        sampled_residuals = (
            pd.Series(sampled_residuals)
            .rolling(window=smooth_window, center=True, min_periods=1)
            .mean()
            .to_numpy()
        )

    target["price_eur_kwh"] = (
        target["price_eur_kwh"].astype(float) + noise_scale * sampled_residuals
    )
    target["price_eur_kwh"] = target["price_eur_kwh"].clip(lower=-0.5)
    return target.drop(columns=["residual_pool"])


def fill_missing_with_seasonal_profile(
    target_frame: pd.DataFrame,
    history_frames: list[pd.DataFrame],
    add_randomness: bool = True,
    random_seed: int = 42,
    noise_scale: float = 0.35,
    smooth_window: int = 8,
) -> pd.DataFrame:
    history = pd.concat(history_frames, ignore_index=True)
    history = history.dropna(subset=["price_eur_kwh"])
    history = _add_time_features(history)

    target = _add_time_features(target_frame)

    profile_keys = [
        ["month", "day_of_week", "quarter_hour"],
        ["day_of_week", "quarter_hour"],
        ["month", "quarter_hour"],
        ["quarter_hour"],
    ]

    target["price_eur_kwh"] = target["price_eur_kwh"].astype("Float64")

    for keys in profile_keys:
        lookup = (
            history.groupby(keys, dropna=False)["price_eur_kwh"]
            .median()
            .rename("forecast_value")
            .reset_index()
        )
        target = target.merge(lookup, on=keys, how="left")
        missing_mask = target["price_eur_kwh"].isna()
        target.loc[missing_mask, "price_eur_kwh"] = target.loc[
            missing_mask, "forecast_value"
        ]
        target = target.drop(columns=["forecast_value"])

    global_mean = history["price_eur_kwh"].median()
    target["price_eur_kwh"] = target["price_eur_kwh"].fillna(global_mean)

    if add_randomness:
        target = _apply_random_residuals(
            target=target,
            history=history,
            random_seed=random_seed,
            noise_scale=noise_scale,
            smooth_window=smooth_window,
        )

    return target[["timestamp", "price_eur_kwh", "year", "area", "source_year"]]


def forecast_year_from_history(
    history_frames: list[pd.DataFrame],
    target_year: int,
    area: str = "BZN|NL",
    source_year: int | None = None,
    add_randomness: bool = True,
    random_seed: int = 42,
    noise_scale: float = 0.35,
    smooth_window: int = 8,
) -> pd.DataFrame:
    empty_year = pd.DataFrame(
        {
            "timestamp": quarter_hour_index_for_year(target_year),
            "price_eur_kwh": pd.Series([pd.NA] * expected_year_periods(target_year), dtype="Float64"),
            "year": target_year,
            "area": area,
            "source_year": source_year if source_year is not None else target_year,
        }
    )
    return fill_missing_with_seasonal_profile(
        empty_year,
        history_frames,
        add_randomness=add_randomness,
        random_seed=random_seed,
        noise_scale=noise_scale,
        smooth_window=smooth_window,
    )


def plot_year_subplots(year_frames: dict[int, pd.DataFrame]) -> tuple[plt.Figure, list]:
    years = sorted(year_frames)
    fig, axes = plt.subplots(len(years), 1, figsize=(16, 11), sharex=False)
    if len(years) == 1:
        axes = [axes]

    colors = {
        years[0]: "#1d4ed8",
        years[1] if len(years) > 1 else years[0]: "#0f766e",
        years[2] if len(years) > 2 else years[0]: "#ea580c",
    }

    for ax, year in zip(axes, years):
        frame = year_frames[year]
        ax.plot(
            frame["timestamp"],
            frame["price_eur_kwh"],
            linewidth=0.8,
            color=colors[year],
        )
        source_year = int(frame["source_year"].iloc[0])
        title = f"{year} Energy Prices"
        if source_year != year:
            title += f" (forecast using history through {source_year})"
        ax.set_title(title)
        ax.set_ylabel("EUR/kWh")
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel("Timestamp")
    fig.tight_layout()
    return fig, axes
