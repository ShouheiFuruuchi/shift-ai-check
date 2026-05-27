import argparse
import math
import re
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


def z_to_percentile_score(z: pd.Series) -> pd.Series:
    return z.apply(lambda v: 100.0 * 0.5 * (1.0 + math.erf(float(v) / math.sqrt(2.0))))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate personal productivity from summed slot scores."
    )
    parser.add_argument("--year", type=int, required=True, help="Target year")
    parser.add_argument("--month", type=int, required=True, help="Target month (1-12)")
    parser.add_argument(
        "--attendance",
        default="attendance_summary.csv",
        help="Path to attendance_summary.csv",
    )
    parser.add_argument(
        "--slot-score",
        default="time_slot_aov_scoring_2025-12.csv",
        help="Path to time-slot score csv",
    )
    parser.add_argument(
        "--presence-mode",
        choices=["break_weighted", "store_stay"],
        default="break_weighted",
        help="break_weighted: 30m break=0.5, 45/60m break=0.0; store_stay: all 1.0",
    )
    parser.add_argument(
        "--evaluation-mode",
        choices=["total", "hourly", "hybrid"],
        default="total",
        help="total: sum points, hourly: points/hour, hybrid: 50/50",
    )
    parser.add_argument(
        "--weight-productivity",
        type=float,
        default=0.70,
        help="Weight for productivity score when mixing with sales power",
    )
    parser.add_argument(
        "--weight-sales-power",
        type=float,
        default=0.30,
        help="Weight for sales power score when mixing with productivity",
    )
    parser.add_argument("--min-slots", type=int, default=1, help="Minimum slot count per staff")
    parser.add_argument(
        "--output",
        default="staff_slot_score_productivity.csv",
        help="Output csv path",
    )
    parser.add_argument(
        "--top-output",
        default="staff_slot_score_productivity_top20.csv",
        help="Output top20 csv path",
    )
    return parser.parse_args()


def resolve_input_path(base_dir: Path, raw: str) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p
    p_abs = p.resolve()
    if p_abs.exists():
        return p_abs
    in_base = (base_dir / raw).resolve()
    if in_base.exists():
        return in_base
    parts = p.parts
    if parts and parts[0] == "SHIFT_AICK_REMOTE":
        project_root = base_dir.parents[1]
        from_root = (project_root / raw).resolve()
        if from_root.exists():
            return from_root
    return in_base


def parse_member_rows(att: pd.DataFrame, presence_mode: str) -> pd.DataFrame:
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
            except Exception:  # noqa: BLE001
                sales_power = np.nan

            weight = 1.0
            if presence_mode == "break_weighted":
                if "休憩" in status:
                    m = re.search(r"(\d+)", status)
                    break_min = int(m.group(1)) if m else None
                    weight = 0.5 if break_min == 30 else 0.0

            rows.append(
                {
                    "date": r.date,
                    "store_cd_norm": r.store_cd_norm,
                    "hour": int(r.hour),
                    "slot_id": r.slot_id,
                    "emp_cd": emp_cd,
                    "name": name,
                    "weight": float(weight),
                    "sales_power": sales_power,
                }
            )

    mem = pd.DataFrame(rows)
    if mem.empty:
        return mem

    # If duplicated in same slot, keep strongest weight.
    mem = (
        mem.groupby(
            ["date", "store_cd_norm", "hour", "slot_id", "emp_cd", "name"], as_index=False
        ).agg(weight=("weight", "max"), sales_power=("sales_power", "mean"))
    )
    return mem


def find_col(cols: List[str], keyword: str) -> Optional[str]:
    for c in cols:
        if keyword in c:
            return c
    return None


