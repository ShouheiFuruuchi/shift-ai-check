import argparse
import calendar
from typing import Iterable, List, Optional

import numpy as np
import pandas as pd


ENCODINGS = ("cp932", "shift_jis", "utf-8-sig", "utf-8")
POS_USECOLS = ["営業日付", "店舗コード", "登録日時", "販売金額"]


def read_csv_fallback(
    path: str, usecols: Optional[List[str]] = None, chunksize: Optional[int] = None
) -> Iterable[pd.DataFrame]:
    last_err = None
    for enc in ENCODINGS:
        try:
            reader = pd.read_csv(path, encoding=enc, usecols=usecols, chunksize=chunksize)
            return reader if chunksize else [reader]
        except UnicodeDecodeError as err:
            last_err = err
            continue
    raise last_err  # type: ignore[misc]


def pick_column(columns: List[str], candidates: List[str]) -> Optional[str]:
    lower_map = {str(c).lower(): c for c in columns}
    for candidate in candidates:
        if candidate in columns:
            return candidate
        c = lower_map.get(candidate.lower())
        if c is not None:
            return c
    return None


def normalize_store_cd(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip().copy()
    num = pd.to_numeric(s, errors="coerce")
    mask = num.notna()
    if mask.any():
        s.loc[mask] = num.loc[mask].astype(np.int64).astype(str)
    return s


def parse_business_date(series: pd.Series) -> pd.Series:
    # POS business date is often YYYYMMDD as int; parse explicitly first.
    s = series.astype(str).str.strip()
    out = pd.to_datetime(series, errors="coerce")
    ymd_mask = s.str.fullmatch(r"\d{8}")
    if ymd_mask.any():
        out.loc[ymd_mask] = pd.to_datetime(s.loc[ymd_mask], format="%Y%m%d", errors="coerce")
    return out


def load_attendance_slots(path: str, year: int, month: int) -> pd.DataFrame:
    att = next(iter(read_csv_fallback(path)))
    att["date"] = pd.to_datetime(att["date"], errors="coerce")
    att = att[
        (att["date"].dt.year == year)
        & (att["date"].dt.month == month)
        & att["time_slot"].notna()
        & att["store_cd_full"].notna()
    ].copy()
    att = att[att["time_slot"].astype(str) != "ERROR"]
    start_hhmm = att["time_slot"].astype(str).str.extract(r"^(\d{1,2}:\d{2})", expand=False)
    start_dt = pd.to_datetime(start_hhmm, format="%H:%M", errors="coerce")
    att["hour"] = start_dt.dt.hour
    att["day_of_week"] = att["date"].dt.dayofweek
    att["store_cd_norm"] = normalize_store_cd(att["store_cd_full"])
    att["date"] = att["date"].dt.strftime("%Y-%m-%d")
    cols = [
        "store_cd_full",
        "store_cd_norm",
        "store_abbrev",
        "store_full_name",
        "date",
        "time_slot",
        "hour",
        "day_of_week",
    ]
    slots = att[cols].dropna(subset=["hour"]).drop_duplicates().copy()
    slots["hour"] = slots["hour"].astype(int)
    slots["day_of_week"] = slots["day_of_week"].astype(int)
    return slots


def build_history_features(pos_files: List[str], target_month: int, chunksize: int) -> pd.DataFrame:
    partials = []
    for pos_file in pos_files:
        for chunk in read_csv_fallback(pos_file, usecols=POS_USECOLS, chunksize=chunksize):
            chunk["営業日付"] = parse_business_date(chunk["営業日付"])
            chunk["登録日時"] = pd.to_datetime(chunk["登録日時"], errors="coerce")
            chunk = chunk[chunk["営業日付"].dt.month == target_month]
            if chunk.empty:
                continue
            chunk["販売金額"] = pd.to_numeric(chunk["販売金額"], errors="coerce").fillna(0)
            chunk["store_cd_norm"] = normalize_store_cd(chunk["店舗コード"])
            chunk["day_of_week"] = chunk["営業日付"].dt.dayofweek
            chunk["hour"] = chunk["登録日時"].dt.hour
            chunk = chunk.dropna(subset=["hour", "day_of_week", "store_cd_norm"])
            if chunk.empty:
                continue
            g = (
                chunk.groupby(["store_cd_norm", "day_of_week", "hour"], as_index=False)
                .agg(hist_sales=("販売金額", "sum"))
            )
            partials.append(g)
    if not partials:
        return pd.DataFrame(columns=["store_cd_norm", "day_of_week", "hour", "hist_sales"])
    hist = pd.concat(partials, ignore_index=True)
    hist = (
        hist.groupby(["store_cd_norm", "day_of_week", "hour"], as_index=False)
        .agg(hist_sales=("hist_sales", "sum"))
    )
    return hist


def load_monthly_budget_csv(path: str, year: int, month: int) -> pd.DataFrame:
    budget = next(iter(read_csv_fallback(path)))
    columns = list(budget.columns)
    store_col = pick_column(columns, ["store_cd_full", "店舗コード", "store_cd", "store"])
    amount_col = pick_column(columns, ["monthly_budget", "予算", "月予算", "budget"])
    year_col = pick_column(columns, ["year", "対象年", "予算年"])
    month_col = pick_column(columns, ["month", "対象月", "予算月"])
    if not store_col or not amount_col:
        raise ValueError("budget csv must contain store code and budget amount columns")

    if year_col:
        budget = budget[budget[year_col].astype(str) == str(year)]
    if month_col:
        budget = budget[pd.to_numeric(budget[month_col], errors="coerce") == month]

    budget["store_cd_norm"] = normalize_store_cd(budget[store_col])
    budget["monthly_budget"] = pd.to_numeric(budget[amount_col], errors="coerce").fillna(0)
    budget = (
        budget.groupby("store_cd_norm", as_index=False)
        .agg(monthly_budget=("monthly_budget", "sum"))
    )
    return budget


def allocate_total_budget(slots: pd.DataFrame, hist: pd.DataFrame, total_budget: float) -> pd.DataFrame:
    stores = slots[["store_cd_norm"]].drop_duplicates().copy()
    store_sales = hist.groupby("store_cd_norm", as_index=False).agg(hist_sales=("hist_sales", "sum"))
    stores = stores.merge(store_sales, on="store_cd_norm", how="left")
    stores["hist_sales"] = pd.to_numeric(stores["hist_sales"], errors="coerce").fillna(0.0)
    total_hist = stores["hist_sales"].sum()
    if total_hist > 0:
        stores["share"] = stores["hist_sales"] / total_hist
    else:
        stores["share"] = 1.0 / max(1, len(stores))
    stores["monthly_budget"] = total_budget * stores["share"]
    return stores[["store_cd_norm", "monthly_budget"]]


def load_daily_budget_xlsx(path: str, year: int, month: int, sheet_name: str = "DATA") -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
    days_in_month = calendar.monthrange(year, month)[1]

    store_code_row = None
    for i in range(len(raw)):
        row = pd.to_numeric(raw.iloc[i, 7:], errors="coerce")
        valid = row.dropna()
        if valid.size >= 5 and float(valid.median()) >= 100000:
            store_code_row = i
            break
    if store_code_row is None:
        raise ValueError("could not find store code row in daily budget xlsx")

    store_cols = {}
    for col in range(7, raw.shape[1]):
        code = pd.to_numeric(raw.iat[store_code_row, col], errors="coerce")
        if pd.notna(code):
            store_cols[col] = str(int(code))
    if not store_cols:
        raise ValueError("no store code cells found in daily budget xlsx")

    records = []
    for i in range(store_code_row + 1, len(raw)):
        dt = pd.to_datetime(raw.iat[i, 1], errors="coerce")
        if pd.isna(dt):
            continue
        if dt.year != year or dt.month != month or dt.day > days_in_month:
            continue
        date_str = dt.strftime("%Y-%m-%d")
        for col, store_cd in store_cols.items():
            val = pd.to_numeric(raw.iat[i, col], errors="coerce")
            if pd.isna(val):
                continue
            records.append((store_cd, date_str, float(val)))

    daily = pd.DataFrame(records, columns=["store_cd_norm", "date", "daily_budget"])
    if daily.empty:
        raise ValueError("no daily budget rows found in xlsx for target year/month")
    daily = (
        daily.groupby(["store_cd_norm", "date"], as_index=False)
        .agg(daily_budget=("daily_budget", "sum"))
    )
    return daily


def main() -> None:
    parser = argparse.ArgumentParser(description="Create hourly budget from 2-year POS history")
    parser.add_argument("--attendance", default="attendance_summary.csv")
    parser.add_argument(
        "--pos-files",
        nargs="+",
        default=["販売伝票明細 (2024).csv", "販売伝票明細 (2025).csv"],
    )
    parser.add_argument("--target-year", type=int, required=True)
    parser.add_argument("--target-month", type=int, required=True)
    parser.add_argument("--budget-csv", default=None)
    parser.add_argument("--budget-total", type=float, default=None)
    parser.add_argument("--daily-budget-xlsx", default=None)
    parser.add_argument("--daily-budget-sheet", default="DATA")
    parser.add_argument("--output", default="時間帯予算.csv")
    parser.add_argument("--output-store-summary", default="店舗別予算配分.csv")
    parser.add_argument("--chunksize", type=int, default=300_000)
    args = parser.parse_args()

    budget_mode_count = sum(
        [
            args.budget_csv is not None,
            args.budget_total is not None,
            args.daily_budget_xlsx is not None,
        ]
    )
    if budget_mode_count != 1:
        raise ValueError("set one of --budget-csv / --budget-total / --daily-budget-xlsx")

    slots = load_attendance_slots(args.attendance, args.target_year, args.target_month)
    if slots.empty:
        raise ValueError("no attendance slots found for target year/month")

    hist = build_history_features(args.pos_files, args.target_month, args.chunksize)
    by_store_dow_hour = hist.rename(columns={"hist_sales": "score_1"})
    by_store_dow = (
        hist.groupby(["store_cd_norm", "day_of_week"], as_index=False)
        .agg(score_2=("hist_sales", "sum"))
    )
    by_store_hour = (
        hist.groupby(["store_cd_norm", "hour"], as_index=False)
        .agg(score_3=("hist_sales", "sum"))
    )
    by_dow_hour = (
        hist.groupby(["day_of_week", "hour"], as_index=False)
        .agg(score_4=("hist_sales", "sum"))
    )
    by_hour = hist.groupby(["hour"], as_index=False).agg(score_5=("hist_sales", "sum"))

    plan = slots.merge(by_store_dow_hour, on=["store_cd_norm", "day_of_week", "hour"], how="left")
    plan = plan.merge(by_store_dow, on=["store_cd_norm", "day_of_week"], how="left")
    plan = plan.merge(by_store_hour, on=["store_cd_norm", "hour"], how="left")
    plan = plan.merge(by_dow_hour, on=["day_of_week", "hour"], how="left")
    plan = plan.merge(by_hour, on=["hour"], how="left")
    for col in ["score_1", "score_2", "score_3", "score_4", "score_5"]:
        plan[col] = pd.to_numeric(plan[col], errors="coerce")

    if args.daily_budget_xlsx is not None:
        # Daily-budget mode: date budget is fixed, so prioritize hourly shape.
        plan["weight_source"] = np.select(
            [
                plan["score_1"].notna(),
                plan["score_3"].notna(),
                plan["score_4"].notna(),
                plan["score_5"].notna(),
                plan["score_2"].notna(),
            ],
            ["store_dow_hour", "store_hour", "dow_hour", "hour", "store_dow"],
            default="uniform",
        )
        plan["historical_score"] = (
            plan["score_1"]
            .fillna(plan["score_3"])
            .fillna(plan["score_4"])
            .fillna(plan["score_5"])
            .fillna(plan["score_2"])
            .fillna(1.0)
        )
        daily_budget = load_daily_budget_xlsx(
            args.daily_budget_xlsx,
            args.target_year,
            args.target_month,
            sheet_name=args.daily_budget_sheet,
        )
        plan = plan.merge(daily_budget, on=["store_cd_norm", "date"], how="left")
        plan["daily_budget"] = pd.to_numeric(plan["daily_budget"], errors="coerce").fillna(0)
        sum_by_day = plan.groupby(["store_cd_norm", "date"])["historical_score"].transform("sum")
        cnt_by_day = plan.groupby(["store_cd_norm", "date"])["historical_score"].transform("count")
        plan["slot_weight"] = np.where(
            sum_by_day > 0, plan["historical_score"] / sum_by_day, 1.0 / cnt_by_day
        )
        plan["hourly_budget"] = plan["daily_budget"] * plan["slot_weight"]
        monthly = (
            daily_budget.groupby("store_cd_norm", as_index=False)
            .agg(monthly_budget=("daily_budget", "sum"))
        )
        plan = plan.merge(monthly, on="store_cd_norm", how="left")
    else:
        # Monthly-budget mode: explicitly keep day-of-week characteristic.
        plan["weight_source"] = np.select(
            [
                plan["score_1"].notna(),
                plan["score_2"].notna(),
                plan["score_3"].notna(),
                plan["score_4"].notna(),
                plan["score_5"].notna(),
            ],
            ["store_dow_hour", "store_dow", "store_hour", "dow_hour", "hour"],
            default="uniform",
        )
        plan["historical_score"] = (
            plan["score_1"]
            .fillna(plan["score_2"])
            .fillna(plan["score_3"])
            .fillna(plan["score_4"])
            .fillna(plan["score_5"])
            .fillna(1.0)
        )
        if args.budget_csv is not None:
            budget = load_monthly_budget_csv(args.budget_csv, args.target_year, args.target_month)
        else:
            budget = allocate_total_budget(slots, hist, float(args.budget_total))
        sum_by_store = plan.groupby("store_cd_norm")["historical_score"].transform("sum")
        cnt_by_store = plan.groupby("store_cd_norm")["historical_score"].transform("count")
        plan["slot_weight"] = np.where(
            sum_by_store > 0, plan["historical_score"] / sum_by_store, 1.0 / cnt_by_store
        )
        plan = plan.merge(budget, on="store_cd_norm", how="left")
        plan["monthly_budget"] = pd.to_numeric(plan["monthly_budget"], errors="coerce").fillna(0)
        plan["hourly_budget"] = plan["monthly_budget"] * plan["slot_weight"]
        plan["daily_budget"] = plan.groupby(["store_cd_norm", "date"])["hourly_budget"].transform("sum")

    output_cols = [
        "store_cd_full",
        "store_abbrev",
        "store_full_name",
        "date",
        "time_slot",
        "hour",
        "day_of_week",
        "monthly_budget",
        "daily_budget",
        "hourly_budget",
        "slot_weight",
        "historical_score",
        "weight_source",
    ]
    plan[output_cols].sort_values(["store_cd_full", "date", "hour"]).to_csv(
        args.output, index=False, encoding="utf-8-sig"
    )

    store_summary = (
        plan.groupby(["store_cd_full", "store_abbrev", "store_full_name"], as_index=False)
        .agg(
            monthly_budget=("monthly_budget", "max"),
            allocated_budget=("hourly_budget", "sum"),
            slots=("hourly_budget", "size"),
            avg_hourly_budget=("hourly_budget", "mean"),
        )
    )
    store_summary.to_csv(args.output_store_summary, index=False, encoding="utf-8-sig")

    unallocated_total = 0.0
    if args.daily_budget_xlsx is not None:
        chk = (
            store_summary[["store_abbrev", "store_full_name", "monthly_budget", "allocated_budget"]]
            .copy()
        )
        chk["unallocated_budget"] = chk["monthly_budget"] - chk["allocated_budget"]
        unallocated_total = float(chk["unallocated_budget"].clip(lower=0).sum())

    print(
        "OK:",
        "stores=",
        plan["store_cd_norm"].nunique(),
        "slots=",
        len(plan),
        "budget_total=",
        round(float(plan["hourly_budget"].sum()), 2),
        "unallocated_total=",
        round(unallocated_total, 2),
    )


if __name__ == "__main__":
    main()
