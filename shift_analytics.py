import argparse
from typing import Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


SERVICE_TIME = 20
TRYON_RATE = 0.35
AVG_WORKLOAD = SERVICE_TIME * (1 + TRYON_RATE)  # 27 min / customer


def simultaneous_customers(avg_sales: float) -> float:
    if pd.isna(avg_sales):
        return np.nan
    if avg_sales >= 4.5:
        return 2.0
    elif avg_sales >= 4.0:
        return 1.5
    return 1.0


def capacity_per_hour(avg_sales: float, workload_minutes: float) -> float:
    if pd.isna(avg_sales) or pd.isna(workload_minutes) or workload_minutes <= 0:
        return np.nan
    return (60 / workload_minutes) * simultaneous_customers(avg_sales)


def read_csv_fallback(
    path: str, usecols: Optional[List[str]] = None, chunksize: Optional[int] = None
) -> Iterable[pd.DataFrame]:
    encodings = ("cp932", "shift_jis", "utf-8-sig", "utf-8")
    last_err = None
    for enc in encodings:
        try:
            reader = pd.read_csv(path, encoding=enc, usecols=usecols, chunksize=chunksize)
            return reader if chunksize else [reader]
        except UnicodeDecodeError as e:
            last_err = e
            continue
    raise last_err  # type: ignore[misc]

def build_workload_lookup(df: pd.DataFrame) -> Tuple[pd.DataFrame, float]:
    # Use only unconstrained slots to infer effective workload (min/customer)
    # Unconstrained: demand <= baseline capacity (allow small tolerance)
    tol = 0.05
    base_capacity = df["staff_count"] * df["個人処理能力_客/時_baseline"]
    mask = (df["staff_count"] > 0) & (df["客数"] > 0) & (df["客数"] <= base_capacity * (1 + tol))
    sample = df.loc[mask].copy()
    if sample.empty:
        return pd.DataFrame(), AVG_WORKLOAD

    simul = sample["avg_sales"].apply(simultaneous_customers)
    implied_capacity = sample["客数"] / sample["staff_count"]
    implied_workload = (60 * simul) / implied_capacity
    sample["implied_workload"] = implied_workload.clip(10, 60)

    agg = (
        sample.groupby(["store_cd_norm", "day_of_week", "hour"], as_index=False)
        .agg(workload_minutes=("implied_workload", "median"), n=("implied_workload", "size"))
    )
    global_workload = float(sample["implied_workload"].median())
    if np.isnan(global_workload):
        global_workload = AVG_WORKLOAD
    return agg, global_workload


def attach_workload(df: pd.DataFrame, agg: pd.DataFrame, global_workload: float) -> pd.Series:
    if agg.empty:
        return pd.Series(global_workload, index=df.index)
    merged = df.merge(
        agg,
        on=["store_cd_norm", "day_of_week", "hour"],
        how="left",
    )
    workload = merged["workload_minutes"]
    workload = workload.fillna(global_workload)
    return workload


