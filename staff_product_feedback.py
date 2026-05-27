import argparse
import datetime as dt
from collections import defaultdict
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from staff_tendency_analysis import BAG_PRODUCT_CODES, load_attendance_members


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create product-based feedback report for one employee."
    )
    parser.add_argument("--emp-cd", required=True, help="Target employee code")
    parser.add_argument("--year", type=int, required=True, help="Target year")
    parser.add_argument("--month", type=int, required=True, help="Target month (1-12)")
    parser.add_argument("--attendance", default="attendance_summary.csv", help="Attendance summary csv path")
    parser.add_argument("--pos", default="", help="POS detail csv path (optional; auto-detect when omitted)")
    parser.add_argument(
        "--presence-mode",
        choices=["break_weighted", "store_stay"],
        default="store_stay",
        help="How to treat break slots",
    )
    parser.add_argument(
        "--exclude-bag",
        action="store_true",
        default=True,
        help="Exclude bag product codes from product metrics",
    )
    parser.add_argument(
        "--output-prefix",
        default="",
        help="Output prefix. default=product_feedback_<emp>_<yyyy-mm>",
    )
    return parser.parse_args()


def detect_pos_file(pos_arg: str, year: int) -> Path:
    if pos_arg:
        p = Path(pos_arg)
        if p.exists():
            return p
    cands = sorted(
        [p for p in Path(".").glob(f"*{year}*.csv") if p.stat().st_size > 100_000_000],
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not cands:
        raise FileNotFoundError("POS csv not found. Please pass --pos.")
    return cands[0]


def month_range_ymd(year: int, month: int) -> Tuple[int, int]:
    start = dt.date(year, month, 1)
    if month == 12:
        end = dt.date(year + 1, 1, 1) - dt.timedelta(days=1)
    else:
        end = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    return int(start.strftime("%Y%m%d")), int(end.strftime("%Y%m%d"))


def load_pos_month_product_data(
    pos_path: Path, year: int, month: int, exclude_bag: bool
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    ymd_min, ymd_max = month_range_ymd(year, month)

    # 0=receipt_no, 3=business_date, 5=store_cd, 8=product_code, 10=product_name, 19=sales, 21=qty, 37=registered_at
    usecols = [0, 3, 5, 8, 10, 19, 21, 37]
    names = [
        "receipt_no",
        "business_date",
        "store_cd",
        "product_code",
        "product_name",
        "sales_amount",
        "qty",
        "registered_at",
    ]

    parts = []
    for chunk in pd.read_csv(
        pos_path,
        encoding="cp932",
        usecols=usecols,
        header=0,
        names=names,
        chunksize=300_000,
        low_memory=False,
    ):
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
        c["hour"] = c["slot_start"].dt.hour
        c["store_cd_full_norm"] = c["store_cd"].astype(str).str.replace(".0", "", regex=False).str.strip()
        c["product_code_norm"] = (
            c["product_code"].astype(str).str.replace(".0", "", regex=False).str.strip()
        )
        c["product_name"] = c["product_name"].astype(str).str.strip()
        c["sales"] = pd.to_numeric(c["sales_amount"], errors="coerce").fillna(0.0)
        c["qty_num"] = pd.to_numeric(c["qty"], errors="coerce").fillna(0.0)
        if exclude_bag:
            c = c[~c["product_code_norm"].isin(BAG_PRODUCT_CODES)].copy()
            if c.empty:
                continue
        parts.append(
            c[
                [
                    "store_cd_full_norm",
                    "slot_start",
                    "hour",
                    "receipt_no",
                    "product_code_norm",
                    "product_name",
                    "sales",
                    "qty_num",
                ]
            ]
        )

    if not parts:
        return pd.DataFrame(), pd.DataFrame()

    df = pd.concat(parts, ignore_index=True)
    df["slot_id"] = df["store_cd_full_norm"] + "|" + df["slot_start"].dt.strftime("%Y-%m-%d %H:%M:%S")

    name_map = (
        df.groupby(["product_code_norm", "product_name"], as_index=False)
        .size()
        .sort_values(["product_code_norm", "size"], ascending=[True, False])
        .drop_duplicates("product_code_norm")
        .rename(columns={"product_name": "product_name_best"})[
            ["product_code_norm", "product_name_best"]
        ]
    )

    slot_tot = (
        df.groupby(["store_cd_full_norm", "slot_start", "hour", "slot_id"], as_index=False)
        .agg(
            slot_sales=("sales", "sum"),
            slot_receipts=("receipt_no", "nunique"),
            slot_qty=("qty_num", "sum"),
        )
    )

    slot_prod = (
        df.groupby(
            ["store_cd_full_norm", "slot_start", "hour", "slot_id", "product_code_norm"],
            as_index=False,
        )
        .agg(
            prod_sales=("sales", "sum"),
            prod_qty=("qty_num", "sum"),
            prod_receipts=("receipt_no", "nunique"),
        )
        .merge(name_map, on="product_code_norm", how="left")
    )
    slot_prod["product_name_best"] = slot_prod["product_name_best"].fillna("")
    return slot_tot, slot_prod


def build_product_feedback(
    emp_cd: str, mem: pd.DataFrame, slot_tot: pd.DataFrame, slot_prod: pd.DataFrame
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    target = mem[mem["emp_cd"] == str(emp_cd)].copy()
    if target.empty:
        raise ValueError(f"emp_cd={emp_cd} not found in attendance.")

    on_slots = target.merge(
        slot_tot[["store_cd_full_norm", "slot_start", "hour", "slot_id"]],
        on=["store_cd_full_norm", "slot_start", "hour"],
        how="inner",
    )
    if "slot_id" not in on_slots.columns:
        on_slots["slot_id"] = (
            on_slots["store_cd_full_norm"]
            + "|"
            + pd.to_datetime(on_slots["slot_start"]).dt.strftime("%Y-%m-%d %H:%M:%S")
        )
    on_slots = on_slots.drop_duplicates(["store_cd_full_norm", "slot_start", "hour", "slot_id"])
    if on_slots.empty:
        raise ValueError(f"emp_cd={emp_cd} has no merged slots in POS.")

    on_slot_ids = set(on_slots["slot_id"].tolist())
    key_counts = on_slots.groupby(["store_cd_full_norm", "hour"]).size().to_dict()

    on_tot = slot_tot[slot_tot["slot_id"].isin(on_slot_ids)].copy()
    on_total_sales = float(on_tot["slot_sales"].sum())
    on_total_receipts = float(on_tot["slot_receipts"].sum())
    on_total_qty = float(on_tot["slot_qty"].sum())

    on_prod = (
        slot_prod[slot_prod["slot_id"].isin(on_slot_ids)]
        .groupby(["product_code_norm", "product_name_best"], as_index=False)
        .agg(
            on_sales=("prod_sales", "sum"),
            on_qty=("prod_qty", "sum"),
            on_receipts_with_product=("prod_receipts", "sum"),
        )
    )
    if on_prod.empty or on_total_sales <= 0 or on_total_receipts <= 0:
        raise ValueError(f"emp_cd={emp_cd} has no analyzable product sales in target month.")

    # Build baseline by matched store-hour keys (excluding target employee slots).
    key_groups_tot = {k: g.copy() for k, g in slot_tot.groupby(["store_cd_full_norm", "hour"])}
    key_groups_prod = {k: g.copy() for k, g in slot_prod.groupby(["store_cd_full_norm", "hour"])}

    total_key_weight = 0.0
    base_share_sum = defaultdict(float)
    base_attach_sum = defaultdict(float)
    base_qtypr_sum = defaultdict(float)
    matched_key_count = 0

    for key, count in key_counts.items():
        k_tot = key_groups_tot.get(key)
        k_prod = key_groups_prod.get(key)
        if k_tot is None or k_tot.empty or k_prod is None or k_prod.empty:
            continue
        bg_tot = k_tot[~k_tot["slot_id"].isin(on_slot_ids)]
        if bg_tot.empty:
            continue
        bg_ids = set(bg_tot["slot_id"].tolist())
        bg_prod = k_prod[k_prod["slot_id"].isin(bg_ids)]
        if bg_prod.empty:
            continue

        key_total_sales = float(bg_tot["slot_sales"].sum())
        key_total_receipts = float(bg_tot["slot_receipts"].sum())
        if key_total_sales <= 0 or key_total_receipts <= 0:
            continue

        key_prod = bg_prod.groupby("product_code_norm", as_index=False).agg(
            key_sales=("prod_sales", "sum"),
            key_qty=("prod_qty", "sum"),
            key_receipts=("prod_receipts", "sum"),
        )
        w = float(count)
        total_key_weight += w
        matched_key_count += 1

        for _, r in key_prod.iterrows():
            code = str(r["product_code_norm"])
            base_share_sum[code] += w * (float(r["key_sales"]) / key_total_sales)
            base_attach_sum[code] += w * (float(r["key_receipts"]) / key_total_receipts)
            base_qtypr_sum[code] += w * (float(r["key_qty"]) / key_total_receipts)

    if total_key_weight <= 0:
        raise ValueError("No baseline keys found for comparison.")

    out = on_prod.copy()
    out["社員CD"] = str(emp_cd)
    out["勤務時売上"] = out["on_sales"]
    out["勤務時数量"] = out["on_qty"]
    out["勤務時該当会計数"] = out["on_receipts_with_product"]
    out["勤務時売上構成比(%)"] = np.where(on_total_sales > 0, out["on_sales"] / on_total_sales * 100.0, np.nan)
    out["勤務時購入率(%)"] = np.where(
        on_total_receipts > 0, out["on_receipts_with_product"] / on_total_receipts * 100.0, np.nan
    )
    out["勤務時会計あたり数量"] = np.where(on_total_receipts > 0, out["on_qty"] / on_total_receipts, np.nan)

    out["基準売上構成比(%)"] = out["product_code_norm"].map(lambda c: base_share_sum.get(str(c), 0.0) / total_key_weight * 100.0)
    out["基準購入率(%)"] = out["product_code_norm"].map(lambda c: base_attach_sum.get(str(c), 0.0) / total_key_weight * 100.0)
    out["基準会計あたり数量"] = out["product_code_norm"].map(lambda c: base_qtypr_sum.get(str(c), 0.0) / total_key_weight)
    out["基準想定売上"] = out["基準売上構成比(%)"] / 100.0 * on_total_sales

    out["売上差分(円)"] = out["勤務時売上"] - out["基準想定売上"]
    out["構成比差(pt)"] = out["勤務時売上構成比(%)"] - out["基準売上構成比(%)"]
    out["購入率差(pt)"] = out["勤務時購入率(%)"] - out["基準購入率(%)"]
    out["会計あたり数量差"] = out["勤務時会計あたり数量"] - out["基準会計あたり数量"]

    out["比較に使えた条件数"] = matched_key_count
    out["対象会計数(全体)"] = on_total_receipts
    out["対象売上(全体)"] = on_total_sales
    out["対象数量(全体)"] = on_total_qty

    detail = out[
        [
            "社員CD",
            "product_code_norm",
            "product_name_best",
            "勤務時売上",
            "基準想定売上",
            "売上差分(円)",
            "勤務時売上構成比(%)",
            "基準売上構成比(%)",
            "構成比差(pt)",
            "勤務時購入率(%)",
            "基準購入率(%)",
            "購入率差(pt)",
            "勤務時会計あたり数量",
            "基準会計あたり数量",
            "会計あたり数量差",
            "勤務時該当会計数",
            "対象会計数(全体)",
            "比較に使えた条件数",
        ]
    ].rename(
        columns={
            "product_code_norm": "商品コード",
            "product_name_best": "商品名",
        }
    )
    detail = detail.sort_values("売上差分(円)", ascending=False).reset_index(drop=True)

    summary = pd.DataFrame(
        [
            {
                "社員CD": str(emp_cd),
                "出勤した時間帯数": int(on_slots["slot_id"].nunique()),
                "対象会計数": float(on_total_receipts),
                "対象売上(円)": float(on_total_sales),
                "比較に使えた条件数": int(matched_key_count),
                "分析商品数": int(detail.shape[0]),
            }
        ]
    )

    top_pos = detail[detail["勤務時該当会計数"] >= 5].head(20).copy()
    top_neg = (
        detail[detail["勤務時該当会計数"] >= 5]
        .sort_values("売上差分(円)", ascending=True)
        .head(20)
        .reset_index(drop=True)
    )

    return summary, detail, top_pos, top_neg


def write_markdown(summary: pd.DataFrame, top_pos: pd.DataFrame, top_neg: pd.DataFrame, out_path: Path) -> None:
    s = summary.iloc[0]
    lines = []
    lines.append(f"# 商品ベース実績フィードバック（社員CD {s['社員CD']}）")
    lines.append("")
    lines.append("## 1. 分析対象")
    lines.append(
        f"- 出勤した時間帯数: {int(s['出勤した時間帯数'])}コマ / 対象会計数: {int(s['対象会計数'])} / 対象売上: {float(s['対象売上(円)']):,.0f}円"
    )
    lines.append(
        f"- 比較に使えた条件数: {int(s['比較に使えた条件数'])} / 分析商品数: {int(s['分析商品数'])}"
    )
    lines.append("")
    lines.append("## 2. 強み商品TOP10（売上差分がプラス）")
    for _, r in top_pos.head(10).iterrows():
        lines.append(
            f"- {r['商品名']} ({r['商品コード']}): 売上差分 {float(r['売上差分(円)']):+,.0f}円 / 構成比差 {float(r['構成比差(pt)']):+.2f}pt / 購入率差 {float(r['購入率差(pt)']):+.2f}pt"
        )
    lines.append("")
    lines.append("## 3. 改善商品TOP10（売上差分がマイナス）")
    for _, r in top_neg.head(10).iterrows():
        lines.append(
            f"- {r['商品名']} ({r['商品コード']}): 売上差分 {float(r['売上差分(円)']):+,.0f}円 / 構成比差 {float(r['構成比差(pt)']):+.2f}pt / 購入率差 {float(r['購入率差(pt)']):+.2f}pt"
        )
    lines.append("")
    lines.append("※ セット率関連は袋代コードを除外して計算。")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    emp_cd = str(args.emp_cd)
    pos_path = detect_pos_file(args.pos, args.year)
    mem = load_attendance_members(Path(args.attendance), args.year, args.month, args.presence_mode)
    slot_tot, slot_prod = load_pos_month_product_data(pos_path, args.year, args.month, args.exclude_bag)
    if slot_tot.empty or slot_prod.empty:
        raise ValueError("No POS rows were loaded for target month.")

    summary, detail, top_pos, top_neg = build_product_feedback(emp_cd, mem, slot_tot, slot_prod)

    prefix = args.output_prefix.strip()
    if not prefix:
        prefix = f"product_feedback_{emp_cd}_{args.year:04d}-{args.month:02d}"

    summary_path = Path(f"{prefix}_summary.csv")
    detail_path = Path(f"{prefix}_detail.csv")
    pos_path_out = Path(f"{prefix}_top_positive20.csv")
    neg_path_out = Path(f"{prefix}_top_negative20.csv")
    md_path = Path(f"{prefix}_report.md")

    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
    top_pos.to_csv(pos_path_out, index=False, encoding="utf-8-sig")
    top_neg.to_csv(neg_path_out, index=False, encoding="utf-8-sig")
    write_markdown(summary, top_pos, top_neg, md_path)

    print(f"saved: {summary_path}")
    print(f"saved: {detail_path}")
    print(f"saved: {pos_path_out}")
    print(f"saved: {neg_path_out}")
    print(f"saved: {md_path}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
