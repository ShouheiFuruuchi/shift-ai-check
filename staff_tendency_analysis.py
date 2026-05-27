import argparse
import datetime as dt
import math
import re
from pathlib import Path
from typing import Dict, List, Tuple

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

EASY_COLUMN_MAP = {
    "emp_cd": "社員CD",
    "name": "氏名",
    "on_slots": "出勤した時間帯数",
    "on_weight_hours": "実質勤務時間",
    "avg_sales_power": "販売力(5点満点)",
    "on_aov": "勤務時の客単価",
    "baseline_aov_matched": "基準客単価(同じ店・同じ時間)",
    "aov_lift_pct": "客単価の上昇率(%)",
    "on_aov_raw": "勤務時客単価(実測)",
    "baseline_aov_raw_matched": "基準客単価(実測)",
    "aov_lift_raw_pct": "客単価の上昇率(実測,%)",
    "aov_adjustment": "客単価補正モード",
    "aov_traffic_beta": "客数補正係数β",
    "on_set_rate_line2": "勤務時セット率(点数2点以上)",
    "baseline_set_rate_line2_matched": "基準セット率(点数2点以上)",
    "set_rate_line2_diff_pp": "セット率の差(点数2点以上,pt)",
    "on_set_rate_qty2": "勤務時セット率(数量2点以上)",
    "baseline_set_rate_qty2_matched": "基準セット率(数量2点以上)",
    "set_rate_qty2_diff_pp": "セット率の差(数量2点以上,pt)",
    "on_units_per_receipt": "勤務時1会計あたり点数",
    "baseline_units_per_receipt_matched": "基準1会計あたり点数",
    "units_per_receipt_diff": "1会計あたり点数の差",
    "matched_key_count": "比較に使えた条件数",
    "score_aov": "客単価スコア(100点)",
    "score_set_line2": "セット率スコア(点数2点以上,100点)",
    "score_set_qty2": "セット率スコア(数量2点以上,100点)",
    "score_sales_power": "販売力スコア(100点)",
    "tendency_score": "総合スコア(100点)",
}

EASY_OUTPUT_ORDER = [
    "emp_cd",
    "name",
    "on_slots",
    "on_weight_hours",
    "avg_sales_power",
    "score_sales_power",
    "on_aov",
    "baseline_aov_matched",
    "aov_lift_pct",
    "on_aov_raw",
    "baseline_aov_raw_matched",
    "aov_lift_raw_pct",
    "aov_adjustment",
    "aov_traffic_beta",
    "score_aov",
    "on_set_rate_line2",
    "baseline_set_rate_line2_matched",
    "set_rate_line2_diff_pp",
    "score_set_line2",
    "on_set_rate_qty2",
    "baseline_set_rate_qty2_matched",
    "set_rate_qty2_diff_pp",
    "score_set_qty2",
    "on_units_per_receipt",
    "baseline_units_per_receipt_matched",
    "units_per_receipt_diff",
    "matched_key_count",
    "tendency_score",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze employee tendency by matching attendance slots and POS slots."
    )
    parser.add_argument("--year", type=int, required=True, help="Target year (e.g. 2025)")
    parser.add_argument("--month", type=int, required=True, help="Target month (1-12)")
    parser.add_argument(
        "--attendance",
        default="attendance_summary.csv",
        help="Path to attendance summary csv",
    )
    parser.add_argument(
        "--pos",
        default="販売伝票明細 (2025).csv",
        help="Path to POS detail csv",
    )
    parser.add_argument(
        "--min-slots",
        type=int,
        default=30,
        help="Minimum on-duty slots required per employee",
    )
    parser.add_argument(
        "--output",
        default="staff_tendency_analysis.csv",
        help="Output analysis csv",
    )
    parser.add_argument(
        "--top-output",
        default="staff_tendency_top20.csv",
        help="Output top20 csv",
    )
    parser.add_argument(
        "--presence-mode",
        choices=["break_weighted", "store_stay"],
        default="break_weighted",
        help="break_weighted=30min break 0.5 and 45/60min break 0.0, store_stay=ignore break and use 1.0 for all present slots",
    )
    parser.add_argument(
        "--weight-aov",
        type=float,
        default=0.30,
        help="Weight for AOV lift in tendency score",
    )
    parser.add_argument(
        "--weight-set-line2",
        type=float,
        default=0.15,
        help="Weight for set-rate(line>=2) uplift in tendency score",
    )
    parser.add_argument(
        "--weight-set-qty2",
        type=float,
        default=0.05,
        help="Weight for set-rate(qty>=2) uplift in tendency score",
    )
    parser.add_argument(
        "--weight-sales-power",
        type=float,
        default=0.50,
        help="Weight for avg sales power in tendency score",
    )
    parser.add_argument(
        "--aov-adjustment",
        choices=["none", "list_price", "list_price_traffic"],
        default="list_price_traffic",
        help="AOV adjustment mode: none/raw, list-price adjusted, or list-price + customer-count adjusted",
    )
    parser.add_argument(
        "--traffic-adjust-clip",
        type=float,
        default=0.30,
        help="Clip range for customer-count adjustment factor (+/- ratio). 0.30 means 0.70-1.30.",
    )
    return parser.parse_args()