def main() -> None:
    parser = argparse.ArgumentParser(description="POS x attendance loss analysis")
    parser.add_argument("--attendance", default="attendance_summary.csv")
    parser.add_argument("--pos-2024", default="販売伝票明細 (2024).csv")
    parser.add_argument("--pos-2025", default="販売伝票明細 (2025).csv")
    parser.add_argument("--output-detail", default="人員不足_売上ロス分析.csv")
    parser.add_argument("--output-top50", default="売上ロス上位50.csv")
    parser.add_argument("--chunksize", type=int, default=300_000)
    args = parser.parse_args()

    att = pd.read_csv(args.attendance, encoding="utf-8-sig")
    att["datetime"] = pd.to_datetime(
        att["date"].astype(str) + " " + att["time_slot"].astype(str).str[:5],
        errors="coerce",
    )
    att["store_cd_norm"] = att["store_cd_full"].astype(str).str.strip()
    att["day_of_week"] = pd.to_datetime(att["date"], errors="coerce").dt.dayofweek
    att["hour"] = pd.to_datetime(att["time_slot"].astype(str).str[:5], format="%H:%M", errors="coerce").dt.hour

    att_min = pd.to_datetime(att["date"]).min()
    att_max = pd.to_datetime(att["date"]).max()

    usecols = ["店舗コード", "営業日付", "伝票番号", "登録日時", "販売金額"]
    pos_files = [args.pos_2024, args.pos_2025]

    partials = []
    for file in pos_files:
        for chunk in read_csv_fallback(file, usecols=usecols, chunksize=args.chunksize):
            chunk["営業日付"] = pd.to_datetime(chunk["営業日付"], errors="coerce")
            chunk = chunk[(chunk["営業日付"] >= att_min) & (chunk["営業日付"] <= att_max)]
            if chunk.empty:
                continue
            chunk["登録日時"] = pd.to_datetime(chunk["登録日時"], errors="coerce")
            chunk["販売金額"] = pd.to_numeric(chunk["販売金額"], errors="coerce").fillna(0)
            chunk["datetime"] = chunk["営業日付"].dt.floor("D") + pd.to_timedelta(
                chunk["登録日時"].dt.hour, unit="h"
            )
            chunk["store_cd_norm"] = chunk["店舗コード"].astype(str).str.strip()

            g = (
                chunk.groupby(["store_cd_norm", "datetime"], as_index=False)
                .agg(客数=("伝票番号", "nunique"), 売上=("販売金額", "sum"))
            )
            partials.append(g)

    if partials:
        pos_hourly = pd.concat(partials, ignore_index=True)
        pos_hourly = (
            pos_hourly.groupby(["store_cd_norm", "datetime"], as_index=False)
            .agg(客数=("客数", "sum"), 売上=("売上", "sum"))
        )
    else:
        pos_hourly = pd.DataFrame(columns=["store_cd_norm", "datetime", "客数", "売上"])

    pos_hourly["客単価"] = np.where(
        pos_hourly["客数"] > 0, pos_hourly["売上"] / pos_hourly["客数"], 0
    )

    df = att.merge(pos_hourly, on=["store_cd_norm", "datetime"], how="left")
    df["客数"] = df["客数"].fillna(0)
    df["売上"] = df["売上"].fillna(0)
    df["客単価"] = df["客単価"].fillna(0)

    # baseline capacity (fixed workload)
    df["個人処理能力_客/時_baseline"] = df["avg_sales"].apply(
        lambda v: capacity_per_hour(v, AVG_WORKLOAD)
    )
    df["総処理能力_客/時_baseline"] = df["staff_count"] * df["個人処理能力_客/時_baseline"]

    # calibrate workload by store/day/hour from unconstrained slots
    workload_agg, global_workload = build_workload_lookup(df)
    df["workload_minutes"] = attach_workload(df, workload_agg, global_workload)

    # productivity factor from index_sum (if available)
    avg_index = np.where(
        (df["staff_count"] > 0) & (df["index_sum"].notna()),
        df["index_sum"] / df["staff_count"],
        np.nan,
    )
    prod_factor = pd.Series(avg_index).clip(0.7, 1.3)
    prod_factor = prod_factor.fillna(1.0)

    # actual capacity with calibrated workload and productivity factor
    df["個人処理能力_客/時"] = df.apply(
        lambda r: capacity_per_hour(r["avg_sales"], r["workload_minutes"]) * prod_factor.loc[r.name],
        axis=1,
    )
    df["総処理能力_客/時"] = df["staff_count"] * df["個人処理能力_客/時"]
    df["不足客数"] = np.maximum(0, df["客数"] - df["総処理能力_客/時"])
    df["売上ロス"] = df["不足客数"] * df["客単価"]
    df["必要人数"] = np.where(
        df["個人処理能力_客/時"] > 0,
        df["客数"] / df["個人処理能力_客/時"],
        np.nan,
    )
    df["人員ギャップ"] = df["staff_count"] - df["必要人数"]

    out_cols = [
        "store_cd_full",
        "store_abbrev",
        "store_full_name",
        "date",
        "time_slot",
        "datetime",
        "客数",
        "売上",
        "客単価",
        "staff_count",
        "avg_sales",
        "workload_minutes",
        "個人処理能力_客/時",
        "総処理能力_客/時",
        "不足客数",
        "売上ロス",
        "必要人数",
        "人員ギャップ",
        "error_type",
        "error_detail",
    ]
    df[out_cols].to_csv(args.output_detail, index=False, encoding="utf-8-sig")

    rank = (
        df.groupby(["store_abbrev", "store_full_name", "date", "time_slot"], as_index=False)
        .agg(
            売上ロス=("売上ロス", "sum"),
            不足客数=("不足客数", "sum"),
            客数=("客数", "sum"),
            staff_count=("staff_count", "mean"),
            avg_sales=("avg_sales", "mean"),
        )
        .sort_values("売上ロス", ascending=False)
        .head(50)
    )
    rank.to_csv(args.output_top50, index=False, encoding="utf-8-sig")

    print("OK:", "merged_rows=", len(df), "merged_stores=", df["store_cd_norm"].nunique())


if __name__ == "__main__":
    main()
