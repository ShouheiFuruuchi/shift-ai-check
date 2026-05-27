import argparse
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from staff_tendency_analysis import (
    load_attendance_members,
    load_pos_slot_metrics,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create employee feedback report using attendance and POS slot metrics."
    )
    parser.add_argument("--emp-cd", required=True, help="Target employee code (e.g. 1778)")
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
    parser.add_argument("--store-master", default="store_master.json", help="Store master json path")
    parser.add_argument("--output-prefix", default="", help="Output prefix; default feedback_<emp>_<yyyy-mm>")
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


def load_store_name_map(store_master_path: Path) -> Dict[str, str]:
    if not store_master_path.exists():
        return {}
    try:
        raw = pd.read_json(store_master_path)
    except Exception:
        import json

        with open(store_master_path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        stores = obj.get("stores", [])
    else:
        if isinstance(raw, pd.DataFrame) and "stores" in raw.columns:
            stores = raw["stores"].iloc[0]
        else:
            stores = []
    m: Dict[str, str] = {}
    for s in stores:
        cd = str(s.get("store_cd_full", "")).replace(".0", "").strip()
        name = str(s.get("store_abbrev", "")).strip()
        if cd:
            m[cd] = name or cd
    return m


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    wsum = float(weights.sum())
    if wsum <= 0:
        return np.nan
    return float((values * weights).sum() / wsum)


def fmt_slot(hour: int) -> str:
    return f"{hour:02d}:00-{(hour + 1) % 24:02d}:00"


def build_feedback(
    emp_cd: str,
    mem: pd.DataFrame,
    slot: pd.DataFrame,
    store_name_map: Dict[str, str],
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    target = mem[mem["emp_cd"] == str(emp_cd)].copy()
    if target.empty:
        raise ValueError(f"emp_cd={emp_cd} is not found in attendance data.")

    on = target.merge(
        slot[
            [
                "store_cd_full_norm",
                "slot_start",
                "hour",
                "slot_id",
                "aov",
                "set_rate_line2",
                "set_rate_qty2",
                "units_per_receipt",
            ]
        ],
        on=["store_cd_full_norm", "slot_start", "hour", "slot_id"],
        how="inner",
    )
    if on.empty:
        raise ValueError(f"emp_cd={emp_cd} has no merged rows with POS slots.")

    on_slot_ids = set(on["slot_id"].tolist())
    key_groups = {
        k: g[["slot_id", "aov", "set_rate_line2", "set_rate_qty2", "units_per_receipt"]].copy()
        for k, g in slot.groupby(["store_cd_full_norm", "hour"])
    }

    key_rows = []
    key_counts = on.groupby(["store_cd_full_norm", "hour"]).size().reset_index(name="on_slots")
    for _, r in key_counts.iterrows():
        store_cd = str(r["store_cd_full_norm"])
        hour = int(r["hour"])
        count = int(r["on_slots"])

        on_key = on[(on["store_cd_full_norm"] == store_cd) & (on["hour"] == hour)].copy()
        on_w = on_key["weight"].fillna(0.0)
        on_aov = weighted_mean(on_key["aov"], on_w)
        on_set1 = weighted_mean(on_key["set_rate_line2"], on_w)
        on_set2 = weighted_mean(on_key["set_rate_qty2"], on_w)
        on_upr = weighted_mean(on_key["units_per_receipt"], on_w)

        kg = key_groups.get((store_cd, hour))
        base_aov = np.nan
        base_set1 = np.nan
        base_set2 = np.nan
        base_upr = np.nan
        if kg is not None and not kg.empty:
            bg = kg[~kg["slot_id"].isin(on_slot_ids)]
            if not bg.empty:
                base_aov = float(bg["aov"].mean())
                base_set1 = float(bg["set_rate_line2"].mean())
                base_set2 = float(bg["set_rate_qty2"].mean())
                base_upr = float(bg["units_per_receipt"].mean())

        aov_lift_pct = np.nan
        if pd.notna(base_aov) and base_aov != 0:
            aov_lift_pct = (on_aov / base_aov - 1.0) * 100.0

        key_rows.append(
            {
                "社員CD": str(emp_cd),
                "店舗コード": store_cd,
                "店舗名": store_name_map.get(store_cd, store_cd),
                "時間帯": fmt_slot(hour),
                "出勤回数": count,
                "勤務時客単価": on_aov,
                "基準客単価": base_aov,
                "客単価上昇率(%)": aov_lift_pct,
                "勤務時セット率(点数2点以上)": on_set1,
                "基準セット率(点数2点以上)": base_set1,
                "セット率差(点数2点以上,pt)": (on_set1 - base_set1) * 100.0
                if pd.notna(base_set1)
                else np.nan,
                "勤務時セット率(数量2点以上)": on_set2,
                "基準セット率(数量2点以上)": base_set2,
                "セット率差(数量2点以上,pt)": (on_set2 - base_set2) * 100.0
                if pd.notna(base_set2)
                else np.nan,
                "勤務時1会計あたり点数": on_upr,
                "基準1会計あたり点数": base_upr,
                "1会計あたり点数差": (on_upr - base_upr) if pd.notna(base_upr) else np.nan,
            }
        )

    detail = pd.DataFrame(key_rows).sort_values(["出勤回数", "店舗名", "時間帯"], ascending=[False, True, True])

    # Overall summary (same logic as tendency: weighted baseline by key frequency).
    on_w = on["weight"].fillna(0.0)
    on_aov = weighted_mean(on["aov"], on_w)
    on_set1 = weighted_mean(on["set_rate_line2"], on_w)
    on_set2 = weighted_mean(on["set_rate_qty2"], on_w)
    on_upr = weighted_mean(on["units_per_receipt"], on_w)
    sales_power = weighted_mean(on["sales_power"], on_w)

    base_weight_sum = 0.0
    base_aov_sum = 0.0
    base_set1_sum = 0.0
    base_set2_sum = 0.0
    base_upr_sum = 0.0
    for _, row in detail.iterrows():
        cnt = float(row["出勤回数"])
        if pd.notna(row["基準客単価"]):
            base_weight_sum += cnt
            base_aov_sum += float(row["基準客単価"]) * cnt
            base_set1_sum += float(row["基準セット率(点数2点以上)"]) * cnt
            base_set2_sum += float(row["基準セット率(数量2点以上)"]) * cnt
            base_upr_sum += float(row["基準1会計あたり点数"]) * cnt

    base_aov = base_aov_sum / base_weight_sum if base_weight_sum > 0 else np.nan
    base_set1 = base_set1_sum / base_weight_sum if base_weight_sum > 0 else np.nan
    base_set2 = base_set2_sum / base_weight_sum if base_weight_sum > 0 else np.nan
    base_upr = base_upr_sum / base_weight_sum if base_weight_sum > 0 else np.nan

    summary = pd.DataFrame(
        [
            {
                "社員CD": str(emp_cd),
                "氏名": str(on["name"].iloc[0]),
                "出勤した時間帯数": int(on["slot_id"].nunique()),
                "実質勤務時間": float(on_w.sum()),
                "販売力(5点満点)": sales_power,
                "勤務時客単価": on_aov,
                "基準客単価(同じ店・同じ時間)": base_aov,
                "客単価の上昇率(%)": (on_aov / base_aov - 1.0) * 100.0
                if pd.notna(base_aov) and base_aov != 0
                else np.nan,
                "勤務時セット率(点数2点以上)": on_set1,
                "基準セット率(点数2点以上)": base_set1,
                "セット率の差(点数2点以上,pt)": (on_set1 - base_set1) * 100.0
                if pd.notna(base_set1)
                else np.nan,
                "勤務時セット率(数量2点以上)": on_set2,
                "基準セット率(数量2点以上)": base_set2,
                "セット率の差(数量2点以上,pt)": (on_set2 - base_set2) * 100.0
                if pd.notna(base_set2)
                else np.nan,
                "勤務時1会計あたり点数": on_upr,
                "基準1会計あたり点数": base_upr,
                "1会計あたり点数の差": (on_upr - base_upr) if pd.notna(base_upr) else np.nan,
                "比較に使えた条件数": int(detail["基準客単価"].notna().sum()),
            }
        ]
    )

    daily = (
        on.assign(日付=on["slot_start"].dt.date.astype(str))
        .groupby("日付", as_index=False)
        .agg(
            出勤した時間帯数=("slot_id", "nunique"),
            平均客単価=("aov", "mean"),
            平均セット率_点数2点以上=("set_rate_line2", "mean"),
            平均セット率_数量2点以上=("set_rate_qty2", "mean"),
            平均1会計あたり点数=("units_per_receipt", "mean"),
        )
        .sort_values("日付")
    )

    return summary, detail, daily


def build_markdown_report(
    summary: pd.DataFrame, detail: pd.DataFrame, daily: pd.DataFrame, out_md: Path
) -> None:
    s = summary.iloc[0]
    strong = detail[detail["出勤回数"] >= 3].sort_values(
        ["客単価上昇率(%)", "セット率差(点数2点以上,pt)"], ascending=False
    ).head(5)
    weak = detail[detail["出勤回数"] >= 3].sort_values(
        ["客単価上昇率(%)", "セット率差(点数2点以上,pt)"], ascending=True
    ).head(5)

    lines = []
    lines.append(f"# 実績フィードバック（{s['氏名']} / 社員CD {s['社員CD']}）")
    lines.append("")
    lines.append("## 1. 月間サマリー")
    lines.append(
        f"- 出勤した時間帯数: {int(s['出勤した時間帯数'])}コマ / 実質勤務時間: {float(s['実質勤務時間']):.1f}h"
    )
    lines.append(
        f"- 販売力(5点満点): {float(s['販売力(5点満点)']):.1f}"
    )
    lines.append(
        f"- 客単価: {float(s['勤務時客単価']):,.0f}円（基準 {float(s['基準客単価(同じ店・同じ時間)']):,.0f}円 / {float(s['客単価の上昇率(%)']):+.1f}%）"
    )
    lines.append(
        f"- セット率(点数2点以上): {float(s['勤務時セット率(点数2点以上)'])*100:.1f}%（基準 {float(s['基準セット率(点数2点以上)'])*100:.1f}% / {float(s['セット率の差(点数2点以上,pt)']):+.1f}pt）"
    )
    lines.append(
        f"- セット率(数量2点以上): {float(s['勤務時セット率(数量2点以上)'])*100:.1f}%（基準 {float(s['基準セット率(数量2点以上)'])*100:.1f}% / {float(s['セット率の差(数量2点以上,pt)']):+.1f}pt）"
    )
    lines.append("")
    lines.append("## 2. 強み（店舗×時間帯）")
    for _, r in strong.iterrows():
        lines.append(
            f"- {r['店舗名']} {r['時間帯']}（{int(r['出勤回数'])}回）: 客単価 {float(r['客単価上昇率(%)']):+.1f}% / セット率差 {float(r['セット率差(点数2点以上,pt)']):+.1f}pt"
        )
    lines.append("")
    lines.append("## 3. 改善チャンス（店舗×時間帯）")
    for _, r in weak.iterrows():
        lines.append(
            f"- {r['店舗名']} {r['時間帯']}（{int(r['出勤回数'])}回）: 客単価 {float(r['客単価上昇率(%)']):+.1f}% / セット率差 {float(r['セット率差(点数2点以上,pt)']):+.1f}pt"
        )
    lines.append("")
    lines.append("## 4. 翌月アクション提案")
    lines.append("- 強み時間帯の接客トークや提案順序を標準化し、他時間帯へ横展開する。")
    lines.append("- 改善チャンス時間帯は、セット提案の初回声がけを固定化する。")
    lines.append("- 日別で客単価が下がった日に、レジ前の関連提案実施率を確認する。")
    lines.append("")
    lines.append("※ セット率は袋代コードを除外して算出。")

    out_md.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    emp_cd = str(args.emp_cd)
    pos_path = detect_pos_file(args.pos, args.year)
    mem = load_attendance_members(Path(args.attendance), args.year, args.month, args.presence_mode)
    slot = load_pos_slot_metrics(pos_path, args.year, args.month)
    store_name_map = load_store_name_map(Path(args.store_master))

    summary, detail, daily = build_feedback(emp_cd, mem, slot, store_name_map)

    prefix = args.output_prefix.strip()
    if not prefix:
        prefix = f"feedback_{emp_cd}_{args.year:04d}-{args.month:02d}"

    summary_path = Path(f"{prefix}_summary.csv")
    detail_path = Path(f"{prefix}_store_hour.csv")
    daily_path = Path(f"{prefix}_daily.csv")
    md_path = Path(f"{prefix}_report.md")

    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
    daily.to_csv(daily_path, index=False, encoding="utf-8-sig")
    build_markdown_report(summary, detail, daily, md_path)

    print(f"saved: {summary_path}")
    print(f"saved: {detail_path}")
    print(f"saved: {daily_path}")
    print(f"saved: {md_path}")
    print(summary.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
