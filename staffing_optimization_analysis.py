import argparse
import datetime as dt
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class LinearModel:
    feature_names: List[str]
    beta: np.ndarray
    yhat: np.ndarray
    r2: float

    def coef(self, name: str, default: float = 0.0) -> float:
        if name not in self.feature_names:
            return default
        return float(self.beta[self.feature_names.index(name)])


def month_range_ymd(year: int, month: int) -> Tuple[int, int]:
    start = dt.date(year, month, 1)
    if month == 12:
        end = dt.date(year + 1, 1, 1) - dt.timedelta(days=1)
    else:
        end = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    return int(start.strftime("%Y%m%d")), int(end.strftime("%Y%m%d"))


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
    return p_abs


def detect_pos_path(base_dir: Path, pos_arg: str, year: int) -> Path:
    if pos_arg:
        p = resolve_input_path(base_dir, pos_arg)
        if p.exists():
            return p
        raise FileNotFoundError(f"POS file not found: {p}")
    cands = sorted(
        [p for p in base_dir.glob(f"*{year}*.csv") if p.stat().st_size > 100_000_000],
        key=lambda x: x.stat().st_size,
        reverse=True,
    )
    if not cands:
        raise FileNotFoundError("No large POS csv found for target year.")
    return cands[0]


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
    raise RuntimeError("read_csv fallback failed")


def parse_break_weight(status: str) -> float:
    if "休憩" not in status:
        return 0.0
    m = re.search(r"(\d+)", status)
    if not m:
        return 1.0
    mins = int(m.group(1))
    return 0.5 if mins == 30 else 1.0


