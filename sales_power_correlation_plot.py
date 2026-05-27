import argparse
import datetime as dt
from pathlib import Path
from typing import Iterable, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create correlation charts for time-slot sales vs avg sales power."
    )
    parser.add_argument("--year", type=int, required=True, help="Target year (e.g. 2025)")
    parser.add_argument("--month", type=int, required=True, help="Target month (1-12)")
    parser.add_argument(
        "--attendance",
        default="attendance_summary.csv",
        help="Path to attendance summary CSV",
    )
    parser.add_argument(
        "--pos",
        default="",
        help="Path to POS CSV. If omitted, auto-detect a large *<year>*.csv file.",
    )
    parser.add_argument(
        "--output-dir",
        default="sales_power_correlation_charts",
        help="Directory to save PNG outputs",
    )
    parser.add_argument(
        "--min-store-rows",
        type=int,
        default=80,
        help="Minimum rows per store for store-level correlation chart",
    )
    return parser.parse_args()


def month_range_ymd(year: int, month: int) -> Tuple[int, int]:
    start = dt.date(year, month, 1)
    if month == 12:
        end = dt.date(year + 1, 1, 1) - dt.timedelta(days=1)
    else:
        end = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    return int(start.strftime("%Y%m%d")), int(end.strftime("%Y%m%d"))


