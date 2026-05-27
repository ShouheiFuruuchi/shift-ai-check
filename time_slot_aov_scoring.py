import argparse
import datetime as dt
from pathlib import Path
from typing import Iterable, List, Optional

import numpy as np
import pandas as pd


BAG_PRODUCT_CODES = {
    "9998998012113",
    "9998998011112",
    "9998998008114",
    "9998998007113",
    "9998998006112",
    "9998998014115",
    "9998998013114",
}


def month_range_ymd(year: int, month: int) -> tuple[int, int]:
    start = dt.date(year, month, 1)
    if month == 12:
        end = dt.date(year + 1, 1, 1) - dt.timedelta(days=1)
    else:
        end = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    return int(start.strftime("%Y%m%d")), int(end.strftime("%Y%m%d"))


def read_csv_fallback(
    path: Path,
    usecols: Optional[List[int]] = None,
    names: Optional[List[str]] = None,
    chunksize: Optional[int] = None,
) -> Iterable[pd.DataFrame]:
    encodings = ("cp932", "shift_jis", "utf-8-sig", "utf-8")
    last_err: Optional[Exception] = None
    for enc in encodings:
        try:
            reader = pd.read_csv(
                path,
                encoding=enc,
                usecols=usecols,
                header=0,
                names=names,
                chunksize=chunksize,
                low_memory=False,
            )
            if chunksize is None:
                return [reader]
            return reader
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    if last_err:
        raise last_err
    raise RuntimeError("failed to read csv")


def load_attendance_slots(att_path: Path, year: int, month: int) -> pd.DataFrame:
    att = pd.read_csv(att_path, encoding="utf-8-sig", dtype={"store_cd_full": "string"})
    att["date_dt"] = pd.to_datetime(att["date"], errors="coerce")
    att = att[
        (att["date_dt"].dt.year == year)
        & (att["date_dt"].dt.month == month)
        & (att["error_type"].fillna("") == "")
    ].copy()
    att["date"] = att["date_dt"].dt.strftime("%Y-%m-%d")
    att["hour"] = pd.to_datetime(
        att["time_slot"].astype(str).str.split("-").str[0], format="%H:%M", errors="coerce"
    ).dt.hour
    att["store_cd_norm"] = (
        att["store_cd_full"].astype(str).str.replace(".0", "", regex=False).str.strip()
    )
    att["staff_count"] = pd.to_numeric(att["staff_count"], errors="coerce")
    att["avg_sales"] = pd.to_numeric(att["avg_sales"], errors="coerce")
    out = att[
        [
            "store_cd_norm",
            "store_abbrev",
            "store_full_name",
            "date",
            "time_slot",
            "hour",
            "staff_count",
            "avg_sales",
        ]
    ].dropna(subset=["hour"])
    out["hour"] = out["hour"].astype(int)
    return out