def load_attendance_members(
    attendance_path: Path, year: int, month: int, presence_mode: str
) -> pd.DataFrame:
    att = pd.read_csv(attendance_path, encoding="utf-8-sig", dtype={"store_cd_full": "string"})
    prefix = f"{year:04d}-{month:02d}-"
    att = att[att["date"].astype(str).str.startswith(prefix)].copy()
    att = att[att["error_type"].fillna("") == ""].copy()

    att["store_cd_full_norm"] = (
        att["store_cd_full"].astype(str).str.replace(".0", "", regex=False).str.strip()
    )
    att["slot_start"] = pd.to_datetime(
        att["date"] + " " + att["time_slot"].astype(str).str.split("-").str[0], errors="coerce"
    )
    att = att.dropna(subset=["slot_start"])
    att["hour"] = att["slot_start"].dt.hour

    member_cols = [c for c in att.columns if c.startswith("member_")]
    rows: List[dict] = []
    for r in att.itertuples(index=False):
        for c in member_cols:
            txt = getattr(r, c)
            if pd.isna(txt):
                continue
            s = str(txt).strip()
            if not s or "(" not in s or ")" not in s:
                continue
            name = s.split("(", 1)[0].strip()
            inside = s[s.find("(") + 1 : s.rfind(")")]
            parts = inside.split(":", 3)
            if len(parts) < 2:
                continue
            status = parts[0].strip()
            emp_cd = parts[1].strip()
            sales_power_raw = parts[2].strip() if len(parts) >= 3 else ""
            if not re.fullmatch(r"\d+", emp_cd):
                continue
            try:
                sales_power = float(sales_power_raw) if sales_power_raw else np.nan
            except Exception:
                sales_power = np.nan

            weight = 1.0
            if presence_mode == "break_weighted":
                if status.startswith("休憩"):
                    m = re.search(r"(\d+)", status)
                    break_min = int(m.group(1)) if m else None
                    if break_min == 30:
                        weight = 0.5
                    else:
                        weight = 0.0

            rows.append(
                {
                    "emp_cd": emp_cd,
                    "name": name,
                    "store_cd_full_norm": r.store_cd_full_norm,
                    "slot_start": r.slot_start,
                    "hour": int(r.hour),
                    "weight": float(weight),
                    "sales_power": sales_power,
                }
            )

    mem = pd.DataFrame(rows)
    if mem.empty:
        return mem
    mem["slot_id"] = (
        mem["store_cd_full_norm"]
        + "|"
        + mem["slot_start"].dt.strftime("%Y-%m-%d %H:%M:%S")
    )
    # If same employee appears multiple columns in one slot, keep the strongest weight.
    mem = (
        mem.groupby(["emp_cd", "name", "store_cd_full_norm", "slot_start", "hour", "slot_id"], as_index=False)
        .agg(weight=("weight", "max"), sales_power=("sales_power", "mean"))
    )
    return mem


