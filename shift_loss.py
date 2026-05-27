import argparse
from typing import List, Tuple

import pandas as pd


def count_breaks(row: pd.Series, member_cols: List[str]) -> int:
    count = 0
    for col in member_cols:
        val = row.get(col)
        if isinstance(val, str) and "休憩(" in val:
            count += 1
    return count


def compute_risk_flags(
    row: pd.Series,
    member_cols: List[str],
    min_staff: float,
    min_index: float,
    min_avg_sales: float,
    max_breaks: int,
) -> List[str]:
    flags = []
    staff = row.get("staff_count")
    idx = row.get("index_sum")
    avg_sales = row.get("avg_sales")

    if pd.notna(staff) and float(staff) < min_staff:
        flags.append("STAFF_SHORTAGE")
    if pd.notna(idx) and float(idx) < min_index:
        flags.append("LOW_INDEX")
    if pd.notna(avg_sales) and float(avg_sales) < min_avg_sales:
        flags.append("LOW_AVG_SALES")

    breaks = count_breaks(row, member_cols)
    if max_breaks >= 0 and breaks > max_breaks:
        flags.append("BREAK_OVERLAP")

    return flags


def risk_score(row: pd.Series, flags: List[str]) -> float:
    # Simple weighted score; can be tuned
    score = 0.0
    if "STAFF_SHORTAGE" in flags:
        score += 2.0
    if "LOW_INDEX" in flags:
        score += 1.5
    if "LOW_AVG_SALES" in flags:
        score += 1.0
    if "BREAK_OVERLAP" in flags:
        score += 1.0
    return round(score, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Predict potential sales/staff loss time slots")
    parser.add_argument("--input", default="attendance_summary.csv", help="Input CSV")
    parser.add_argument("--output", default="shift_loss.csv", help="Output CSV")
    parser.add_argument("--min-staff", type=float, default=1.5, help="Minimum staff_count threshold")
    parser.add_argument("--min-index", type=float, default=1.5, help="Minimum index_sum threshold")
    parser.add_argument("--min-avg-sales", type=float, default=3.0, help="Minimum avg_sales threshold")
    parser.add_argument(
        "--max-breaks",
        type=int,
        default=1,
        help="Maximum number of breaks allowed per slot (-1 to disable)",
    )
    args = parser.parse_args()

    df = pd.read_csv(args.input, encoding="utf-8-sig")
    member_cols = [c for c in df.columns if c.startswith("member_")]

    records: List[Tuple] = []
    for _, row in df.iterrows():
        if row.get("time_slot") == "ERROR":
            continue
        flags = compute_risk_flags(
            row,
            member_cols,
            args.min_staff,
            args.min_index,
            args.min_avg_sales,
            args.max_breaks,
        )
        if not flags:
            continue
        score = risk_score(row, flags)
        records.append(
            (
                row.get("date"),
                row.get("store_abbrev"),
                row.get("store_full_name"),
                row.get("store_cd_full"),
                row.get("time_slot"),
                row.get("staff_count"),
                row.get("avg_sales"),
                row.get("index_sum"),
                count_breaks(row, member_cols),
                ";".join(flags),
                score,
            )
        )

    out_df = pd.DataFrame(
        records,
        columns=[
            "date",
            "store_abbrev",
            "store_full_name",
            "store_cd_full",
            "time_slot",
            "staff_count",
            "avg_sales",
            "index_sum",
            "break_count",
            "risk_flags",
            "risk_score",
        ],
    )
    out_df.to_csv(args.output, index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