def load_slot_score(slot_path: Path) -> pd.DataFrame:
    slot = pd.read_csv(slot_path, encoding="utf-8-sig")
    cols = [str(c) for c in slot.columns]

    store_col = "store_cd_norm" if "store_cd_norm" in cols else find_col(cols, "store_cd")
    date_col = "date" if "date" in cols else find_col(cols, "date")
    hour_col = "hour" if "hour" in cols else find_col(cols, "hour")
    score_sum_col = find_col(cols, "点数合計")
    score_per_staff_col = find_col(cols, "1人あたり点数")
    sales_col = find_col(cols, "時間帯売上")
    customers_col = find_col(cols, "客数")

    required = [store_col, date_col, hour_col, score_sum_col]
    if any(x is None for x in required):
        raise ValueError("slot-score csv columns are not recognized")

    out = slot[
        [
            store_col,
            date_col,
            hour_col,
            score_sum_col,
            score_per_staff_col,
            sales_col,
            customers_col,
        ]
    ].copy()
    out.columns = [
        "store_cd_norm",
        "date",
        "hour",
        "slot_score_sum",
        "slot_score_per_staff",
        "slot_sales",
        "slot_customers",
    ]
    out["store_cd_norm"] = out["store_cd_norm"].astype(str).str.replace(".0", "", regex=False).str.strip()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["hour"] = pd.to_numeric(out["hour"], errors="coerce")
    out["slot_score_sum"] = pd.to_numeric(out["slot_score_sum"], errors="coerce").fillna(0.0)
    out["slot_score_per_staff"] = pd.to_numeric(
        out["slot_score_per_staff"], errors="coerce"
    ).fillna(0.0)
    out["slot_sales"] = pd.to_numeric(out["slot_sales"], errors="coerce").fillna(0.0)
    out["slot_customers"] = pd.to_numeric(out["slot_customers"], errors="coerce").fillna(0.0)
    out = out.dropna(subset=["hour"])
    out["hour"] = out["hour"].astype(int)
    return out