def load_pos_slot_metrics(pos_path: Path, year: int, month: int) -> pd.DataFrame:
    month_start = dt.date(year, month, 1)
    if month == 12:
        month_end = dt.date(year + 1, 1, 1) - dt.timedelta(days=1)
    else:
        month_end = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    ymd_min = int(month_start.strftime("%Y%m%d"))
    ymd_max = int(month_end.strftime("%Y%m%d"))

    # POS file is large; read only required columns by index to avoid encoding-dependent header matching.
    # 0=伝票番号, 3=営業日付, 5=店舗コード, 8=商品コード, 16=標準金額, 19=販売金額, 21=数量, 37=登録日時
    usecols = [0, 3, 5, 8, 16, 19, 21, 37]
    col_names = [
        "receipt_no",
        "business_date",
        "store_cd",
        "product_code",
        "list_amount",
        "sales_amount",
        "qty",
        "registered_at",
    ]

    chunks: List[pd.DataFrame] = []
    for chunk in pd.read_csv(
        pos_path,
        encoding="cp932",
        usecols=usecols,
        header=0,
        names=col_names,
        chunksize=300_000,
        low_memory=False,
    ):
        d = pd.to_numeric(chunk["business_date"], errors="coerce").astype("Int64")
        mask = (d >= ymd_min) & (d <= ymd_max)
        if not mask.any():
            continue
        c = chunk.loc[mask].copy()
        c["date"] = pd.to_datetime(d[mask].astype(str), format="%Y%m%d", errors="coerce")
        c = c.dropna(subset=["date"])
        c["registered_dt"] = pd.to_datetime(c["registered_at"], errors="coerce")
        c = c.dropna(subset=["registered_dt"])
        c["slot_start"] = c["date"] + pd.to_timedelta(c["registered_dt"].dt.hour, unit="h")
        c["store_cd_full_norm"] = c["store_cd"].astype(str).str.replace(".0", "", regex=False).str.strip()
        c["product_code_norm"] = c["product_code"].astype(str).str.replace(".0", "", regex=False).str.strip()
        c["is_bag"] = c["product_code_norm"].isin(BAG_PRODUCT_CODES)
        c["list_sales"] = pd.to_numeric(c["list_amount"], errors="coerce").fillna(0.0)
        c["sales"] = pd.to_numeric(c["sales_amount"], errors="coerce").fillna(0.0)
        c["qty_num"] = pd.to_numeric(c["qty"], errors="coerce").fillna(0.0)
        chunks.append(
            c[
                [
                    "store_cd_full_norm",
                    "slot_start",
                    "receipt_no",
                    "list_sales",
                    "sales",
                    "qty_num",
                    "is_bag",
                ]
            ]
        )

    if not chunks:
        return pd.DataFrame()

    pos = pd.concat(chunks, ignore_index=True)
    receipt_slot = (
        pos.groupby(["store_cd_full_norm", "slot_start", "receipt_no"], as_index=False)
        .agg(
            receipt_list_sales=("list_sales", "sum"),
            receipt_sales=("sales", "sum"),
            receipt_qty=("qty_num", "sum"),
            line_count=("qty_num", "size"),
            non_bag_qty=("qty_num", lambda s: float(s[pos.loc[s.index, "is_bag"] == False].sum())),
            non_bag_line_count=("is_bag", lambda s: int((~s).sum())),
        )
    )
    slot = (
        receipt_slot.groupby(["store_cd_full_norm", "slot_start"], as_index=False)
        .agg(
            customers=("receipt_no", "nunique"),
            list_sales=("receipt_list_sales", "sum"),
            sales=("receipt_sales", "sum"),
            total_qty=("receipt_qty", "sum"),
            non_bag_total_qty=("non_bag_qty", "sum"),
            set_receipts_line2=("non_bag_line_count", lambda s: int((s >= 2).sum())),
            set_receipts_qty2=("non_bag_qty", lambda s: int((s >= 2).sum())),
        )
    )
    slot["aov"] = np.where(slot["customers"] > 0, slot["sales"] / slot["customers"], np.nan)
    slot["aov_list"] = np.where(slot["customers"] > 0, slot["list_sales"] / slot["customers"], np.nan)
    slot["discount_rate"] = np.where(
        slot["list_sales"] > 0,
        (slot["list_sales"] - slot["sales"]) / slot["list_sales"],
        np.nan,
    )
    slot["set_rate_line2"] = np.where(
        slot["customers"] > 0, slot["set_receipts_line2"] / slot["customers"], np.nan
    )
    slot["set_rate_qty2"] = np.where(
        slot["customers"] > 0, slot["set_receipts_qty2"] / slot["customers"], np.nan
    )
    slot["units_per_receipt"] = np.where(
        slot["customers"] > 0, slot["non_bag_total_qty"] / slot["customers"], np.nan
    )
    slot["hour"] = slot["slot_start"].dt.hour
    slot["slot_id"] = (
        slot["store_cd_full_norm"] + "|" + slot["slot_start"].dt.strftime("%Y-%m-%d %H:%M:%S")
    )
    return slot


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    wsum = weights.sum()
    if wsum <= 0:
        return np.nan
    return float((values * weights).sum() / wsum)