def load_receipt_sales_hourly(
    pos_path: Path, year: int, month: int, chunksize: int, exclude_bag: bool
) -> pd.DataFrame:
    ymd_min, ymd_max = month_range_ymd(year, month)
    usecols = [0, 3, 5, 8, 19, 21, 37]
    names = [
        "receipt_no",
        "business_date",
        "store_cd",
        "product_code",
        "sales_amount",
        "qty",
        "registered_at",
    ]

    parts: List[pd.DataFrame] = []
    for chunk in read_csv_fallback(pos_path, usecols=usecols, names=names, chunksize=chunksize):
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
        c["date"] = c["date"].dt.strftime("%Y-%m-%d")
        c["hour"] = c["registered_dt"].dt.hour.astype(int)
        c["store_cd_norm"] = c["store_cd"].astype(str).str.replace(".0", "", regex=False).str.strip()
        c["product_code_norm"] = (
            c["product_code"].astype(str).str.replace(".0", "", regex=False).str.strip()
        )
        c["sales"] = pd.to_numeric(c["sales_amount"], errors="coerce").fillna(0.0)
        c["qty"] = pd.to_numeric(c["qty"], errors="coerce").fillna(0.0)
        if exclude_bag:
            is_bag = c["product_code_norm"].isin(BAG_PRODUCT_CODES)
            c.loc[is_bag, "sales"] = 0.0
            c.loc[is_bag, "qty"] = 0.0
        g = (
            c.groupby(["store_cd_norm", "date", "hour", "receipt_no"], as_index=False)
            .agg(receipt_sales=("sales", "sum"), receipt_qty=("qty", "sum"))
        )
        parts.append(g)

    if not parts:
        return pd.DataFrame(
            columns=["store_cd_norm", "date", "hour", "receipt_no", "receipt_sales", "receipt_qty"]
        )

    r = pd.concat(parts, ignore_index=True)
    r = (
        r.groupby(["store_cd_norm", "date", "hour", "receipt_no"], as_index=False)
        .agg(receipt_sales=("receipt_sales", "sum"), receipt_qty=("receipt_qty", "sum"))
    )
    r = r[r["receipt_sales"] > 0].copy()
    return r


def build_baseline(
    receipts: pd.DataFrame, baseline_scope: str
) -> tuple[pd.DataFrame, float]:
    valid = receipts[receipts["receipt_sales"] > 0].copy()
    if valid.empty:
        empty = pd.DataFrame(
            columns=[
                "store_cd_norm",
                "平均商品単価",
                "平均セット率",
                "基準客単価",
                "最大客単価_分布",
                "会計件数",
            ]
        )
        return empty, 0.0

    if baseline_scope == "global":
        total_sales = float(valid["receipt_sales"].sum())
        total_qty = float(valid["receipt_qty"].sum())
        total_receipts = int(valid["receipt_no"].nunique())
        max_receipt_sales = float(valid["receipt_sales"].max())
        avg_item_price = total_sales / total_qty if total_qty > 0 else np.nan
        avg_set_rate = total_qty / total_receipts if total_receipts > 0 else np.nan
        baseline_aov = (
            avg_item_price * avg_set_rate
            if pd.notna(avg_item_price) and pd.notna(avg_set_rate)
            else (total_sales / total_receipts if total_receipts > 0 else np.nan)
        )
        df = pd.DataFrame(
            [
                {
                    "store_cd_norm": "__all__",
                    "平均商品単価": avg_item_price,
                    "平均セット率": avg_set_rate,
                    "基準客単価": baseline_aov,
                    "最大客単価_分布": max_receipt_sales,
                    "会計件数": total_receipts,
                }
            ]
        )
        return df, float(baseline_aov) if pd.notna(baseline_aov) else 0.0

    # store baseline
    b = (
        valid.groupby("store_cd_norm", as_index=False)
        .agg(
            total_sales=("receipt_sales", "sum"),
            total_qty=("receipt_qty", "sum"),
            receipts=("receipt_no", "nunique"),
            max_receipt_sales=("receipt_sales", "max"),
        )
    )
    b["平均商品単価"] = np.where(b["total_qty"] > 0, b["total_sales"] / b["total_qty"], np.nan)
    b["平均セット率"] = np.where(b["receipts"] > 0, b["total_qty"] / b["receipts"], np.nan)
    b["基準客単価"] = np.where(
        b["平均商品単価"].notna() & b["平均セット率"].notna(),
        b["平均商品単価"] * b["平均セット率"],
        np.where(b["receipts"] > 0, b["total_sales"] / b["receipts"], np.nan),
    )
    b["会計件数"] = b["receipts"]
    b["最大客単価_分布"] = b["max_receipt_sales"]
    return (
        b[
            [
                "store_cd_norm",
                "平均商品単価",
                "平均セット率",
                "基準客単価",
                "最大客単価_分布",
                "会計件数",
            ]
        ],
        float(np.nanmedian(pd.to_numeric(b["基準客単価"], errors="coerce"))),
    )