def parse_member_assignments(att: pd.DataFrame, presence_mode: str) -> pd.DataFrame:
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
            power_raw = parts[2].strip() if len(parts) >= 3 else ""
            if not re.fullmatch(r"\d+", emp_cd):
                continue
            try:
                sales_power = float(power_raw) if power_raw else np.nan
            except Exception:  # noqa: BLE001
                sales_power = np.nan

            if presence_mode == "store_stay":
                weight = 1.0
            else:
                if "休憩" in status:
                    bw = parse_break_weight(status)
                    weight = 0.5 if abs(bw - 0.5) < 1e-9 else 0.0
                else:
                    weight = 1.0

            rows.append(
                {
                    "slot_id": r.slot_id,
                    "date": r.date,
                    "store_cd_norm": r.store_cd_norm,
                    "hour": r.hour,
                    "emp_cd": emp_cd,
                    "name": name,
                    "status": status,
                    "weight": float(weight),
                    "sales_power": sales_power,
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = (
        out.groupby(
            ["slot_id", "date", "store_cd_norm", "hour", "emp_cd", "name"], as_index=False
        ).agg(weight=("weight", "max"), sales_power=("sales_power", "mean"))
    )
    return out


def load_attendance(
    att_path: Path, year: Optional[int], month: Optional[int]
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    att = pd.read_csv(att_path, encoding="utf-8-sig", dtype={"store_cd_full": "string"})
    att["date_dt"] = pd.to_datetime(att["date"], errors="coerce")
    if year is not None:
        att = att[att["date_dt"].dt.year == year].copy()
    if month is not None:
        att = att[att["date_dt"].dt.month == month].copy()
    att = att[att["error_type"].fillna("") == ""].copy()
    att["date"] = att["date_dt"].dt.strftime("%Y-%m-%d")
    att["store_cd_norm"] = (
        att["store_cd_full"].astype(str).str.replace(".0", "", regex=False).str.strip()
    )
    att["hour"] = pd.to_datetime(
        att["time_slot"].astype(str).str.split("-").str[0], format="%H:%M", errors="coerce"
    ).dt.hour
    att["staff_count"] = pd.to_numeric(att["staff_count"], errors="coerce")
    att["avg_sales_power"] = pd.to_numeric(att["avg_sales"], errors="coerce")
    att = att.dropna(subset=["date", "store_cd_norm", "hour"])
    att["hour"] = att["hour"].astype(int)
    att["slot_id"] = (
        att["store_cd_norm"]
        + "|"
        + att["date"]
        + " "
        + att["hour"].astype(str).str.zfill(2)
    )

    member_cols = [c for c in att.columns if c.startswith("member_")]
    break_equiv: List[float] = []
    break_people: List[int] = []
    for r in att.itertuples(index=False):
        eq = 0.0
        ppl = 0
        for c in member_cols:
            txt = getattr(r, c)
            if pd.isna(txt):
                continue
            s = str(txt)
            if "休憩" in s:
                ppl += 1
                status = s[s.find("(") + 1 : s.rfind(")")].split(":", 1)[0] if "(" in s and ")" in s else s
                eq += parse_break_weight(status)
        break_equiv.append(eq)
        break_people.append(ppl)
    att["break_equiv"] = break_equiv
    att["break_people"] = break_people

    slot_cols = [
        "slot_id",
        "date",
        "store_cd_norm",
        "store_abbrev",
        "store_full_name",
        "time_slot",
        "hour",
        "staff_count",
        "avg_sales_power",
        "break_equiv",
        "break_people",
        "error_type",
        "error_detail",
    ]
    return att, att[slot_cols].copy()


def load_pos_hourly(
    pos_paths: List[Path], date_min: pd.Timestamp, date_max: pd.Timestamp, chunksize: int
) -> pd.DataFrame:
    ymd_min = int(date_min.strftime("%Y%m%d"))
    ymd_max = int(date_max.strftime("%Y%m%d"))
    usecols = [0, 3, 5, 19, 37]
    names = ["receipt_no", "business_date", "store_cd", "sales_amount", "registered_at"]

    parts: List[pd.DataFrame] = []
    for pos_path in pos_paths:
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
            c["sales_amount"] = pd.to_numeric(c["sales_amount"], errors="coerce").fillna(0.0)
            g = (
                c.groupby(["store_cd_norm", "date", "hour"], as_index=False)
                .agg(
                    sales_amount=("sales_amount", "sum"),
                    customer_count=("receipt_no", "nunique"),
                )
            )
            parts.append(g)

    if not parts:
        return pd.DataFrame(columns=["store_cd_norm", "date", "hour", "sales_amount", "customer_count"])
    pos = pd.concat(parts, ignore_index=True)
    pos = (
        pos.groupby(["store_cd_norm", "date", "hour"], as_index=False)
        .agg(
            sales_amount=("sales_amount", "sum"),
            customer_count=("customer_count", "sum"),
        )
    )
    return pos


def merge_slot_data(att_slots: pd.DataFrame, pos_hourly: pd.DataFrame) -> pd.DataFrame:
    df = att_slots.merge(pos_hourly, on=["store_cd_norm", "date", "hour"], how="left")
    df["sales_amount"] = pd.to_numeric(df["sales_amount"], errors="coerce").fillna(0.0)
    df["customer_count"] = pd.to_numeric(df["customer_count"], errors="coerce").fillna(0.0)
    df["sales_per_staff"] = np.where(df["staff_count"] > 0, df["sales_amount"] / df["staff_count"], np.nan)
    df["customers_per_staff"] = np.where(df["staff_count"] > 0, df["customer_count"] / df["staff_count"], np.nan)
    df["aov"] = np.where(df["customer_count"] > 0, df["sales_amount"] / df["customer_count"], np.nan)
    df["dow"] = pd.to_datetime(df["date"], errors="coerce").dt.dayofweek
    df = df[df["store_cd_norm"].str.fullmatch(r"\d+")].copy()
    df = df[df["store_cd_norm"] != "0"].copy()
    df = df.dropna(subset=["staff_count", "avg_sales_power", "dow"])
    df["dow"] = df["dow"].astype(int)
    return df


def fit_lstsq(X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, float, np.ndarray]:
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    yhat = X @ beta
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    ss_res = float(np.sum((y - yhat) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    return beta, r2, yhat


def build_full_model(df: pd.DataFrame) -> LinearModel:
    core = pd.DataFrame(
        {
            "staff": pd.to_numeric(df["staff_count"], errors="coerce").fillna(0.0),
            "staff_sq": pd.to_numeric(df["staff_count"], errors="coerce").fillna(0.0) ** 2,
            "power": pd.to_numeric(df["avg_sales_power"], errors="coerce").fillna(0.0),
        }
    )
    core["staff_power"] = core["staff"] * core["power"]

    fe = pd.get_dummies(
        pd.DataFrame(
            {
                "store": df["store_cd_norm"].astype(str),
                "hour": df["hour"].astype(str),
                "dow": df["dow"].astype(str),
            }
        ),
        drop_first=True,
        dtype=float,
    )
    X_df = pd.concat([core, fe], axis=1)
    X = np.column_stack([np.ones(len(X_df)), X_df.to_numpy(dtype=float)])
    names = ["intercept"] + X_df.columns.tolist()
    y = pd.to_numeric(df["sales_amount"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    beta, r2, yhat = fit_lstsq(X, y)
    return LinearModel(feature_names=names, beta=beta, yhat=yhat, r2=r2)

def build_simple_store_models(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    coef_rows: List[dict] = []
    req_rows: List[dict] = []
    for store, g in df.groupby("store_cd_norm"):
        if len(g) < 20:
            continue
        X = np.column_stack(
            [
                np.ones(len(g)),
                pd.to_numeric(g["staff_count"], errors="coerce").fillna(0.0).to_numpy(),
                pd.to_numeric(g["avg_sales_power"], errors="coerce").fillna(0.0).to_numpy(),
            ]
        )
        y = pd.to_numeric(g["sales_amount"], errors="coerce").fillna(0.0).to_numpy()
        beta, r2, _ = fit_lstsq(X, y)
        c, a_staff, b_power = [float(x) for x in beta]
        coef_rows.append(
            {
                "store_cd_norm": store,
                "store_abbrev": g["store_abbrev"].iloc[0],
                "rows": len(g),
                "coef_staff_a": a_staff,
                "coef_sales_power_b": b_power,
                "intercept_c": c,
                "r2": r2,
            }
        )
        p50 = float(np.quantile(y, 0.50))
        p75 = float(np.quantile(y, 0.75))
        p90 = float(np.quantile(y, 0.90))
        power_ref = float(pd.to_numeric(g["avg_sales_power"], errors="coerce").median())
        for label, target in [("P50", p50), ("P75", p75), ("P90", p90)]:
            if a_staff > 1e-9:
                need = (target - b_power * power_ref - c) / a_staff
                need = max(0.0, need)
                need_round = math.ceil(need * 2) / 2.0
            else:
                need = np.nan
                need_round = np.nan
            req_rows.append(
                {
                    "store_cd_norm": store,
                    "store_abbrev": g["store_abbrev"].iloc[0],
                    "target_label": label,
                    "target_sales": target,
                    "power_ref": power_ref,
                    "required_staff_raw": need,
                    "required_staff_roundup_0_5": need_round,
                }
            )
    return pd.DataFrame(coef_rows), pd.DataFrame(req_rows)


def compute_marginal_effects(df: pd.DataFrame, model: LinearModel) -> pd.DataFrame:
    out = df.copy()
    b1 = model.coef("staff")
    b2 = model.coef("staff_sq")
    b3 = model.coef("power")
    b4 = model.coef("staff_power")
    s = pd.to_numeric(out["staff_count"], errors="coerce").fillna(0.0)
    p = pd.to_numeric(out["avg_sales_power"], errors="coerce").fillna(0.0)
    out["marginal_sales_plus1_staff"] = b1 + b2 * (2 * s + 1.0) + b4 * p
    out["pred_sales_change_minus1_staff"] = -b1 + b2 * (-2 * s + 1.0) - b4 * p
    out["marginal_sales_plus0_5_power"] = 0.5 * (b3 + b4 * s)
    out["pred_sales_model"] = model.yhat
    out["residual_sales"] = out["sales_amount"] - out["pred_sales_model"]
    return out


def detect_loss_slots(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    cps = pd.to_numeric(out["customers_per_staff"], errors="coerce")
    cps_pos = cps[cps > 0]
    if cps_pos.empty or not np.isfinite(np.nanmedian(cps_pos)):
        cps_med = 1.0
        cps_q60 = 0.0
    else:
        cps_med = float(np.nanmedian(cps_pos))
        cps_q60 = float(np.nanquantile(cps_pos, 0.60))
    cps_med = max(cps_med, 1e-6)
    out["demand_pressure"] = np.where(cps > 0, cps / cps_med, 1.0)
    out["potential_increase_sales"] = np.maximum(0.0, pd.to_numeric(out["marginal_sales_plus1_staff"], errors="coerce"))
    out["priority_score"] = out["potential_increase_sales"] * out["demand_pressure"]
    shortage = out[
        (out["potential_increase_sales"] > 0)
        & (pd.to_numeric(out["staff_count"], errors="coerce") > 0)
        & (pd.to_numeric(out["customers_per_staff"], errors="coerce") >= cps_q60)
    ].copy()
    shortage = shortage.sort_values("priority_score", ascending=False)
    cols = [
        "date",
        "store_abbrev",
        "store_full_name",
        "time_slot",
        "staff_count",
        "avg_sales_power",
        "sales_amount",
        "customer_count",
        "sales_per_staff",
        "marginal_sales_plus1_staff",
        "potential_increase_sales",
        "priority_score",
    ]
    return shortage[cols]


def classify_cause(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    key_target = (
        out.groupby(["store_cd_norm", "hour"], as_index=False)
        .agg(target_sales_p75=("sales_amount", lambda s: float(np.quantile(s, 0.75))))
    )
    out = out.merge(key_target, on=["store_cd_norm", "hour"], how="left")
    out["opportunity_gap"] = np.maximum(0.0, out["target_sales_p75"] - out["sales_amount"])
    staff_eff = np.maximum(0.0, pd.to_numeric(out["marginal_sales_plus1_staff"], errors="coerce"))
    skill_eff = np.maximum(0.0, pd.to_numeric(out["marginal_sales_plus0_5_power"], errors="coerce"))

    cause: List[str] = []
    action: List[str] = []
    for g, se, ke in zip(out["opportunity_gap"], staff_eff, skill_eff):
        if g <= 0:
            cause.append("NO_GAP")
            action.append("削減")
            continue
        if se >= ke * 1.2 and se > 0:
            cause.append("STAFF_SHORTAGE")
            action.append("増員")
        elif ke >= se * 1.2 and ke > 0:
            cause.append("SKILL_SHORTAGE")
            action.append("教育")
        elif se > 0 or ke > 0:
            cause.append("MIXED")
            action.append("増員" if se >= ke else "教育")
        else:
            cause.append("DEMAND_WEAK")
            action.append("削減")
    out["cause_type"] = cause
    out["action"] = action
    cols = [
        "date",
        "store_abbrev",
        "store_full_name",
        "time_slot",
        "staff_count",
        "avg_sales_power",
        "sales_amount",
        "customer_count",
        "opportunity_gap",
        "marginal_sales_plus1_staff",
        "marginal_sales_plus0_5_power",
        "cause_type",
        "action",
    ]
    return out[cols].sort_values(["opportunity_gap", "date"], ascending=[False, True])


def staff_contribution(df: pd.DataFrame, member_assign: pd.DataFrame) -> pd.DataFrame:
    if member_assign.empty:
        return pd.DataFrame()
    base = df[["slot_id", "residual_sales"]].copy()
    m = member_assign.merge(base, on="slot_id", how="left")
    m["residual_sales"] = pd.to_numeric(m["residual_sales"], errors="coerce").fillna(0.0)
    wsum = m.groupby("slot_id")["weight"].transform("sum")
    m["weight_share"] = np.where(wsum > 0, m["weight"] / wsum, 0.0)
    m["contribution_sales"] = m["residual_sales"] * m["weight_share"]
    out = (
        m.groupby(["emp_cd", "name"], as_index=False)
        .agg(
            slots=("slot_id", "nunique"),
            work_weight=("weight", "sum"),
            avg_sales_power=("sales_power", "mean"),
            contribution_sales=("contribution_sales", "sum"),
            contribution_per_slot=("contribution_sales", "mean"),
        )
        .sort_values("contribution_sales", ascending=False)
    )
    return out

def sales_ceiling_by_staff(df: pd.DataFrame) -> pd.DataFrame:
    rows: List[dict] = []
    tmp = df.copy()
    tmp = tmp[pd.to_numeric(tmp["staff_count"], errors="coerce") > 0].copy()
    tmp["staff_bucket"] = np.round(pd.to_numeric(tmp["staff_count"], errors="coerce")).astype(int)
    for n in [2, 3, 4]:
        g = tmp[tmp["staff_bucket"] == n].copy()
        if g.empty:
            rows.append(
                {
                    "staff_level": n,
                    "rows": 0,
                    "sales_p90": np.nan,
                    "sales_p95": np.nan,
                    "customer_p90": np.nan,
                    "avg_sales_per_staff": np.nan,
                }
            )
            continue
        rows.append(
            {
                "staff_level": n,
                "rows": len(g),
                "sales_p90": float(np.quantile(g["sales_amount"], 0.90)),
                "sales_p95": float(np.quantile(g["sales_amount"], 0.95)),
                "customer_p90": float(np.quantile(g["customer_count"], 0.90)),
                "avg_sales_per_staff": float(np.nanmean(g["sales_per_staff"])),
            }
        )
    return pd.DataFrame(rows)


def recommend_staff_from_customers(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, float]]:
    g = df[df["customer_count"] > 0].copy()
    if len(g) < 10:
        return pd.DataFrame(), {"alpha": np.nan, "beta": np.nan, "r2": np.nan}
    x = pd.to_numeric(g["customer_count"], errors="coerce").fillna(0.0).to_numpy()
    y = pd.to_numeric(g["staff_count"], errors="coerce").fillna(0.0).to_numpy()
    X = np.column_stack([np.ones(len(g)), x])
    beta, r2, _ = fit_lstsq(X, y)
    b0, b1 = float(beta[0]), float(beta[1])
    max_c = int(max(40, np.nanquantile(x, 0.99)))
    levels = list(range(5, max_c + 1, 5))
    rows = []
    for c in levels:
        s = max(0.0, b0 + b1 * c)
        rows.append(
            {
                "customer_count": c,
                "recommended_staff_raw": s,
                "recommended_staff_roundup_0_5": math.ceil(s * 2) / 2.0,
            }
        )
    return pd.DataFrame(rows), {"alpha": b1, "beta": b0, "r2": r2}


def break_timing_impact(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, float]]:
    g = df.copy()
    core = pd.DataFrame(
        {
            "break_equiv": pd.to_numeric(g["break_equiv"], errors="coerce").fillna(0.0),
            "staff": pd.to_numeric(g["staff_count"], errors="coerce").fillna(0.0),
            "power": pd.to_numeric(g["avg_sales_power"], errors="coerce").fillna(0.0),
        }
    )
    fe = pd.get_dummies(
        pd.DataFrame(
            {
                "store": g["store_cd_norm"].astype(str),
                "hour": g["hour"].astype(str),
                "dow": g["dow"].astype(str),
            }
        ),
        drop_first=True,
        dtype=float,
    )
    X_df = pd.concat([core, fe], axis=1)
    X = np.column_stack([np.ones(len(X_df)), X_df.to_numpy(dtype=float)])
    y = pd.to_numeric(g["sales_amount"], errors="coerce").fillna(0.0).to_numpy()
    beta, r2, _ = fit_lstsq(X, y)
    names = ["intercept"] + X_df.columns.tolist()
    break_coef = float(beta[names.index("break_equiv")]) if "break_equiv" in names else np.nan

    hr = (
        g.assign(has_break=(pd.to_numeric(g["break_equiv"], errors="coerce").fillna(0.0) > 0))
        .groupby(["hour", "has_break"], as_index=False)
        .agg(mean_sales=("sales_amount", "mean"), rows=("sales_amount", "size"))
    )
    pivot = hr.pivot(index="hour", columns="has_break", values="mean_sales").rename(
        columns={False: "mean_sales_no_break", True: "mean_sales_with_break"}
    )
    cnt = hr.pivot(index="hour", columns="has_break", values="rows").rename(
        columns={False: "rows_no_break", True: "rows_with_break"}
    )
    out = pivot.join(cnt).reset_index()
    for c in ["mean_sales_no_break", "mean_sales_with_break", "rows_no_break", "rows_with_break"]:
        if c not in out.columns:
            out[c] = np.nan
    out["diff_sales_break_minus_no_break"] = out["mean_sales_with_break"] - out["mean_sales_no_break"]
    out["break_share"] = out["rows_with_break"] / (out["rows_with_break"].fillna(0) + out["rows_no_break"].fillna(0))
    out = out.sort_values("diff_sales_break_minus_no_break")
    return out, {"adjusted_break_coef": break_coef, "r2": r2}


def aov_congestion_analysis(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, float]]:
    g = df[(df["customer_count"] > 0) & (df["staff_count"] > 0)].copy()
    if g.empty:
        return pd.DataFrame(), {"coef_congestion": np.nan, "r2": np.nan}
    g["congestion"] = g["customer_count"] / g["staff_count"]
    core = pd.DataFrame(
        {
            "congestion": pd.to_numeric(g["congestion"], errors="coerce").fillna(0.0),
            "power": pd.to_numeric(g["avg_sales_power"], errors="coerce").fillna(0.0),
        }
    )
    fe = pd.get_dummies(
        pd.DataFrame(
            {
                "store": g["store_cd_norm"].astype(str),
                "hour": g["hour"].astype(str),
            }
        ),
        drop_first=True,
        dtype=float,
    )
    X_df = pd.concat([core, fe], axis=1)
    X = np.column_stack([np.ones(len(X_df)), X_df.to_numpy(dtype=float)])
    y = pd.to_numeric(g["aov"], errors="coerce").fillna(0.0).to_numpy()
    beta, r2, _ = fit_lstsq(X, y)
    names = ["intercept"] + X_df.columns.tolist()
    coef_cong = float(beta[names.index("congestion")]) if "congestion" in names else np.nan

    try:
        g["q"] = pd.qcut(
            g["congestion"], q=4, labels=["Q1_low", "Q2", "Q3", "Q4_high"], duplicates="drop"
        )
    except ValueError:
        g["q"] = "ALL"
    summary = (
        g.groupby("q", as_index=False, observed=False)
        .agg(
            avg_congestion=("congestion", "mean"),
            avg_aov=("aov", "mean"),
            rows=("aov", "size"),
        )
        .sort_values("avg_congestion")
    )
    return summary, {"coef_congestion": coef_cong, "r2": r2}


def kmeans_numpy(X: np.ndarray, k: int, max_iter: int = 100, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = X.shape[0]
    if n < k:
        return np.zeros(n, dtype=int)
    idx = rng.choice(n, size=k, replace=False)
    centers = X[idx].copy()
    labels = np.zeros(n, dtype=int)
    for _ in range(max_iter):
        dist = ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        new_labels = dist.argmin(axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for j in range(k):
            mask = labels == j
            if mask.any():
                centers[j] = X[mask].mean(axis=0)
    return labels


def day_pattern_clustering(df: pd.DataFrame, k: int = 4) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    peak = (
        df.sort_values(["store_cd_norm", "date", "sales_amount"], ascending=[True, True, False])
        .drop_duplicates(["store_cd_norm", "date"])
        .loc[:, ["store_cd_norm", "date", "hour"]]
        .rename(columns={"hour": "peak_hour"})
    )
    daily = (
        df.groupby(["store_cd_norm", "store_abbrev", "store_full_name", "date"], as_index=False)
        .agg(
            total_sales=("sales_amount", "sum"),
            total_customers=("customer_count", "sum"),
            avg_staff=("staff_count", "mean"),
            avg_sales_power=("avg_sales_power", "mean"),
            break_equiv_total=("break_equiv", "sum"),
        )
        .merge(peak, on=["store_cd_norm", "date"], how="left")
    )
    daily["dow"] = pd.to_datetime(daily["date"], errors="coerce").dt.dayofweek.fillna(0).astype(int)
    daily["is_weekend"] = (daily["dow"] >= 5).astype(int)

    feats = ["total_sales", "total_customers", "avg_staff", "avg_sales_power", "peak_hour", "dow"]
    X = daily[feats].fillna(0.0).to_numpy(dtype=float)
    mu = np.nanmean(X, axis=0)
    sigma = np.nanstd(X, axis=0)
    sigma = np.where(sigma <= 1e-9, 1.0, sigma)
    Xn = (X - mu) / sigma

    if len(daily) < 3:
        daily["day_type"] = "TYPE_1"
    else:
        k_eff = min(max(2, k), len(daily))
        labels = kmeans_numpy(Xn, k=k_eff, seed=42)
        daily["day_type"] = [f"TYPE_{int(x) + 1}" for x in labels]
        ordered = (
            daily.groupby("day_type", as_index=False)["total_sales"]
            .mean()
            .sort_values("total_sales", ascending=False)["day_type"]
            .tolist()
        )
        remap = {old: f"TYPE_{i + 1}" for i, old in enumerate(ordered)}
        daily["day_type"] = daily["day_type"].map(remap).fillna(daily["day_type"])

    slots = df.merge(daily[["store_cd_norm", "date", "day_type"]], on=["store_cd_norm", "date"], how="left")
    template = (
        slots.groupby(["store_abbrev", "store_full_name", "day_type", "hour"], as_index=False)
        .agg(
            recommended_staff_mean=("staff_count", "mean"),
            recommended_power_mean=("avg_sales_power", "mean"),
            expected_sales_mean=("sales_amount", "mean"),
            expected_customers_mean=("customer_count", "mean"),
            rows=("sales_amount", "size"),
        )
        .sort_values(["store_abbrev", "day_type", "hour"])
    )
    template["recommended_staff_roundup_0_5"] = np.ceil(
        pd.to_numeric(template["recommended_staff_mean"], errors="coerce").fillna(0.0) * 2
    ) / 2.0
    template["time_slot"] = template["hour"].apply(lambda h: f"{int(h):02d}:00-{(int(h) + 1) % 24:02d}:00")
    return daily, template


def overstaff_detection(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out = out[pd.to_numeric(out["staff_count"], errors="coerce") >= 1.5].copy()
    if out.empty:
        return pd.DataFrame()
    out["reduce_impact_1staff"] = np.maximum(0.0, -pd.to_numeric(out["pred_sales_change_minus1_staff"], errors="coerce"))
    out["sales_per_staff"] = pd.to_numeric(out["sales_per_staff"], errors="coerce")
    out["customers_per_staff"] = pd.to_numeric(out["customers_per_staff"], errors="coerce")

    def q35(s: pd.Series) -> float:
        z = pd.to_numeric(s, errors="coerce").dropna()
        if z.empty:
            return np.nan
        return float(np.nanquantile(z, 0.35))

    thr_sps = out.groupby(["store_cd_norm", "hour"])["sales_per_staff"].transform(q35)
    thr_cps = out.groupby(["store_cd_norm", "hour"])["customers_per_staff"].transform(q35)
    reduce_impact_q40 = float(np.nanquantile(out["reduce_impact_1staff"], 0.40))
    cand = out[
        (out["sales_per_staff"] <= thr_sps.fillna(np.inf))
        & (out["customers_per_staff"] <= thr_cps.fillna(np.inf))
        & (out["reduce_impact_1staff"] <= reduce_impact_q40)
    ].copy()
    cand["suggested_staff_change"] = -0.5
    cand["expected_sales_impact"] = -0.5 * cand["reduce_impact_1staff"]
    cand["priority_score"] = (
        np.maximum(0.0, thr_sps.fillna(0.0) - pd.to_numeric(cand["sales_per_staff"], errors="coerce").fillna(0.0))
        + np.maximum(0.0, reduce_impact_q40 - cand["reduce_impact_1staff"])
    )
    cols = [
        "date",
        "store_abbrev",
        "store_full_name",
        "time_slot",
        "staff_count",
        "avg_sales_power",
        "sales_amount",
        "customer_count",
        "sales_per_staff",
        "customers_per_staff",
        "reduce_impact_1staff",
        "suggested_staff_change",
        "expected_sales_impact",
        "priority_score",
    ]
    return cand[cols].sort_values(["priority_score", "date"], ascending=[False, True])


def build_action_table(
    loss_slots: pd.DataFrame, cause_df: pd.DataFrame, overstaff_df: pd.DataFrame
) -> pd.DataFrame:
    parts: List[pd.DataFrame] = []
    if not loss_slots.empty:
        inc = loss_slots.copy()
        inc["action"] = "増員"
        inc["reason"] = "需要過多で取りこぼしリスクが高い時間帯"
        inc["suggested_staff_change"] = 1.0
        inc["expected_sales_impact"] = pd.to_numeric(inc["potential_increase_sales"], errors="coerce").fillna(0.0)
        inc["priority"] = pd.to_numeric(inc["priority_score"], errors="coerce").fillna(0.0)
        parts.append(
            inc[
                [
                    "date",
                    "store_abbrev",
                    "store_full_name",
                    "time_slot",
                    "action",
                    "reason",
                    "staff_count",
                    "avg_sales_power",
                    "suggested_staff_change",
                    "expected_sales_impact",
                    "priority",
                ]
            ]
        )

    if not cause_df.empty:
        edu = cause_df[
            cause_df["cause_type"].isin(["SKILL_SHORTAGE", "MIXED"])
            & (pd.to_numeric(cause_df["opportunity_gap"], errors="coerce") > 0)
        ].copy()
        if not edu.empty:
            edu["action"] = "教育"
            edu["reason"] = np.where(
                edu["cause_type"] == "SKILL_SHORTAGE",
                "人数より販売力の寄与が大きい",
                "人数と販売力の複合課題",
            )
            edu["suggested_staff_change"] = 0.0
            edu["expected_sales_impact"] = np.maximum(
                0.0, pd.to_numeric(edu["marginal_sales_plus0_5_power"], errors="coerce")
            )
            edu["priority"] = np.maximum(0.0, pd.to_numeric(edu["opportunity_gap"], errors="coerce")) + np.maximum(
                0.0, pd.to_numeric(edu["marginal_sales_plus0_5_power"], errors="coerce")
            )
            parts.append(
                edu[
                    [
                        "date",
                        "store_abbrev",
                        "store_full_name",
                        "time_slot",
                        "action",
                        "reason",
                        "staff_count",
                        "avg_sales_power",
                        "suggested_staff_change",
                        "expected_sales_impact",
                        "priority",
                    ]
                ]
            )

    if not overstaff_df.empty:
        dec = overstaff_df.copy()
        dec["action"] = "削減"
        dec["reason"] = "人時売上が低く、減員影響が小さい"
        dec["priority"] = pd.to_numeric(dec["priority_score"], errors="coerce").fillna(0.0)
        parts.append(
            dec[
                [
                    "date",
                    "store_abbrev",
                    "store_full_name",
                    "time_slot",
                    "action",
                    "reason",
                    "staff_count",
                    "avg_sales_power",
                    "suggested_staff_change",
                    "expected_sales_impact",
                    "priority",
                ]
            ]
        )

    if not parts:
        return pd.DataFrame(
            columns=[
                "date",
                "store_abbrev",
                "store_full_name",
                "time_slot",
                "action",
                "reason",
                "staff_count",
                "avg_sales_power",
                "suggested_staff_change",
                "expected_sales_impact",
                "priority",
            ]
        )
    out = pd.concat(parts, ignore_index=True)
    out = out.sort_values(["priority", "date"], ascending=[False, True])
    return out


def write_summary_md(
    out_path: Path,
    merged: pd.DataFrame,
    model: LinearModel,
    loss_slots: pd.DataFrame,
    cause_df: pd.DataFrame,
    action_df: pd.DataFrame,
    break_meta: Dict[str, float],
    aov_meta: Dict[str, float],
) -> None:
    lines: List[str] = []
    lines.append("# 人員最適化 分析サマリー")
    lines.append("")
    lines.append("## 全体指標")
    lines.append(f"- 分析スロット数: {len(merged):,}")
    lines.append(f"- 対象店舗数: {merged['store_cd_norm'].nunique():,}")
    lines.append(f"- 売上モデルR2: {model.r2:.3f}")
    lines.append(f"- 休憩影響係数(調整後): {break_meta.get('adjusted_break_coef', np.nan):.2f}")
    lines.append(f"- 混雑→客単価係数: {aov_meta.get('coef_congestion', np.nan):.2f}")
    lines.append("")
    lines.append("## 判定件数")
    lines.append(f"- 増員候補件数: {len(loss_slots):,}")
    lines.append(
        f"- 教育候補件数: {int((cause_df['cause_type'] == 'SKILL_SHORTAGE').sum()) if not cause_df.empty else 0:,}"
    )
    lines.append(f"- 全アクション件数: {len(action_df):,}")
    lines.append("")
    lines.append("## 優先アクション上位10")
    if action_df.empty:
        lines.append("- なし")
    else:
        top = action_df.head(10)
        for r in top.itertuples(index=False):
            lines.append(
                f"- {r.date} {r.store_abbrev} {r.time_slot} [{r.action}] "
                f"効果見込み={float(r.expected_sales_impact):.1f} 優先度={float(r.priority):.1f}"
            )
    out_path.write_text("\n".join(lines), encoding="utf-8-sig")


def main() -> None:
    parser = argparse.ArgumentParser(description="Shift + POS staffing optimization analysis")
    parser.add_argument("--attendance", default="attendance_summary.csv")
    parser.add_argument("--pos-files", nargs="*", default=[])
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--month", type=int, default=None)
    parser.add_argument("--presence-mode", choices=["effective", "store_stay"], default="effective")
    parser.add_argument("--chunksize", type=int, default=300_000)
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    att_path = resolve_input_path(base_dir, args.attendance)
    if not att_path.exists():
        raise FileNotFoundError(f"attendance file not found: {att_path}")

    if args.pos_files:
        pos_paths = [resolve_input_path(base_dir, p) for p in args.pos_files]
    else:
        pos_paths = sorted(base_dir.glob("*販売伝票明細*.csv"))
        if args.year is not None:
            pos_paths = [p for p in pos_paths if str(args.year) in p.stem]
    pos_paths = [p for p in pos_paths if p.exists()]
    if not pos_paths:
        raise FileNotFoundError("No POS csv found. Use --pos-files to specify input files.")

    out_dir = resolve_input_path(base_dir, args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    att_clean, att_slots = load_attendance(att_path, args.year, args.month)
    if att_slots.empty:
        raise ValueError("No attendance rows after year/month/error filter.")
    date_min = pd.to_datetime(att_slots["date"], errors="coerce").min()
    date_max = pd.to_datetime(att_slots["date"], errors="coerce").max()
    if pd.isna(date_min) or pd.isna(date_max):
        raise ValueError("attendance date range could not be determined.")

    pos_hourly = load_pos_hourly(pos_paths, date_min=date_min, date_max=date_max, chunksize=args.chunksize)
    merged = merge_slot_data(att_slots, pos_hourly)
    if merged.empty:
        raise ValueError("No merged rows. Check store codes/date range/time keys.")

    model = build_full_model(merged)
    merged = compute_marginal_effects(merged, model)

    loss_slots = detect_loss_slots(merged)
    cause_df = classify_cause(merged)
    member_assign = parse_member_assignments(att_clean, args.presence_mode)
    contribution_df = staff_contribution(merged, member_assign)
    ceiling_df = sales_ceiling_by_staff(merged)
    customer_staff_df, customer_staff_meta = recommend_staff_from_customers(merged)
    break_df, break_meta = break_timing_impact(merged)
    aov_df, aov_meta = aov_congestion_analysis(merged)
    day_type_df, template_df = day_pattern_clustering(merged, k=4)
    overstaff_df = overstaff_detection(merged)
    action_df = build_action_table(loss_slots, cause_df, overstaff_df)
    store_coef_df, target_staff_df = build_simple_store_models(merged)

    model_coef_df = pd.DataFrame({"feature": model.feature_names, "coefficient": model.beta})
    model_coef_df["model_r2"] = np.nan
    model_coef_df.loc[0, "model_r2"] = model.r2

    meta_rows = [
        {"metric": "model_r2", "value": model.r2},
        {"metric": "merged_rows", "value": float(len(merged))},
        {"metric": "merged_stores", "value": float(merged["store_cd_norm"].nunique())},
        {"metric": "customer_staff_alpha", "value": customer_staff_meta.get("alpha", np.nan)},
        {"metric": "customer_staff_beta", "value": customer_staff_meta.get("beta", np.nan)},
        {"metric": "customer_staff_r2", "value": customer_staff_meta.get("r2", np.nan)},
        {"metric": "break_coef", "value": break_meta.get("adjusted_break_coef", np.nan)},
        {"metric": "break_model_r2", "value": break_meta.get("r2", np.nan)},
        {"metric": "aov_congestion_coef", "value": aov_meta.get("coef_congestion", np.nan)},
        {"metric": "aov_model_r2", "value": aov_meta.get("r2", np.nan)},
    ]
    meta_df = pd.DataFrame(meta_rows)

    merged_out_cols = [
        "date",
        "store_abbrev",
        "store_full_name",
        "store_cd_norm",
        "time_slot",
        "hour",
        "staff_count",
        "avg_sales_power",
        "break_equiv",
        "sales_amount",
        "customer_count",
        "sales_per_staff",
        "customers_per_staff",
        "aov",
        "marginal_sales_plus1_staff",
        "pred_sales_change_minus1_staff",
        "marginal_sales_plus0_5_power",
        "pred_sales_model",
        "residual_sales",
    ]
    merged[merged_out_cols].to_csv(out_dir / "00_統合スロットデータ.csv", index=False, encoding="utf-8-sig")
    loss_slots.to_csv(out_dir / "01_売上ロス時間帯.csv", index=False, encoding="utf-8-sig")
    model_coef_df.to_csv(out_dir / "02_回帰モデル係数_全体.csv", index=False, encoding="utf-8-sig")
    store_coef_df.to_csv(out_dir / "02_回帰モデル係数_店舗別.csv", index=False, encoding="utf-8-sig")
    target_staff_df.to_csv(out_dir / "02_目標売上別必要人数.csv", index=False, encoding="utf-8-sig")
    cause_df.to_csv(out_dir / "03_人数不足_スキル不足判定.csv", index=False, encoding="utf-8-sig")
    contribution_df.to_csv(out_dir / "04_スタッフ貢献度.csv", index=False, encoding="utf-8-sig")
    ceiling_df.to_csv(out_dir / "05_人数別売上上限.csv", index=False, encoding="utf-8-sig")
    customer_staff_df.to_csv(out_dir / "06_客数別推奨人員.csv", index=False, encoding="utf-8-sig")
    break_df.to_csv(out_dir / "07_休憩タイミング影響.csv", index=False, encoding="utf-8-sig")
    aov_df.to_csv(out_dir / "08_時間帯別客単価分析.csv", index=False, encoding="utf-8-sig")
    day_type_df.to_csv(out_dir / "09_日タイプ分類.csv", index=False, encoding="utf-8-sig")
    template_df.to_csv(out_dir / "09_日タイプ別最適人員テンプレ.csv", index=False, encoding="utf-8-sig")
    overstaff_df.to_csv(out_dir / "10_過剰人員検知.csv", index=False, encoding="utf-8-sig")
    action_df.to_csv(out_dir / "運営アクション一覧.csv", index=False, encoding="utf-8-sig")
    meta_df.to_csv(out_dir / "分析メタ指標.csv", index=False, encoding="utf-8-sig")
    write_summary_md(
        out_path=out_dir / "分析サマリー.md",
        merged=merged,
        model=model,
        loss_slots=loss_slots,
        cause_df=cause_df,
        action_df=action_df,
        break_meta=break_meta,
        aov_meta=aov_meta,
    )

    print("OK:", "merged_rows=", len(merged), "merged_stores=", merged["store_cd_norm"].nunique())
    print("output_dir=", str(out_dir))


if __name__ == "__main__":
    main()