def apply_aov_adjustment(
    slot: pd.DataFrame, mode: str, traffic_adjust_clip: float
) -> Tuple[pd.DataFrame, float]:
    adjusted = slot.copy()
    adjusted["aov_eval"] = adjusted["aov"]

    if mode in ("list_price", "list_price_traffic"):
        adjusted["aov_eval"] = np.where(
            adjusted["aov_list"].notna() & (adjusted["aov_list"] > 0),
            adjusted["aov_list"],
            adjusted["aov"],
        )

    beta = 0.0
    if mode == "list_price_traffic":
        valid = adjusted[
            adjusted["customers"].notna()
            & adjusted["aov_eval"].notna()
            & (adjusted["customers"] > 0)
            & (adjusted["aov_eval"] > 0)
        ].copy()
        if len(valid) >= 10:
            x = np.log(valid["customers"].astype(float))
            y = np.log(valid["aov_eval"].astype(float))
            var_x = float(np.var(x))
            if var_x > 1e-12:
                cov_xy = float(np.cov(x, y, ddof=0)[0, 1])
                beta = max(-1.0, min(1.0, cov_xy / var_x))

        key_median = (
            adjusted.groupby(["store_cd_full_norm", "hour"], as_index=False)
            .agg(customers_key_median=("customers", "median"))
        )
        adjusted = adjusted.merge(key_median, on=["store_cd_full_norm", "hour"], how="left")
        ratio = np.where(
            (adjusted["customers"] > 0) & (adjusted["customers_key_median"] > 0),
            adjusted["customers_key_median"] / adjusted["customers"],
            1.0,
        )
        factor = np.power(ratio, beta)
        clip = max(0.0, float(traffic_adjust_clip))
        low = max(0.01, 1.0 - clip)
        high = 1.0 + clip
        factor = np.clip(factor, low, high)
        adjusted["aov_eval"] = adjusted["aov_eval"] * factor
    else:
        adjusted["customers_key_median"] = np.nan

    adjusted["aov_adjustment"] = mode
    adjusted["aov_traffic_beta"] = beta
    return adjusted, beta


def z_to_percentile_score(z: pd.Series) -> pd.Series:
    # Convert z-score to 0-100 percentile-like score.
    return z.apply(lambda v: 100.0 * 0.5 * (1.0 + math.erf(float(v) / math.sqrt(2.0))))