def detect_pos_file(pos_arg: str, year: int) -> Path:
    if pos_arg:
        p = Path(pos_arg)
        if p.exists():
            return p
        raise FileNotFoundError(f"POS file not found: {pos_arg}")
    candidates = sorted(
        [p for p in Path(".").glob(f"*{year}*.csv") if p.stat().st_size > 100_000_000],
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("No large POS csv found. Pass --pos.")
    return candidates[0]


def load_attendance(path: Path, year: int, month: int) -> pd.DataFrame:
    att = pd.read_csv(path, encoding="utf-8-sig", dtype={"store_cd_full": "string"})
    prefix = f"{year:04d}-{month:02d}-"
    att = att[att["date"].astype(str).str.startswith(prefix)].copy()
    att = att[att["error_type"].fillna("") == ""].copy()
    att["store_cd_full_norm"] = (
        att["store_cd_full"].astype(str).str.replace(".0", "", regex=False).str.strip()
    )
    att["slot_start"] = pd.to_datetime(
        att["date"] + " " + att["time_slot"].astype(str).str.split("-").str[0], errors="coerce"
    )
    att["avg_sales_num"] = pd.to_numeric(att["avg_sales"], errors="coerce")
    att["staff_count_num"] = pd.to_numeric(att["staff_count"], errors="coerce")
    att = att.dropna(subset=["slot_start", "avg_sales_num"])
    return att


def read_pos_chunks(path: Path, usecols: Iterable[int], names: Iterable[str]) -> Iterable[pd.DataFrame]:
    encodings = ["cp932", "shift_jis", "utf-8-sig", "utf-8"]
    last_exc: Optional[Exception] = None
    for enc in encodings:
        try:
            yield from pd.read_csv(
                path,
                encoding=enc,
                usecols=list(usecols),
                header=0,
                names=list(names),
                chunksize=300_000,
                low_memory=False,
            )
            return
        except Exception as exc:
            last_exc = exc
    if last_exc:
        raise last_exc


def load_pos_slot_sales(path: Path, year: int, month: int) -> pd.DataFrame:
    ymd_min, ymd_max = month_range_ymd(year, month)
    usecols = [3, 5, 19, 37]  # business_date, store_cd, sales_amount, registered_at
    names = ["business_date", "store_cd", "sales_amount", "registered_at"]

    parts = []
    for chunk in read_pos_chunks(path, usecols, names):
        d = pd.to_numeric(chunk["business_date"], errors="coerce").astype("Int64")
        mask = (d >= ymd_min) & (d <= ymd_max)
        if not mask.any():
            continue
        c = chunk.loc[mask].copy()
        c["date"] = pd.to_datetime(d[mask].astype(str), format="%Y%m%d", errors="coerce")
        c["registered_dt"] = pd.to_datetime(c["registered_at"], errors="coerce")
        c = c.dropna(subset=["date", "registered_dt"])
        if c.empty:
            continue
        c["slot_start"] = c["date"] + pd.to_timedelta(c["registered_dt"].dt.hour, unit="h")
        c["store_cd_full_norm"] = c["store_cd"].astype(str).str.replace(".0", "", regex=False).str.strip()
        c["sales"] = pd.to_numeric(c["sales_amount"], errors="coerce").fillna(0.0)
        parts.append(c[["store_cd_full_norm", "slot_start", "sales"]])

    if not parts:
        return pd.DataFrame(columns=["store_cd_full_norm", "slot_start", "slot_sales"])
    pos = pd.concat(parts, ignore_index=True)
    return (
        pos.groupby(["store_cd_full_norm", "slot_start"], as_index=False)
        .agg(slot_sales=("sales", "sum"))
    )


def calc_corr(df: pd.DataFrame, x: str, y: str) -> Tuple[float, float]:
    d = df[[x, y]].dropna()
    if len(d) < 3:
        return np.nan, np.nan
    return float(d.corr(method="pearson").iloc[0, 1]), float(d.corr(method="spearman").iloc[0, 1])


def scatter_with_trend(df: pd.DataFrame, x: str, y: str, title: str, out_path: Path) -> None:
    d = df[[x, y]].dropna()
    plt.figure(figsize=(9, 6))
    plt.scatter(d[x], d[y], s=12, alpha=0.20, edgecolors="none")
    if len(d) >= 2 and d[x].nunique() >= 2:
        coef = np.polyfit(d[x], d[y], deg=1)
        xx = np.linspace(float(d[x].min()), float(d[x].max()), 200)
        yy = coef[0] * xx + coef[1]
        plt.plot(xx, yy, linewidth=2)
    p, s = calc_corr(d, x, y)
    plt.title(f"{title}\nPearson={p:.3f}, Spearman={s:.3f}, n={len(d)}")
    plt.xlabel(x)
    plt.ylabel(y)
    plt.grid(alpha=0.2)
    plt.tight_layout()
    plt.savefig(out_path, dpi=160)
    plt.close()


def bar_store_corr(df: pd.DataFrame, out_path: Path) -> None:
    d = df.dropna(subset=["pearson_per_staff"]).copy()
    d = d.sort_values("pearson_per_staff", ascending=False)
    plt.figure(figsize=(12, 7))
    colors = ["#2a9d8f" if v >= 0 else "#e76f51" for v in d["pearson_per_staff"]]
    plt.bar(d["store"], d["pearson_per_staff"], color=colors)
    plt.axhline(0, color="black", linewidth=1)
    plt.title("Store-Level Correlation: avg_sales vs sales_per_staff (Pearson)")
    plt.xlabel("store")
    plt.ylabel("correlation")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(out_path, dpi=160)
    plt.close()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    att = load_attendance(Path(args.attendance), args.year, args.month)
    pos_file = detect_pos_file(args.pos, args.year)
    pos_slot = load_pos_slot_sales(pos_file, args.year, args.month)

    merged = att.merge(pos_slot, on=["store_cd_full_norm", "slot_start"], how="left")
    merged["slot_sales"] = merged["slot_sales"].fillna(0.0)
    merged["sales_per_staff"] = np.where(
        merged["staff_count_num"] > 0,
        merged["slot_sales"] / merged["staff_count_num"],
        np.nan,
    )

    # overall summary
    p_total, s_total = calc_corr(merged, "avg_sales_num", "slot_sales")
    p_ps, s_ps = calc_corr(merged, "avg_sales_num", "sales_per_staff")
    summary = pd.DataFrame(
        [
            {
                "rows_merged": len(merged),
                "overall_pearson_total": p_total,
                "overall_spearman_total": s_total,
                "overall_pearson_per_staff": p_ps,
                "overall_spearman_per_staff": s_ps,
            }
        ]
    )

    # by store
    stores = []
    for store, g in merged.groupby("store_abbrev"):
        if len(g) < args.min_store_rows:
            continue
        p1, s1 = calc_corr(g, "avg_sales_num", "slot_sales")
        p2, s2 = calc_corr(g, "avg_sales_num", "sales_per_staff")
        stores.append(
            {
                "store": store,
                "n": len(g),
                "pearson_total": p1,
                "spearman_total": s1,
                "pearson_per_staff": p2,
                "spearman_per_staff": s2,
            }
        )
    by_store = pd.DataFrame(stores).sort_values("pearson_per_staff", ascending=False)

    # save data tables
    summary.to_csv(out_dir / "summary.csv", index=False, encoding="utf-8-sig")
    by_store.to_csv(out_dir / "by_store.csv", index=False, encoding="utf-8-sig")

    # charts
    scatter_with_trend(
        merged,
        "avg_sales_num",
        "slot_sales",
        "Time-Slot Sales vs Avg Sales Power",
        out_dir / "scatter_total_sales_vs_power.png",
    )
    scatter_with_trend(
        merged.dropna(subset=["sales_per_staff"]),
        "avg_sales_num",
        "sales_per_staff",
        "Sales per Staff vs Avg Sales Power",
        out_dir / "scatter_per_staff_sales_vs_power.png",
    )
    if not by_store.empty:
        bar_store_corr(by_store, out_dir / "bar_store_correlation_per_staff.png")

    print(f"pos_file: {pos_file}")
    print(f"saved: {out_dir / 'summary.csv'}")
    print(f"saved: {out_dir / 'by_store.csv'}")
    print(f"saved: {out_dir / 'scatter_total_sales_vs_power.png'}")
    print(f"saved: {out_dir / 'scatter_per_staff_sales_vs_power.png'}")
    if not by_store.empty:
        print(f"saved: {out_dir / 'bar_store_correlation_per_staff.png'}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