def score_receipts(
    receipts: pd.DataFrame,
    score_bins: int,
    scoring_method: str,
    baseline_scope: str,
    score_step_ratio: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = receipts.copy()
    bins = max(2, int(score_bins))
    baseline_df, global_baseline = build_baseline(out, baseline_scope)

    if scoring_method == "percentile":
        pct = out["receipt_sales"].rank(method="average", pct=True)
        out["客単価点数"] = np.ceil(pct * bins).clip(lower=1, upper=bins).astype(int)
        out["基準客単価"] = global_baseline
        out["売上倍率(対基準)"] = np.where(global_baseline > 0, out["receipt_sales"] / global_baseline, np.nan)
        out["最大客単価_分布"] = float(out["receipt_sales"].max()) if not out.empty else np.nan
        out["等間隔幅"] = np.nan
        return out, baseline_df

    # baseline methods:
    # - receipt <= baseline => 1 point
    # - baseline: above baseline step-up by ratio (default +10% per point)
    # - baseline_equal_interval: split baseline~max into equal-width bins
    if baseline_scope == "global":
        out["基準客単価"] = global_baseline
        out["最大客単価_分布"] = (
            float(baseline_df["最大客単価_分布"].iloc[0]) if not baseline_df.empty else np.nan
        )
    else:
        out = out.merge(
            baseline_df[["store_cd_norm", "基準客単価", "最大客単価_分布"]],
            on="store_cd_norm",
            how="left",
        )
        out["基準客単価"] = out["基準客単価"].fillna(global_baseline)
        global_max = float(out["receipt_sales"].max()) if not out.empty else np.nan
        out["最大客単価_分布"] = out["最大客単価_分布"].fillna(global_max)

    ratio = np.where(out["基準客単価"] > 0, out["receipt_sales"] / out["基準客単価"], np.nan)
    out["売上倍率(対基準)"] = ratio

    if scoring_method == "baseline_equal_interval":
        # score=1 for <= baseline, then split (baseline, max] into equal-width bins for 2..N.
        denom = max(1, bins - 1)
        out["等間隔幅"] = np.where(
            out["最大客単価_分布"] > out["基準客単価"],
            (out["最大客単価_分布"] - out["基準客単価"]) / denom,
            np.nan,
        )
        width = pd.to_numeric(out["等間隔幅"], errors="coerce")
        delta = out["receipt_sales"] - out["基準客単価"]
        points = np.where(
            (out["receipt_sales"] <= out["基準客単価"]) | width.isna() | (width <= 0),
            1.0,
            np.ceil(delta / width) + 1.0,
        )
        points_ser = pd.Series(points, index=out.index)
        points_num = pd.to_numeric(points_ser, errors="coerce").fillna(1.0)
        out["客単価点数"] = np.clip(points_num, 1, bins).astype(int)
        return out, baseline_df

    step = max(0.01, float(score_step_ratio))
    out["等間隔幅"] = np.nan
    points = np.where(
        ratio <= 1.0,
        1.0,
        np.floor((ratio - 1.0) / step) + 2.0,
    )
    points_ser = pd.Series(points, index=out.index)
    points_num = pd.to_numeric(points_ser, errors="coerce").fillna(1.0)
    out["客単価点数"] = np.clip(points_num, 1, bins).astype(int)
    return out, baseline_df


def aggregate_slot_scores(
    receipts_scored: pd.DataFrame, baseline_df: pd.DataFrame, baseline_scope: str
) -> pd.DataFrame:
    slot = (
        receipts_scored.groupby(["store_cd_norm", "date", "hour"], as_index=False)
        .agg(
            客数=("receipt_no", "nunique"),
            時間帯売上=("receipt_sales", "sum"),
            点数合計=("客単価点数", "sum"),
            点数平均=("客単価点数", "mean"),
            最大客単価=("receipt_sales", "max"),
            最大客単価_分布=("最大客単価_分布", "max"),
            等間隔幅=("等間隔幅", "max"),
        )
    )
    slot["時間帯平均客単価"] = np.where(slot["客数"] > 0, slot["時間帯売上"] / slot["客数"], np.nan)
    if baseline_scope == "global":
        base = float(baseline_df["基準客単価"].iloc[0]) if not baseline_df.empty else np.nan
        slot["基準客単価"] = base
        slot["平均商品単価"] = (
            float(baseline_df["平均商品単価"].iloc[0]) if not baseline_df.empty else np.nan
        )
        slot["平均セット率"] = (
            float(baseline_df["平均セット率"].iloc[0]) if not baseline_df.empty else np.nan
        )
        slot["最大客単価_分布"] = (
            float(baseline_df["最大客単価_分布"].iloc[0]) if not baseline_df.empty else np.nan
        )
    else:
        slot = slot.merge(
            baseline_df[["store_cd_norm", "基準客単価", "平均商品単価", "平均セット率"]],
            on="store_cd_norm",
            how="left",
        )
    return slot


def evaluate_productivity(slot_merged: pd.DataFrame) -> pd.DataFrame:
    df = slot_merged.copy()
    df["1人あたり点数"] = np.where(
        df["staff_count"] > 0, df["点数合計"] / df["staff_count"], np.nan
    )
    df["1人あたり売上"] = np.where(
        df["staff_count"] > 0, df["時間帯売上"] / df["staff_count"], np.nan
    )
    rank_base = df["1人あたり点数"].fillna(0.0)
    df["生産性評価(100点)"] = (rank_base.rank(method="average", pct=True) * 100).round(1)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score monthly AOV per receipt and evaluate productivity by time slot."
    )
    parser.add_argument("--year", type=int, required=True, help="Target year")
    parser.add_argument("--month", type=int, required=True, help="Target month")
    parser.add_argument(
        "--attendance",
        default="attendance_summary.csv",
        help="attendance_summary.csv path",
    )
    parser.add_argument(
        "--pos",
        default="",
        help="POS csv path (optional, auto-detect when omitted)",
    )
    parser.add_argument(
        "--scoring-method",
        choices=["baseline", "baseline_equal_interval", "percentile"],
        default="baseline_equal_interval",
        help=(
            "baseline: baseline AOV threshold with ratio-step scoring, "
            "baseline_equal_interval: split baseline~max into equal-width bands, "
            "percentile: rank-based scoring"
        ),
    )
    parser.add_argument(
        "--baseline-scope",
        choices=["store", "global"],
        default="store",
        help="Baseline scope for baseline scoring",
    )
    parser.add_argument(
        "--score-step-ratio",
        type=float,
        default=0.10,
        help="Point step above baseline (ratio). 0.10 means +10%% per point.",
    )
    parser.add_argument(
        "--exclude-bag",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exclude bag-product lines from baseline and receipt amount scoring",
    )
    parser.add_argument("--score-bins", type=int, default=10, help="Score bins (default 10)")
    parser.add_argument("--chunksize", type=int, default=300000, help="POS read chunksize")
    parser.add_argument(
        "--output-detail",
        default="time_slot_aov_scoring.csv",
        help="Output detail csv",
    )
    parser.add_argument(
        "--output-store-hour",
        default="time_slot_aov_scoring_store_hour.csv",
        help="Output store-hour summary csv",
    )
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    attendance_path = Path(args.attendance)
    if not attendance_path.is_absolute():
        attendance_path = attendance_path.resolve()
        if not attendance_path.exists():
            attendance_path = (base_dir / args.attendance).resolve()

    if args.pos:
        pos_path = Path(args.pos)
        if not pos_path.is_absolute():
            pos_path = pos_path.resolve()
            if not pos_path.exists():
                pos_path = (base_dir / args.pos).resolve()
    else:
        cands = sorted(
            [p for p in base_dir.glob(f"*{args.year}*.csv") if p.stat().st_size > 100_000_000],
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        if not cands:
            raise FileNotFoundError("POS csv not found. pass --pos")
        pos_path = cands[0]

    att = load_attendance_slots(attendance_path, args.year, args.month)
    receipts = load_receipt_sales_hourly(
        pos_path, args.year, args.month, args.chunksize, args.exclude_bag
    )
    if receipts.empty:
        raise ValueError("No POS records for target year/month")

    receipts_scored, baseline_df = score_receipts(
        receipts,
        args.score_bins,
        args.scoring_method,
        args.baseline_scope,
        args.score_step_ratio,
    )
    slot_scores = aggregate_slot_scores(receipts_scored, baseline_df, args.baseline_scope)
    merged = att.merge(slot_scores, on=["store_cd_norm", "date", "hour"], how="left")
    for col in [
        "客数",
        "時間帯売上",
        "点数合計",
        "点数平均",
        "最大客単価",
        "最大客単価_分布",
        "時間帯平均客単価",
        "基準客単価",
        "平均商品単価",
        "平均セット率",
        "等間隔幅",
    ]:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)
    evaluated = evaluate_productivity(merged)

    detail_cols = [
        "date",
        "store_abbrev",
        "store_full_name",
        "store_cd_norm",
        "time_slot",
        "hour",
        "staff_count",
        "avg_sales",
        "客数",
        "時間帯売上",
        "時間帯平均客単価",
        "最大客単価",
        "最大客単価_分布",
        "等間隔幅",
        "基準客単価",
        "平均商品単価",
        "平均セット率",
        "点数合計",
        "点数平均",
        "1人あたり点数",
        "1人あたり売上",
        "生産性評価(100点)",
    ]
    detail_cols = [c for c in detail_cols if c in evaluated.columns]
    detail = evaluated[detail_cols].sort_values(["date", "store_abbrev", "hour"])

    store_hour = (
        detail.groupby(["store_abbrev", "store_full_name", "hour"], as_index=False)
        .agg(
            月間客数=("客数", "sum"),
            月間売上=("時間帯売上", "sum"),
            基準客単価_平均=("基準客単価", "mean"),
            月間点数合計=("点数合計", "sum"),
            平均スタッフ数=("staff_count", "mean"),
            平均1人あたり点数=("1人あたり点数", "mean"),
            平均生産性評価=("生産性評価(100点)", "mean"),
        )
        .sort_values(["store_abbrev", "hour"])
    )

    output_detail = Path(args.output_detail)
    if not output_detail.is_absolute():
        output_detail = output_detail.resolve()
        if not output_detail.parent.exists():
            output_detail = (base_dir / args.output_detail).resolve()
    output_store_hour = Path(args.output_store_hour)
    if not output_store_hour.is_absolute():
        output_store_hour = output_store_hour.resolve()
        if not output_store_hour.parent.exists():
            output_store_hour = (base_dir / args.output_store_hour).resolve()

    detail.to_csv(output_detail, index=False, encoding="utf-8-sig")
    store_hour.to_csv(output_store_hour, index=False, encoding="utf-8-sig")

    print(f"saved: {output_detail}")
    print(f"saved: {output_store_hour}")
    print(
        "rows:",
        len(detail),
        "stores:",
        detail["store_cd_norm"].nunique(),
        "avg_productivity_score:",
        round(float(detail["生産性評価(100点)"].mean()), 2),
    )
    if "基準客単価" in detail.columns:
        print(
            "baseline_aov_mean:",
            round(float(pd.to_numeric(detail["基準客単価"], errors="coerce").mean()), 2),
            "scoring_method:",
            args.scoring_method,
            "baseline_scope:",
            args.baseline_scope,
            "score_step_ratio:",
            args.score_step_ratio,
        )


if __name__ == "__main__":
    main()