def analyze_tendency(
    mem: pd.DataFrame,
    slot: pd.DataFrame,
    min_slots: int,
    weight_aov: float,
    weight_set_line2: float,
    weight_set_qty2: float,
    weight_sales_power: float,
    aov_adjustment: str,
    traffic_adjust_clip: float,
) -> pd.DataFrame:
    if mem.empty or slot.empty:
        return pd.DataFrame()

    slot_eval, traffic_beta = apply_aov_adjustment(slot, aov_adjustment, traffic_adjust_clip)
    on = mem.merge(
        slot_eval[
            [
                "store_cd_full_norm",
                "slot_start",
                "hour",
                "slot_id",
                "customers",
                "sales",
                "aov",
                "aov_eval",
                "set_rate_line2",
                "set_rate_qty2",
                "units_per_receipt",
            ]
        ],
        on=["store_cd_full_norm", "slot_start", "hour", "slot_id"],
        how="inner",
    )
    if on.empty:
        return pd.DataFrame()

    key_groups: Dict[Tuple[str, int], pd.DataFrame] = {
        k: g[
            [
                "slot_id",
                "aov",
                "aov_eval",
                "set_rate_line2",
                "set_rate_qty2",
                "units_per_receipt",
                "customers",
            ]
        ].copy()
        for k, g in slot_eval.groupby(["store_cd_full_norm", "hour"])
    }

    results: List[dict] = []
    for (emp_cd, name), g in on.groupby(["emp_cd", "name"]):
        slot_count = int(g["slot_id"].nunique())
        if slot_count < min_slots:
            continue
        on_slot_ids = set(g["slot_id"].tolist())
        key_counts = g.groupby(["store_cd_full_norm", "hour"]).size().to_dict()

        base_weight_sum = 0.0
        base_aov_raw_sum = 0.0
        base_aov_sum = 0.0
        base_set_line_sum = 0.0
        base_set_qty_sum = 0.0
        base_upr_sum = 0.0
        base_keys = 0

        for key, count in key_counts.items():
            kg = key_groups.get(key)
            if kg is None or kg.empty:
                continue
            bg = kg[~kg["slot_id"].isin(on_slot_ids)]
            if bg.empty:
                continue
            base_aov_raw = bg["aov"].mean()
            base_aov = bg["aov_eval"].mean()
            base_set_line = bg["set_rate_line2"].mean()
            base_set_qty = bg["set_rate_qty2"].mean()
            base_upr = bg["units_per_receipt"].mean()
            base_aov_raw_sum += float(base_aov_raw) * count
            base_aov_sum += float(base_aov) * count
            base_set_line_sum += float(base_set_line) * count
            base_set_qty_sum += float(base_set_qty) * count
            base_upr_sum += float(base_upr) * count
            base_weight_sum += count
            base_keys += 1

        if base_weight_sum == 0:
            continue

        on_weight = g["weight"].fillna(0.0)
        on_aov_raw = weighted_mean(g["aov"], on_weight)
        on_aov = weighted_mean(g["aov_eval"], on_weight)
        on_set_line = weighted_mean(g["set_rate_line2"], on_weight)
        on_set_qty = weighted_mean(g["set_rate_qty2"], on_weight)
        on_upr = weighted_mean(g["units_per_receipt"], on_weight)
        on_sales_power = weighted_mean(g["sales_power"], on_weight)

        base_aov_raw = base_aov_raw_sum / base_weight_sum
        base_aov = base_aov_sum / base_weight_sum
        base_set_line = base_set_line_sum / base_weight_sum
        base_set_qty = base_set_qty_sum / base_weight_sum
        base_upr = base_upr_sum / base_weight_sum

        aov_lift_raw_pct = np.nan
        if pd.notna(base_aov_raw) and base_aov_raw != 0:
            aov_lift_raw_pct = (on_aov_raw / base_aov_raw - 1.0) * 100.0

        aov_lift_pct = np.nan
        if pd.notna(base_aov) and base_aov != 0:
            aov_lift_pct = (on_aov / base_aov - 1.0) * 100.0

        results.append(
            {
                "emp_cd": emp_cd,
                "name": name,
                "on_slots": slot_count,
                "on_weight_hours": float(on_weight.sum()),
                "avg_sales_power": on_sales_power,
                "on_aov": on_aov,
                "baseline_aov_matched": base_aov,
                "aov_lift_pct": aov_lift_pct,
                "on_aov_raw": on_aov_raw,
                "baseline_aov_raw_matched": base_aov_raw,
                "aov_lift_raw_pct": aov_lift_raw_pct,
                "aov_adjustment": aov_adjustment,
                "aov_traffic_beta": traffic_beta,
                "on_set_rate_line2": on_set_line,
                "baseline_set_rate_line2_matched": base_set_line,
                "set_rate_line2_diff_pp": (on_set_line - base_set_line) * 100.0,
                "on_set_rate_qty2": on_set_qty,
                "baseline_set_rate_qty2_matched": base_set_qty,
                "set_rate_qty2_diff_pp": (on_set_qty - base_set_qty) * 100.0,
                "on_units_per_receipt": on_upr,
                "baseline_units_per_receipt_matched": base_upr,
                "units_per_receipt_diff": on_upr - base_upr,
                "matched_key_count": base_keys,
            }
        )

    if not results:
        return pd.DataFrame()

    out = pd.DataFrame(results)
    # Composite tendency score.
    # Sales power is an absolute 5-point internal rating, so treat it as fixed 0-100 scale,
    # not sample-relative z-score.
    for col in ["aov_lift_pct", "set_rate_line2_diff_pp", "set_rate_qty2_diff_pp"]:
        mu = out[col].mean(skipna=True)
        sd = out[col].std(skipna=True)
        if pd.notna(sd) and sd > 0:
            out[f"z_{col}"] = (out[col] - mu) / sd
        else:
            out[f"z_{col}"] = 0.0
    total_w = weight_aov + weight_set_line2 + weight_set_qty2 + weight_sales_power
    if total_w <= 0:
        weight_aov, weight_set_line2, weight_set_qty2, weight_sales_power = 0.30, 0.15, 0.05, 0.50
        total_w = 1.0
    wa = weight_aov / total_w
    wsl = weight_set_line2 / total_w
    wsq = weight_set_qty2 / total_w
    wsp = weight_sales_power / total_w
    out["score_aov"] = z_to_percentile_score(out["z_aov_lift_pct"].fillna(0.0))
    out["score_set_line2"] = z_to_percentile_score(out["z_set_rate_line2_diff_pp"].fillna(0.0))
    out["score_set_qty2"] = z_to_percentile_score(out["z_set_rate_qty2_diff_pp"].fillna(0.0))
    out["score_sales_power"] = (
        pd.to_numeric(out["avg_sales_power"], errors="coerce").clip(lower=0.0, upper=5.0) / 5.0 * 100.0
    ).fillna(0.0)
    out["tendency_score"] = (
        wa * out["score_aov"]
        + wsl * out["score_set_line2"]
        + wsq * out["score_set_qty2"]
        + wsp * out["score_sales_power"]
    )
    out = out.sort_values("tendency_score", ascending=False).reset_index(drop=True)
    return out