def main() -> None:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent

    attendance_path = resolve_input_path(base_dir, args.attendance)
    slot_path = resolve_input_path(base_dir, args.slot_score)

    att = pd.read_csv(attendance_path, encoding="utf-8-sig", dtype={"store_cd_full": "string"})
    att["date_dt"] = pd.to_datetime(att["date"], errors="coerce")
    att = att[
        (att["date_dt"].dt.year == args.year)
        & (att["date_dt"].dt.month == args.month)
        & (att["error_type"].fillna("") == "")
    ].copy()
    att["date"] = att["date_dt"].dt.strftime("%Y-%m-%d")
    att["store_cd_norm"] = (
        att["store_cd_full"].astype(str).str.replace(".0", "", regex=False).str.strip()
    )
    att["hour"] = pd.to_datetime(
        att["time_slot"].astype(str).str.split("-").str[0], format="%H:%M", errors="coerce"
    ).dt.hour
    att = att.dropna(subset=["date", "store_cd_norm", "hour"])
    att["hour"] = att["hour"].astype(int)
    att["slot_id"] = att["store_cd_norm"] + "|" + att["date"] + " " + att["hour"].astype(str).str.zfill(2)

    mem = parse_member_rows(att, args.presence_mode)
    if mem.empty:
        raise ValueError("No member rows were parsed from attendance")

    slot_score = load_slot_score(slot_path)
    merged = mem.merge(slot_score, on=["store_cd_norm", "date", "hour"], how="left")
    merged["slot_score_sum"] = pd.to_numeric(merged["slot_score_sum"], errors="coerce").fillna(0.0)
    merged["slot_score_per_staff"] = pd.to_numeric(
        merged["slot_score_per_staff"], errors="coerce"
    ).fillna(0.0)
    merged["slot_sales"] = pd.to_numeric(merged["slot_sales"], errors="coerce").fillna(0.0)
    merged["slot_customers"] = pd.to_numeric(merged["slot_customers"], errors="coerce").fillna(0.0)

    agg = (
        merged.groupby(["emp_cd", "name"], as_index=False)
        .agg(
            出勤した時間帯数=("slot_id", "nunique"),
            実質勤務時間=("weight", "sum"),
            販売力_平均=("sales_power", "mean"),
            合計点数=("slot_score_sum", lambda s: float((s * merged.loc[s.index, "weight"]).sum())),
            合計点数_人員補正=("slot_score_per_staff", lambda s: float((s * merged.loc[s.index, "weight"]).sum())),
            合計売上_担当時間帯=("slot_sales", lambda s: float((s * merged.loc[s.index, "weight"]).sum())),
            合計客数_担当時間帯=("slot_customers", lambda s: float((s * merged.loc[s.index, "weight"]).sum())),
        )
    )
    agg = agg[agg["出勤した時間帯数"] >= int(args.min_slots)].copy()
    if agg.empty:
        raise ValueError("No staff rows after min-slots filtering")

    agg["1時間あたり点数"] = np.where(
        agg["実質勤務時間"] > 0, agg["合計点数"] / agg["実質勤務時間"], np.nan
    )
    agg["1時間あたり点数_人員補正"] = np.where(
        agg["実質勤務時間"] > 0, agg["合計点数_人員補正"] / agg["実質勤務時間"], np.nan
    )

    for col in ["合計点数", "1時間あたり点数_人員補正"]:
        mu = agg[col].mean(skipna=True)
        sd = agg[col].std(skipna=True)
        if pd.notna(sd) and sd > 0:
            agg[f"z_{col}"] = (agg[col] - mu) / sd
        else:
            agg[f"z_{col}"] = 0.0

    agg["スコア_合計点数(100点)"] = z_to_percentile_score(agg["z_合計点数"].fillna(0.0))
    agg["スコア_時間効率(100点)"] = z_to_percentile_score(
        agg["z_1時間あたり点数_人員補正"].fillna(0.0)
    )

    if args.evaluation_mode == "total":
        agg["生産性評価(100点)"] = agg["スコア_合計点数(100点)"]
    elif args.evaluation_mode == "hourly":
        agg["生産性評価(100点)"] = agg["スコア_時間効率(100点)"]
    else:
        agg["生産性評価(100点)"] = (
            0.5 * agg["スコア_合計点数(100点)"] + 0.5 * agg["スコア_時間効率(100点)"]
        )

    # Sales power (5-point internal rating) is converted to 100-point scale and mixed in.
    agg["販売力スコア(100点)"] = (
        pd.to_numeric(agg["販売力_平均"], errors="coerce").clip(lower=0.0, upper=5.0) / 5.0 * 100.0
    ).fillna(0.0)
    w_prod = float(args.weight_productivity)
    w_power = float(args.weight_sales_power)
    if w_prod < 0 or w_power < 0 or (w_prod + w_power) <= 0:
        w_prod, w_power = 0.70, 0.30
    total_w = w_prod + w_power
    w_prod /= total_w
    w_power /= total_w
    agg["生産性評価_販売力加味(100点)"] = (
        w_prod * agg["生産性評価(100点)"] + w_power * agg["販売力スコア(100点)"]
    )

    out = agg.sort_values("生産性評価_販売力加味(100点)", ascending=False).reset_index(drop=True)
    out["順位"] = np.arange(1, len(out) + 1)
    ordered_cols = [
        "順位",
        "emp_cd",
        "name",
        "出勤した時間帯数",
        "実質勤務時間",
        "販売力_平均",
        "合計点数",
        "合計点数_人員補正",
        "1時間あたり点数",
        "1時間あたり点数_人員補正",
        "合計売上_担当時間帯",
        "合計客数_担当時間帯",
        "スコア_合計点数(100点)",
        "スコア_時間効率(100点)",
        "生産性評価(100点)",
        "販売力スコア(100点)",
        "生産性評価_販売力加味(100点)",
    ]
    out = out[ordered_cols]
    out = out.rename(columns={"emp_cd": "社員CD", "name": "氏名"})

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = output_path.resolve()
        if not output_path.parent.exists():
            output_path = (base_dir / args.output).resolve()
    top_path = Path(args.top_output)
    if not top_path.is_absolute():
        top_path = top_path.resolve()
        if not top_path.parent.exists():
            top_path = (base_dir / args.top_output).resolve()

    out.to_csv(output_path, index=False, encoding="utf-8-sig")
    out.head(20).to_csv(top_path, index=False, encoding="utf-8-sig")

    print(f"saved: {output_path}")
    print(f"saved: {top_path}")
    print(
        f"evaluation_mode={args.evaluation_mode}, presence_mode={args.presence_mode}, "
        f"weight_productivity={w_prod:.2f}, weight_sales_power={w_power:.2f}, "
        f"staff_count={len(out)}"
    )
    print(
        out.head(20)[
            ["順位", "社員CD", "氏名", "合計点数", "生産性評価(100点)", "販売力スコア(100点)", "生産性評価_販売力加味(100点)"]
        ]
        .round(2)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