def main() -> None:
    args = parse_args()
    attendance_path = Path(args.attendance)
    pos_path = Path(args.pos)
    mem = load_attendance_members(attendance_path, args.year, args.month, args.presence_mode)
    slot = load_pos_slot_metrics(pos_path, args.year, args.month)
    result = analyze_tendency(
        mem,
        slot,
        args.min_slots,
        args.weight_aov,
        args.weight_set_line2,
        args.weight_set_qty2,
        args.weight_sales_power,
        args.aov_adjustment,
        args.traffic_adjust_clip,
    )

    if result.empty:
        print("No analyzable rows.")
        return

    available_keys = [k for k in EASY_OUTPUT_ORDER if k in result.columns]
    export_df = result[available_keys].rename(columns=EASY_COLUMN_MAP)
    export_df.to_csv(args.output, index=False, encoding="utf-8-sig")
    export_df.head(20).to_csv(args.top_output, index=False, encoding="utf-8-sig")

    view_cols = [
        EASY_COLUMN_MAP["emp_cd"],
        EASY_COLUMN_MAP["name"],
        EASY_COLUMN_MAP["on_slots"],
        EASY_COLUMN_MAP["avg_sales_power"],
        EASY_COLUMN_MAP["aov_lift_pct"],
        EASY_COLUMN_MAP["set_rate_line2_diff_pp"],
        EASY_COLUMN_MAP["tendency_score"],
    ]
    print(f"presence_mode: {args.presence_mode}")
    print(
        "weights:"
        f" aov={args.weight_aov}, set_line2={args.weight_set_line2},"
        f" set_qty2={args.weight_set_qty2}, sales_power={args.weight_sales_power}"
    )
    print(
        "aov_adjustment:"
        f" mode={args.aov_adjustment}, traffic_adjust_clip={args.traffic_adjust_clip}"
    )
    print(f"saved: {args.output}")
    print(f"saved: {args.top_output}")
    preview = export_df.head(20)[view_cols].round(3).to_string(index=False)
    try:
        print(preview)
    except UnicodeEncodeError:
        print(preview.encode("cp932", errors="replace").decode("cp932", errors="replace"))


if __name__ == "__main__":
    main()
