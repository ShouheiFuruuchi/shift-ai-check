from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import re
import unicodedata

import altair as alt
import pandas as pd
import streamlit as st


APP_ROOT = Path(__file__).resolve().parent
DEFAULT_POS_PATH = APP_ROOT / "docs" / "templates" / "販売伝票明細 (49).csv"
SHIFT_TIME_MASTER_PATH = APP_ROOT / "business_hours_and_shift_times.json"


CATEGORY_MAP = {
    "01": "ワンピース",
    "02": "カーデ",
    "03": "ジャケット",
    "04": "ニット",
    "05": "カットソー",
    "06": "コート",
    "07": "ブラウス",
    "08": "スカート",
    "09": "パンツ",
    "10": "トレーナー",
    "11": "インナー",
    "12": "セットアップ",
    "13": "アクセサリー",
    "15": "シューズ",
}


REQUIRED_POS_COLUMNS = [
    "伝票番号",
    "営業日付",
    "店舗コード",
    "店舗名",
    "商品コード",
    "商品名",
    "販売金額",
    "数量",
    "登録日時",
]

CHART_PRIMARY = "#0f6ef4"
CHART_SECONDARY = "#ff8a00"
CHART_TERTIARY = "#2ac7a7"
CHART_SOFT = "#d8e9ff"

DEFAULT_SHIFT_TIME_RANGES = {
    "early": ("09:30", "19:00"),
    "middle": ("11:00", "20:30"),
    "late": ("12:00", "21:30"),
}

SHIFT_SYMBOL_TO_TYPE = {
    "〇": "early",
    "○": "early",
    "◯": "early",
    "O": "early",
    "o": "early",
    "△": "middle",
    "▲": "middle",
    "✕": "late",
    "×": "late",
    "✖": "late",
    "X": "late",
    "x": "late",
}


def apply_modern_theme() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Noto+Sans+JP:wght@400;500;700&display=swap');

        :root {
          --ink: #111827;
          --ink-soft: #5f6a7f;
          --bg-0: #f1f5ff;
          --bg-1: #edf8ff;
          --surface: #ffffff;
          --surface-soft: #f8fbff;
          --line: #d7e2f1;
          --accent: #0f6ef4;
          --accent-2: #ff8a00;
          --accent-3: #2ac7a7;
          --shadow: 0 14px 38px rgba(24, 39, 75, 0.11);
        }

        html, body, [class*="css"] {
          font-family: "Space Grotesk", "Noto Sans JP", sans-serif;
          color: var(--ink);
          letter-spacing: 0.01em;
        }

        [data-testid="stAppViewContainer"] {
          background:
            radial-gradient(1300px 700px at -14% -18%, #c7ddff 0%, transparent 48%),
            radial-gradient(900px 640px at 110% -12%, #bdf2e9 0%, transparent 44%),
            linear-gradient(180deg, var(--bg-0) 0%, var(--bg-1) 100%);
        }

        [data-testid="stHeader"] {
          background: transparent;
          border-bottom: none;
        }

        section.main > div.block-container {
          max-width: 1320px;
          padding-top: 1.1rem;
          padding-bottom: 1.9rem;
        }

        [data-testid="stSidebar"] {
          background:
            linear-gradient(180deg, #0f172a 0%, #16233c 45%, #1d3357 100%);
          border-right: 1px solid rgba(255, 255, 255, 0.10);
        }

        [data-testid="stSidebar"] * {
          color: #f8fbff !important;
        }

        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
          background: linear-gradient(180deg, rgba(255,255,255,.15) 0%, rgba(255,255,255,.08) 100%) !important;
          border: 1px dashed rgba(255, 255, 255, 0.58) !important;
          border-radius: 14px !important;
          transition: all .18s ease;
        }

        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] * {
          color: #f7fbff !important;
          text-shadow: 0 1px 2px rgba(0,0,0,.2);
        }

        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"]:hover {
          border-color: rgba(255, 255, 255, 0.86) !important;
          background: linear-gradient(180deg, rgba(255,255,255,.22) 0%, rgba(255,255,255,.12) 100%) !important;
        }

        [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {
          background: linear-gradient(120deg, #4f7eff, #2f62e8) !important;
          border: 1px solid #8cb1ff !important;
          color: white !important;
          border-radius: 10px !important;
        }

        [data-testid="stSidebar"] .section-note {
          margin-top: .65rem;
          border: 1px solid rgba(255,255,255,.26);
          background: rgba(255,255,255,.14);
          border-radius: 12px;
          padding: .72rem .82rem;
          backdrop-filter: blur(5px);
        }

        [data-testid="stSidebar"] .section-note b {
          color: #f9fcff;
          font-size: .87rem;
        }

        [data-testid="stSidebar"] .section-note,
        [data-testid="stSidebar"] .section-note span,
        [data-testid="stSidebar"] .section-note div {
          color: #e6f0ff !important;
          font-size: .85rem;
          line-height: 1.45;
        }

        .hero-card {
          background:
            radial-gradient(120% 120% at 8% -16%, rgba(73, 138, 255, .18) 0%, transparent 38%),
            radial-gradient(120% 120% at 92% 118%, rgba(42, 199, 167, .16) 0%, transparent 42%),
            linear-gradient(130deg, #ffffff 0%, #f5f9ff 100%);
          border: 1px solid var(--line);
          border-radius: 20px;
          padding: 1.14rem 1.25rem;
          box-shadow: var(--shadow);
          animation: riseIn .45s ease-out;
        }

        .hero-title {
          margin: 0;
          font-size: 1.42rem;
          font-weight: 700;
          color: var(--ink);
          letter-spacing: .01em;
        }

        .hero-sub {
          margin: .34rem 0 0;
          font-size: .95rem;
          color: var(--ink-soft);
        }

        .chip-wrap {
          margin-top: .7rem;
          display: flex;
          flex-wrap: wrap;
          gap: .36rem;
        }

        .chip {
          display: inline-flex;
          align-items: center;
          font-size: .77rem;
          font-weight: 700;
          color: #1e3a8a;
          background: linear-gradient(120deg, #e6efff, #d7fff3);
          border: 1px solid #c6d6f0;
          border-radius: 999px;
          padding: .21rem .6rem;
        }

        .kpi-card {
          background: linear-gradient(180deg, var(--surface) 0%, var(--surface-soft) 100%);
          border: 1px solid var(--line);
          border-radius: 16px;
          padding: .92rem 1.02rem;
          box-shadow: var(--shadow);
          min-height: 122px;
          animation: riseIn .5s ease-out;
          position: relative;
          overflow: hidden;
        }

        .kpi-card::before {
          content: "";
          position: absolute;
          left: 0;
          top: 0;
          width: 100%;
          height: 4px;
          background: linear-gradient(90deg, var(--accent), var(--accent-3));
        }

        .kpi-label {
          margin: 0;
          color: #54607a;
          font-size: .81rem;
          font-weight: 700;
        }

        .kpi-value {
          margin: .24rem 0 .22rem;
          font-size: 1.66rem;
          font-weight: 700;
          color: #132548;
        }

        .kpi-meta {
          margin: 0;
          color: #66758f;
          font-size: .8rem;
        }

        .section-note {
          margin-top: 1rem;
          border: 1px solid var(--line);
          background: rgba(255, 255, 255, 0.88);
          border-radius: 14px;
          padding: .86rem 1rem;
          box-shadow: 0 8px 24px rgba(31, 53, 88, 0.08);
        }

        .section-note b {
          color: #18305f;
        }

        .section-note ul {
          margin: .48rem 0 .08rem 1rem;
          color: #4c5e79;
        }

        div[data-baseweb="tab-list"] {
          gap: .38rem;
          padding: .36rem;
          border-radius: 14px;
          border: 1px solid var(--line);
          background: rgba(255, 255, 255, .75);
          box-shadow: 0 6px 14px rgba(43, 63, 98, .06);
        }

        button[data-baseweb="tab"] {
          border-radius: 10px;
          border: 1px solid transparent;
          padding-top: .48rem;
          padding-bottom: .48rem;
        }

        button[data-baseweb="tab"][aria-selected="true"] {
          color: #0f4ecf !important;
          background: linear-gradient(120deg, #edf3ff, #ecfff9) !important;
          border: 1px solid #c8d8f2 !important;
          box-shadow: inset 0 1px 0 rgba(255,255,255,.8);
        }

        .stButton > button {
          border-radius: 12px;
          border: 1px solid #5f8eff;
          background: linear-gradient(120deg, #3d7dff, #0f6ef4);
          color: #ffffff;
          font-weight: 700;
          box-shadow: 0 8px 20px rgba(22, 88, 211, .25);
        }

        .stButton > button:hover {
          filter: brightness(1.05);
          border-color: #8ab2ff;
        }

        div[data-testid="stDataFrame"] {
          border: 1px solid var(--line);
          border-radius: 12px;
          overflow: hidden;
          box-shadow: 0 8px 18px rgba(39, 63, 100, .08);
        }

        div[data-testid="stDataFrame"] [role="columnheader"] {
          color: #1a2c4d !important;
          font-weight: 700 !important;
          font-size: 0.93rem !important;
          background: linear-gradient(180deg, #f0f5ff, #e8efff) !important;
        }

        div[data-testid="stDataFrame"] [role="gridcell"] {
          color: #2b3850 !important;
          font-size: 0.91rem !important;
        }

        div[data-testid="stMetric"] {
          border: 1px solid var(--line);
          border-radius: 14px;
          background: rgba(255,255,255,.92);
          box-shadow: 0 8px 16px rgba(39, 63, 100, .08);
        }

        @keyframes riseIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }

        @media (max-width: 960px) {
          .hero-title { font-size: 1.16rem; }
          .kpi-value { font-size: 1.34rem; }
          section.main > div.block-container { padding-top: .72rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_header(title: str, subtitle: str, chips: list[str] | None = None) -> None:
    chip_html = ""
    if chips:
        chip_html = "<div class='chip-wrap'>" + "".join(
            f"<span class='chip'>{chip}</span>" for chip in chips
        ) + "</div>"
    st.markdown(
        f"""
        <div class="hero-card">
          <p class="hero-title">{title}</p>
          <p class="hero-sub">{subtitle}</p>
          {chip_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_cards(cards: list[tuple[str, str, str]]) -> None:
    cols = st.columns(len(cards))
    for col, (label, value, meta) in zip(cols, cards):
        col.markdown(
            f"""
            <div class="kpi-card">
              <p class="kpi-label">{label}</p>
              <p class="kpi-value">{value}</p>
              <p class="kpi-meta">{meta}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )


def init_session_state() -> None:
    if "sales_df" not in st.session_state:
        st.session_state.sales_df = None
    if "budget_df" not in st.session_state:
        st.session_state.budget_df = None
    if "stores_df" not in st.session_state:
        st.session_state.stores_df = pd.DataFrame(
            columns=["store_code", "store_name", "area", "min_staff", "max_staff"]
        )
    if "skills_df" not in st.session_state:
        st.session_state.skills_df = pd.DataFrame(
            columns=["skill_code", "skill_name", "is_reg_skill"]
        )
    if "staff_df" not in st.session_state:
        st.session_state.staff_df = pd.DataFrame(
            columns=[
                "staff_id",
                "staff_name",
                "home_store",
                "sales_power",
                "hourly_wage",
                "reg_skill",
                "work_rule",
            ]
        )
    if "shift_constraints_df" not in st.session_state:
        st.session_state.shift_constraints_df = pd.DataFrame(
            columns=[
                "staff_id",
                "staff_name",
                "home_store",
                "sales_power",
                "hourly_wage",
                "reg_skill",
                "can_work",
                "can_help",
                "available_weekdays",
                "earliest_start",
                "latest_end",
                "min_shift_hours",
                "max_shift_hours",
                "day_off_dates",
                "preferred_shift",
            ]
        )
    if "last_shift_result" not in st.session_state:
        st.session_state.last_shift_result = None
    if "last_vertical_shift_table" not in st.session_state:
        st.session_state.last_vertical_shift_table = None
    if "manual_shift_context" not in st.session_state:
        st.session_state.manual_shift_context = None
    if "manual_shift_input_df" not in st.session_state:
        st.session_state.manual_shift_input_df = pd.DataFrame()
    if "manual_shift_result" not in st.session_state:
        st.session_state.manual_shift_result = None


def read_csv_with_fallback(raw_bytes: bytes) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "cp932", "shift_jis", "utf-8"):
        try:
            decoded = raw_bytes.decode(encoding)
            return pd.read_csv(StringIO(decoded), dtype=str)
        except Exception as exc:  # noqa: PERF203
            last_error = exc
    raise ValueError(f"CSVの読み込みに失敗しました: {last_error}")


def load_pos_from_path(path: Path) -> pd.DataFrame:
    raw = path.read_bytes()
    raw_df = read_csv_with_fallback(raw)
    return normalize_pos_df(raw_df)


def load_pos_from_uploaded(raw: bytes) -> pd.DataFrame:
    raw_df = read_csv_with_fallback(raw)
    return normalize_pos_df(raw_df)


def normalize_pos_df(raw_df: pd.DataFrame) -> pd.DataFrame:
    missing = [col for col in REQUIRED_POS_COLUMNS if col not in raw_df.columns]
    if missing:
        raise ValueError(f"必須列が不足しています: {', '.join(missing)}")

    df = raw_df[REQUIRED_POS_COLUMNS].copy()
    df.columns = [
        "receipt_no",
        "business_date",
        "store_code",
        "store_name",
        "product_code_raw",
        "product_name",
        "sales_amount",
        "qty",
        "sales_datetime",
    ]

    df["receipt_no"] = df["receipt_no"].astype(str).str.strip()
    df["store_code"] = df["store_code"].astype(str).str.strip()
    df["store_name"] = df["store_name"].astype(str).str.strip()
    df["product_name"] = df["product_name"].astype(str).str.strip()
    df["business_date"] = pd.to_datetime(
        df["business_date"].astype(str), format="%Y%m%d", errors="coerce"
    )
    df["sales_datetime"] = pd.to_datetime(df["sales_datetime"], errors="coerce")
    df["sales_amount"] = pd.to_numeric(df["sales_amount"], errors="coerce").fillna(0.0)
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce").fillna(0.0)

    product_code = df["product_code_raw"].astype(str).str.replace(r"\.0$", "", regex=True)
    product_code = product_code.str.replace(" ", "", regex=False)
    df["product_code_10"] = product_code.str.slice(0, 10)
    df["color_cd"] = product_code.str.slice(10, 12)
    df["size_cd"] = product_code.str.slice(12)
    df["item_category_cd"] = df["product_code_10"].str.slice(2, 4)
    df["item_category_name"] = df["item_category_cd"].map(CATEGORY_MAP).fillna("未定義")

    df["slot_start"] = df["sales_datetime"].dt.floor("30min")
    df["slot_label"] = df["slot_start"].dt.strftime("%H:%M")

    df = df[
        df["business_date"].notna()
        & df["sales_datetime"].notna()
        & df["store_code"].ne("")
        & df["product_code_10"].str.len().ge(10)
    ].copy()
    return df


def normalize_budget_df(raw_df: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "date": ["date", "日付", "営業日付"],
        "store_code": ["store_code", "店舗コード"],
        "budget_amount": ["budget_amount", "予算", "日割予算"],
    }
    selected_cols: dict[str, str] = {}
    for key, names in aliases.items():
        for name in names:
            if name in raw_df.columns:
                selected_cols[key] = name
                break
    missing = [key for key in aliases if key not in selected_cols]
    if missing:
        raise ValueError(f"予算ファイルの必須列が不足しています: {', '.join(missing)}")

    out = raw_df[
        [selected_cols["date"], selected_cols["store_code"], selected_cols["budget_amount"]]
    ].copy()
    out.columns = ["date", "store_code", "budget_amount"]
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["store_code"] = out["store_code"].astype(str).str.strip()
    out["budget_amount"] = pd.to_numeric(out["budget_amount"], errors="coerce").fillna(0.0)
    out = out[out["date"].notna() & out["store_code"].ne("")].copy()
    return out


def compute_slot_summary(sales_df: pd.DataFrame) -> pd.DataFrame:
    slot = (
        sales_df.groupby(
            ["business_date", "store_code", "store_name", "slot_start", "slot_label"],
            as_index=False,
        )
        .agg(
            slot_sales_amount=("sales_amount", "sum"),
            slot_qty=("qty", "sum"),
            slot_ticket_count=("receipt_no", "nunique"),
        )
        .sort_values(["business_date", "store_code", "slot_start"])
    )
    day_sum = slot.groupby(["business_date", "store_code"], as_index=False).agg(
        day_sales_amount=("slot_sales_amount", "sum")
    )
    slot = slot.merge(day_sum, on=["business_date", "store_code"], how="left")
    slot["slot_sales_ratio"] = (
        slot["slot_sales_amount"] / slot["day_sales_amount"].replace(0, pd.NA)
    ).fillna(0.0)
    return slot


def sales_power_to_coeff(score: float, is_reg: bool) -> float:
    if pd.isna(score):
        return 0.0
    score = float(score)
    if score >= 5.0:
        coeff = 1.5
    elif score >= 4.5:
        coeff = 1.3
    elif score >= 4.0:
        coeff = 1.0
    elif score >= 3.5:
        coeff = 0.7
    elif score >= 3.0:
        coeff = 0.5
    elif score >= 2.5:
        coeff = 0.3
    else:
        coeff = 0.0
    if is_reg and score < 4.0:
        coeff = max(coeff, 0.7)
    return coeff


def ensure_store_master_from_sales() -> None:
    sales_df = st.session_state.sales_df
    if sales_df is None or sales_df.empty:
        return
    if not st.session_state.stores_df.empty:
        return
    stores = sales_df[["store_code", "store_name"]].drop_duplicates().copy()
    stores["area"] = ""
    stores["min_staff"] = 2
    stores["max_staff"] = 8
    st.session_state.stores_df = stores[
        ["store_code", "store_name", "area", "min_staff", "max_staff"]
    ]


def to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on", "対応", "可", "ok"}


def parse_weekday_rule(raw_value: object) -> set[int]:
    if pd.isna(raw_value) or str(raw_value).strip() == "":
        return {0, 1, 2, 3, 4, 5, 6}

    text = str(raw_value).strip().lower()
    tokens: list[str] = []
    for sep in [",", "、", " ", "/", "|", ";"]:
        text = text.replace(sep, " ")
    tokens = [token for token in text.split(" ") if token]

    jp_map = {
        "月": 0,
        "火": 1,
        "水": 2,
        "木": 3,
        "金": 4,
        "土": 5,
        "日": 6,
        "mon": 0,
        "tue": 1,
        "wed": 2,
        "thu": 3,
        "fri": 4,
        "sat": 5,
        "sun": 6,
    }
    weekdays: set[int] = set()
    for token in tokens:
        if token.isdigit():
            num = int(token)
            if 0 <= num <= 6:
                weekdays.add(num)
                continue
        if token in jp_map:
            weekdays.add(jp_map[token])
            continue
        for char in token:
            if char in jp_map:
                weekdays.add(jp_map[char])
    return weekdays or {0, 1, 2, 3, 4, 5, 6}


def parse_day_off_dates(raw_value: object) -> set[pd.Timestamp]:
    if pd.isna(raw_value) or str(raw_value).strip() == "":
        return set()
    text = str(raw_value).strip()
    for sep in [",", "、", "|", ";", "\n", "\t"]:
        text = text.replace(sep, " ")
    tokens = [token for token in text.split(" ") if token]

    day_off: set[pd.Timestamp] = set()
    for token in tokens:
        parsed = pd.to_datetime(token, errors="coerce")
        if pd.notna(parsed):
            day_off.add(parsed.normalize())
    return day_off


def parse_hhmm_to_minutes(raw_value: object, default_minutes: int) -> int:
    if pd.isna(raw_value):
        return default_minutes
    text = str(raw_value).strip()
    if not text:
        return default_minutes
    parsed = pd.to_datetime(text, format="%H:%M", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return default_minutes
    return int(parsed.hour * 60 + parsed.minute)


def normalize_store_code_full(store_code: object) -> int | None:
    if pd.isna(store_code):
        return None
    text = str(store_code).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None

    if len(digits) <= 4:
        return int(f"100{int(digits):04d}")
    return int(digits)


@st.cache_data(show_spinner=False)
def load_shift_time_master(path_str: str) -> dict[int, dict[str, tuple[str, str]]]:
    path = Path(path_str)
    if not path.exists():
        return {}

    raw = path.read_bytes()
    parsed_json: dict[str, object] | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        try:
            parsed_json = json.loads(raw.decode(encoding))
            break
        except Exception:  # noqa: PERF203
            continue

    if parsed_json is None:
        return {}

    stores = parsed_json.get("entities", {}).get("stores", [])
    out: dict[int, dict[str, tuple[str, str]]] = {}
    for store in stores:
        try:
            store_cd_full = int(store.get("store_cd_full"))
        except Exception:  # noqa: PERF203
            continue

        shift_times = store.get("shift_times", {})
        shift_map: dict[str, tuple[str, str]] = {}
        for shift_type in ("early", "middle", "late"):
            shift_info = shift_times.get(shift_type, {})
            start = str(shift_info.get("start", "")).strip()
            end = str(shift_info.get("end", "")).strip()
            if start and end:
                shift_map[shift_type] = (start, end)

        if shift_map:
            out[store_cd_full] = shift_map
    return out


def resolve_shift_time_ranges_for_store(store_code: object) -> dict[str, tuple[str, str]]:
    master = load_shift_time_master(str(SHIFT_TIME_MASTER_PATH))
    full_code = normalize_store_code_full(store_code)
    if full_code is not None and full_code in master:
        shift_ranges = master[full_code]
        return {
            "early": shift_ranges.get("early", DEFAULT_SHIFT_TIME_RANGES["early"]),
            "middle": shift_ranges.get("middle", DEFAULT_SHIFT_TIME_RANGES["middle"]),
            "late": shift_ranges.get("late", DEFAULT_SHIFT_TIME_RANGES["late"]),
        }
    return DEFAULT_SHIFT_TIME_RANGES.copy()


def normalize_time_token(token: str) -> str | None:
    text = unicodedata.normalize("NFKC", str(token)).strip()
    text = text.replace("：", ":")
    if not text:
        return None

    hour: int
    minute: int
    if re.fullmatch(r"\d{1,2}", text):
        hour = int(text)
        minute = 0
    elif re.fullmatch(r"\d{3,4}", text):
        hour = int(text[:-2])
        minute = int(text[-2:])
    elif re.fullmatch(r"\d{1,2}:\d{2}", text):
        hour = int(text.split(":")[0])
        minute = int(text.split(":")[1])
    else:
        return None

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def parse_manual_shift_cell(
    raw_value: object, shift_time_ranges: dict[str, tuple[str, str]]
) -> dict[str, object]:
    raw_text = "" if pd.isna(raw_value) else str(raw_value).strip()
    if not raw_text:
        return {
            "input_text": "",
            "normalized": "",
            "shift_type": None,
            "start_time": None,
            "end_time": None,
            "error": "",
        }

    text = unicodedata.normalize("NFKC", raw_text)
    compact = re.sub(r"\s+", "", text).replace("〜", "-").replace("～", "-").replace("ー", "-")

    if compact in {"休", "休み", "公休", "有休", "/", "欠勤"}:
        return {
            "input_text": raw_text,
            "normalized": "休",
            "shift_type": None,
            "start_time": None,
            "end_time": None,
            "error": "",
        }

    symbol = compact[:1]
    if symbol in SHIFT_SYMBOL_TO_TYPE and len(compact) == 1:
        shift_type = SHIFT_SYMBOL_TO_TYPE[symbol]
        start, end = shift_time_ranges.get(shift_type, ("", ""))
        if not start or not end:
            return {
                "input_text": raw_text,
                "normalized": "",
                "shift_type": shift_type,
                "start_time": None,
                "end_time": None,
                "error": f"{shift_type}の時間帯が未定義です。",
            }
        return {
            "input_text": raw_text,
            "normalized": f"{start}-{end}",
            "shift_type": shift_type,
            "start_time": start,
            "end_time": end,
            "error": "",
        }

    if symbol in SHIFT_SYMBOL_TO_TYPE and "-" in compact:
        shift_type = SHIFT_SYMBOL_TO_TYPE[symbol]
        end_token = compact[1:].replace("-", "")
        end_time = normalize_time_token(end_token)
        shift_start = shift_time_ranges.get(shift_type, ("", ""))[0]
        if end_time and shift_start:
            return {
                "input_text": raw_text,
                "normalized": f"{shift_start}-{end_time}",
                "shift_type": shift_type,
                "start_time": shift_start,
                "end_time": end_time,
                "error": "",
            }

    matched = re.fullmatch(r"(?P<start>[0-9:]{1,5})-(?P<end>[0-9:]{1,5})", compact)
    if matched:
        start_time = normalize_time_token(matched.group("start"))
        end_time = normalize_time_token(matched.group("end"))
        if start_time and end_time:
            return {
                "input_text": raw_text,
                "normalized": f"{start_time}-{end_time}",
                "shift_type": None,
                "start_time": start_time,
                "end_time": end_time,
                "error": "",
            }

    return {
        "input_text": raw_text,
        "normalized": "",
        "shift_type": None,
        "start_time": None,
        "end_time": None,
        "error": "入力形式エラー（〇/△/✕ または HH:MM-HH:MM で入力）",
    }


def build_manual_shift_template(
    start_date: object,
    end_date: object,
    staff_columns: list[tuple[str, str]],
) -> pd.DataFrame:
    start_ts = pd.to_datetime(start_date).normalize()
    end_ts = pd.to_datetime(end_date).normalize()
    if end_ts < start_ts:
        start_ts, end_ts = end_ts, start_ts

    weekday_jp = ["月", "火", "水", "木", "金", "土", "日"]
    rows: list[dict[str, object]] = []
    for current_ts in pd.date_range(start_ts, end_ts, freq="D"):
        row: dict[str, object] = {
            "日付": current_ts.strftime("%Y-%m-%d"),
            "曜日": weekday_jp[current_ts.weekday()],
        }
        for _, label in staff_columns:
            row[label] = ""
        rows.append(row)
    return pd.DataFrame(rows)


def parse_manual_shift_table(
    manual_df: pd.DataFrame,
    staff_columns: list[tuple[str, str]],
    shift_time_ranges: dict[str, tuple[str, str]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = manual_df.copy()
    detail_rows: list[dict[str, object]] = []

    staff_id_by_label = {label: staff_id for staff_id, label in staff_columns}
    for row_idx, row in out.iterrows():
        date_text = str(row.get("日付", ""))
        for _, label in staff_columns:
            parsed = parse_manual_shift_cell(row.get(label, ""), shift_time_ranges)
            out.at[row_idx, label] = parsed["normalized"] if parsed["normalized"] else row.get(label, "")
            detail_rows.append(
                {
                    "date": date_text,
                    "staff_id": staff_id_by_label[label],
                    "staff_label": label,
                    "input_text": parsed["input_text"],
                    "normalized_text": parsed["normalized"],
                    "shift_type": parsed["shift_type"],
                    "start_time": parsed["start_time"],
                    "end_time": parsed["end_time"],
                    "error": parsed["error"],
                }
            )
    return out, pd.DataFrame(detail_rows)


def build_default_shift_constraints(staff_df: pd.DataFrame) -> pd.DataFrame:
    if staff_df.empty:
        return pd.DataFrame(
            columns=[
                "staff_id",
                "staff_name",
                "home_store",
                "sales_power",
                "hourly_wage",
                "reg_skill",
                "can_work",
                "can_help",
                "available_weekdays",
                "earliest_start",
                "latest_end",
                "min_shift_hours",
                "max_shift_hours",
                "day_off_dates",
                "preferred_shift",
            ]
        )

    base = staff_df.copy()
    base["staff_id"] = base["staff_id"].astype(str).str.strip()
    base["staff_name"] = base["staff_name"].astype(str).str.strip()
    base["home_store"] = base["home_store"].astype(str).str.strip()
    base["sales_power"] = pd.to_numeric(base["sales_power"], errors="coerce").fillna(3.0)
    base["hourly_wage"] = pd.to_numeric(base["hourly_wage"], errors="coerce").fillna(1200.0)
    base["reg_skill"] = base["reg_skill"].apply(to_bool)
    base["can_work"] = True
    base["can_help"] = True
    base["available_weekdays"] = "0,1,2,3,4,5,6"
    base["earliest_start"] = "09:30"
    base["latest_end"] = "21:30"
    base["min_shift_hours"] = 4.0
    base["max_shift_hours"] = 8.0
    base["day_off_dates"] = ""
    base["preferred_shift"] = "any"
    return base[
        [
            "staff_id",
            "staff_name",
            "home_store",
            "sales_power",
            "hourly_wage",
            "reg_skill",
            "can_work",
            "can_help",
            "available_weekdays",
            "earliest_start",
            "latest_end",
            "min_shift_hours",
            "max_shift_hours",
            "day_off_dates",
            "preferred_shift",
        ]
    ]


def sync_shift_constraints_with_staff() -> None:
    staff_df = st.session_state.staff_df
    defaults = build_default_shift_constraints(staff_df)
    current = st.session_state.shift_constraints_df
    if defaults.empty:
        st.session_state.shift_constraints_df = defaults
        return

    editable_cols = [
        "can_work",
        "can_help",
        "available_weekdays",
        "earliest_start",
        "latest_end",
        "min_shift_hours",
        "max_shift_hours",
        "day_off_dates",
        "preferred_shift",
    ]
    if current is None or current.empty:
        st.session_state.shift_constraints_df = defaults
        return

    existing = current.copy()
    existing["staff_id"] = existing["staff_id"].astype(str).str.strip()
    keep_cols = ["staff_id"] + editable_cols
    keep_cols = [col for col in keep_cols if col in existing.columns]
    merged = defaults.merge(
        existing[keep_cols],
        on="staff_id",
        how="left",
        suffixes=("", "_saved"),
    )
    for col in editable_cols:
        saved_col = f"{col}_saved"
        if saved_col in merged.columns:
            merged[col] = merged[saved_col].where(merged[saved_col].notna(), merged[col])
            merged = merged.drop(columns=[saved_col])
    st.session_state.shift_constraints_df = merged[defaults.columns]


def build_required_staff_plan(
    store_slots: pd.DataFrame,
    min_staff: int,
    max_staff: int,
    enforce_reg: bool,
) -> pd.DataFrame:
    demand = store_slots.copy().sort_values("slot_start").reset_index(drop=True)
    peak_ratio = demand["slot_sales_ratio"].max()
    if peak_ratio <= 0:
        demand["required_staff"] = min_staff
    else:
        scaled = demand["slot_sales_ratio"] / peak_ratio
        demand["required_staff"] = (
            min_staff + ((max_staff - min_staff) * scaled).round().astype(int)
        )
    demand["required_staff"] = demand["required_staff"].clip(lower=min_staff, upper=max_staff)
    demand["required_reg_staff"] = 1 if enforce_reg else 0
    demand["slot_sales_ratio_pct"] = (demand["slot_sales_ratio"] * 100).round(2)
    return demand


def generate_shift_plan(
    demand_df: pd.DataFrame,
    constraints_df: pd.DataFrame,
    selected_date: object,
    selected_store: str,
    include_help_staff: bool,
) -> dict[str, object]:
    result: dict[str, object] = {
        "slot_result": pd.DataFrame(),
        "assignment_result": pd.DataFrame(),
        "staff_result": pd.DataFrame(),
        "warnings": [],
    }
    warnings: list[str] = []

    if demand_df.empty:
        warnings.append("需要データが空です。")
        result["warnings"] = warnings
        return result
    if constraints_df.empty:
        warnings.append("スタッフ制約が未登録です。")
        result["warnings"] = warnings
        return result

    demand = demand_df.copy().sort_values("slot_start").reset_index(drop=True)
    target_date = pd.to_datetime(selected_date).normalize()
    slot_minutes = (demand["slot_start"].dt.hour * 60 + demand["slot_start"].dt.minute).tolist()
    default_start = int(min(slot_minutes))
    default_end = int(max(slot_minutes) + 30)

    cons = constraints_df.copy()
    cons["staff_id"] = cons["staff_id"].astype(str).str.strip()
    cons["staff_name"] = cons["staff_name"].astype(str).str.strip()
    cons["home_store"] = cons["home_store"].astype(str).str.strip()
    cons["sales_power"] = pd.to_numeric(cons["sales_power"], errors="coerce").fillna(3.0)
    cons["hourly_wage"] = pd.to_numeric(cons["hourly_wage"], errors="coerce").fillna(1200.0)
    cons["reg_skill"] = cons["reg_skill"].apply(to_bool)
    cons["can_work"] = cons["can_work"].apply(to_bool)
    cons["can_help"] = cons["can_help"].apply(to_bool)
    cons["min_shift_hours"] = (
        pd.to_numeric(cons["min_shift_hours"], errors="coerce").fillna(0.0).clip(lower=0.0)
    )
    cons["max_shift_hours"] = (
        pd.to_numeric(cons["max_shift_hours"], errors="coerce").fillna(8.0).clip(lower=0.5)
    )
    cons["preferred_shift"] = (
        cons["preferred_shift"].astype(str).str.strip().str.lower().replace({"": "any"})
    )

    if include_help_staff:
        eligible = cons[
            cons["can_work"]
            & ((cons["home_store"] == selected_store) | cons["can_help"])
        ].copy()
    else:
        eligible = cons[(cons["can_work"]) & (cons["home_store"] == selected_store)].copy()

    if eligible.empty:
        warnings.append("対象店舗で勤務可能なスタッフがいません。")
        result["warnings"] = warnings
        return result

    staff_meta: dict[str, dict[str, object]] = {}
    for row in eligible.itertuples(index=False):
        day_off_set = parse_day_off_dates(getattr(row, "day_off_dates", ""))
        if target_date in day_off_set:
            continue
        weekday_set = parse_weekday_rule(getattr(row, "available_weekdays", ""))
        if int(target_date.weekday()) not in weekday_set:
            continue

        earliest = parse_hhmm_to_minutes(getattr(row, "earliest_start", ""), default_start)
        latest = parse_hhmm_to_minutes(getattr(row, "latest_end", ""), default_end)
        if latest <= earliest:
            latest = default_end

        available_slots: set[int] = set()
        for idx, slot_ts in enumerate(demand["slot_start"]):
            start_min = int(slot_ts.hour * 60 + slot_ts.minute)
            end_min = start_min + 30
            if earliest <= start_min and end_min <= latest:
                available_slots.add(idx)
        if not available_slots:
            continue

        max_slots = max(int(round(float(getattr(row, "max_shift_hours", 8.0)) * 2)), 1)
        min_slots = max(int(round(float(getattr(row, "min_shift_hours", 0.0)) * 2)), 0)
        staff_id = getattr(row, "staff_id")
        staff_meta[staff_id] = {
            "staff_id": staff_id,
            "staff_name": getattr(row, "staff_name"),
            "home_store": getattr(row, "home_store"),
            "sales_power": float(getattr(row, "sales_power")),
            "hourly_wage": float(getattr(row, "hourly_wage")),
            "reg_skill": bool(getattr(row, "reg_skill")),
            "can_help": bool(getattr(row, "can_help")),
            "preferred_shift": str(getattr(row, "preferred_shift", "any")).lower(),
            "available_slots": available_slots,
            "max_slots": max_slots,
            "min_slots": min_slots,
        }

    if not staff_meta:
        warnings.append("休み希望や曜日条件により、勤務可能スタッフが0名でした。")
        result["warnings"] = warnings
        return result

    total_slots = len(demand)
    assigned_by_slot: dict[int, list[str]] = {idx: [] for idx in range(total_slots)}
    assigned_slots_by_staff: dict[str, set[int]] = {staff_id: set() for staff_id in staff_meta}

    def score_staff(staff_id: str, slot_idx: int, need_reg: bool) -> float:
        meta = staff_meta[staff_id]
        assigned_slots = assigned_slots_by_staff[staff_id]
        continuity_bonus = 0.0
        if (slot_idx - 1) in assigned_slots:
            continuity_bonus += 1.2
        if (slot_idx + 1) in assigned_slots:
            continuity_bonus += 0.2

        utilization_penalty = len(assigned_slots) / max(int(meta["max_slots"]), 1)
        score = float(meta["sales_power"]) + continuity_bonus - (utilization_penalty * 1.2)
        if need_reg and bool(meta["reg_skill"]):
            score += 1.5
        if str(meta["home_store"]) == selected_store:
            score += 0.45
        else:
            score -= 0.15

        pref = str(meta["preferred_shift"]).lower()
        if pref in {"early", "早番"}:
            score += 0.45 if slot_idx <= (total_slots // 2) else -0.2
        elif pref in {"late", "遅番"}:
            score += 0.45 if slot_idx >= (total_slots // 2) else -0.2
        return score

    for slot_idx, row in demand.iterrows():
        required_staff = int(pd.to_numeric(row["required_staff"], errors="coerce") or 0)
        required_reg = int(pd.to_numeric(row["required_reg_staff"], errors="coerce") or 0)
        if required_staff <= 0:
            continue

        available_staff = [
            staff_id
            for staff_id, meta in staff_meta.items()
            if slot_idx in meta["available_slots"]
            and len(assigned_slots_by_staff[staff_id]) < int(meta["max_slots"])
        ]
        if not available_staff:
            continue

        selected_slot_staff: list[str] = []
        reg_pool = [staff_id for staff_id in available_staff if bool(staff_meta[staff_id]["reg_skill"])]
        reg_sorted = sorted(
            reg_pool,
            key=lambda sid: score_staff(sid, slot_idx, need_reg=True),
            reverse=True,
        )
        for staff_id in reg_sorted:
            if required_reg <= 0 or required_staff <= 0:
                break
            selected_slot_staff.append(staff_id)
            assigned_slots_by_staff[staff_id].add(slot_idx)
            required_reg -= 1
            required_staff -= 1

        remain_pool = [staff_id for staff_id in available_staff if staff_id not in selected_slot_staff]
        remain_sorted = sorted(
            remain_pool,
            key=lambda sid: score_staff(sid, slot_idx, need_reg=False),
            reverse=True,
        )
        for staff_id in remain_sorted:
            if required_staff <= 0:
                break
            selected_slot_staff.append(staff_id)
            assigned_slots_by_staff[staff_id].add(slot_idx)
            required_staff -= 1

        assigned_by_slot[slot_idx] = selected_slot_staff

    slot_rows: list[dict[str, object]] = []
    assignment_rows: list[dict[str, object]] = []
    for slot_idx, row in demand.iterrows():
        slot_staff_ids = assigned_by_slot.get(slot_idx, [])
        reg_assigned = sum(1 for staff_id in slot_staff_ids if bool(staff_meta[staff_id]["reg_skill"]))
        required_staff = int(pd.to_numeric(row["required_staff"], errors="coerce") or 0)
        required_reg = int(pd.to_numeric(row["required_reg_staff"], errors="coerce") or 0)
        shortage = max(required_staff - len(slot_staff_ids), 0)
        reg_shortage = max(required_reg - reg_assigned, 0)

        slot_rows.append(
            {
                "slot_start": row["slot_start"],
                "slot_label": row["slot_label"],
                "slot_sales_ratio_pct": row["slot_sales_ratio_pct"],
                "slot_sales_amount": row["slot_sales_amount"],
                "required_staff": required_staff,
                "assigned_staff": len(slot_staff_ids),
                "staff_shortage": shortage,
                "required_reg_staff": required_reg,
                "assigned_reg_staff": reg_assigned,
                "reg_shortage": reg_shortage,
                "assigned_staff_names": " / ".join(
                    [str(staff_meta[staff_id]["staff_name"]) for staff_id in slot_staff_ids]
                ),
            }
        )

        for staff_id in slot_staff_ids:
            assignment_rows.append(
                {
                    "date": target_date.date(),
                    "store_code": selected_store,
                    "slot_start": row["slot_start"],
                    "slot_label": row["slot_label"],
                    "staff_id": staff_id,
                    "staff_name": staff_meta[staff_id]["staff_name"],
                    "home_store": staff_meta[staff_id]["home_store"],
                    "is_help": str(staff_meta[staff_id]["home_store"]) != selected_store,
                    "reg_skill": staff_meta[staff_id]["reg_skill"],
                    "sales_power": staff_meta[staff_id]["sales_power"],
                    "hourly_wage": staff_meta[staff_id]["hourly_wage"],
                }
            )

    slot_result = pd.DataFrame(slot_rows)
    assignment_result = pd.DataFrame(assignment_rows)

    staff_rows: list[dict[str, object]] = []
    for staff_id, meta in staff_meta.items():
        slot_idx_list = sorted(assigned_slots_by_staff[staff_id])
        if not slot_idx_list:
            continue
        assigned_hours = len(slot_idx_list) * 0.5
        coeff = sales_power_to_coeff(float(meta["sales_power"]), bool(meta["reg_skill"]))
        labor_cost = assigned_hours * float(meta["hourly_wage"])

        blocks: list[tuple[int, int]] = []
        block_start = slot_idx_list[0]
        prev_idx = slot_idx_list[0]
        for idx in slot_idx_list[1:]:
            if idx == prev_idx + 1:
                prev_idx = idx
                continue
            blocks.append((block_start, prev_idx))
            block_start = idx
            prev_idx = idx
        blocks.append((block_start, prev_idx))

        shift_ranges: list[str] = []
        for start_idx, end_idx in blocks:
            start_ts = demand.loc[start_idx, "slot_start"]
            end_ts = demand.loc[end_idx, "slot_start"] + pd.Timedelta(minutes=30)
            shift_ranges.append(f"{start_ts.strftime('%H:%M')}-{end_ts.strftime('%H:%M')}")

        alerts: list[str] = []
        if len(slot_idx_list) < int(meta["min_slots"]):
            alerts.append("最低勤務時間未満")
        if len(slot_idx_list) > int(meta["max_slots"]):
            alerts.append("最大勤務時間超過")

        staff_rows.append(
            {
                "staff_id": staff_id,
                "staff_name": meta["staff_name"],
                "home_store": meta["home_store"],
                "is_help": str(meta["home_store"]) != selected_store,
                "assigned_slots": len(slot_idx_list),
                "assigned_hours": assigned_hours,
                "shift_blocks": len(blocks),
                "shift_ranges": " / ".join(shift_ranges),
                "avg_sales_power": float(meta["sales_power"]),
                "productivity_coeff": coeff,
                "estimated_labor_cost": labor_cost,
                "alerts": " / ".join(alerts),
            }
        )

    staff_result = pd.DataFrame(staff_rows)
    if not staff_result.empty:
        staff_result = staff_result.sort_values(
            ["is_help", "assigned_hours", "staff_id"], ascending=[True, False, True]
        )

    if not slot_result.empty:
        first_slot = slot_result.iloc[0]
        last_slot = slot_result.iloc[-1]
        if int(first_slot["assigned_staff"]) <= 0:
            warnings.append("早番枠（最初の時間帯）が未充足です。")
        if int(last_slot["assigned_staff"]) <= 0:
            warnings.append("遅番枠（最後の時間帯）が未充足です。")

        total_required = int(slot_result["required_staff"].sum())
        total_assigned = int(slot_result["assigned_staff"].sum())
        total_required_reg = int(slot_result["required_reg_staff"].sum())
        total_assigned_reg = int(slot_result["assigned_reg_staff"].sum())
        result["total_required"] = total_required
        result["total_assigned"] = total_assigned
        result["fill_rate"] = (
            min(total_assigned / total_required, 1.0) if total_required > 0 else 1.0
        )
        result["reg_fill_rate"] = (
            min(total_assigned_reg / total_required_reg, 1.0)
            if total_required_reg > 0
            else 1.0
        )
    else:
        result["total_required"] = 0
        result["total_assigned"] = 0
        result["fill_rate"] = 1.0
        result["reg_fill_rate"] = 1.0

    if not staff_result.empty:
        violation_staff = staff_result[staff_result["alerts"].ne("")]
        if not violation_staff.empty:
            warnings.append(f"勤務時間制約の未充足スタッフ: {len(violation_staff)}名")

    result["slot_result"] = slot_result
    result["assignment_result"] = assignment_result
    result["staff_result"] = staff_result
    result["warnings"] = warnings
    return result


def upsert_constraints(master_df: pd.DataFrame, edited_df: pd.DataFrame) -> pd.DataFrame:
    if master_df.empty:
        return edited_df.copy()
    updated = master_df.copy()
    updated["staff_id"] = updated["staff_id"].astype(str).str.strip()
    edited = edited_df.copy()
    edited["staff_id"] = edited["staff_id"].astype(str).str.strip()

    updated = updated.set_index("staff_id")
    edited = edited.set_index("staff_id")
    for staff_id, row in edited.iterrows():
        if staff_id in updated.index:
            for col in edited.columns:
                updated.loc[staff_id, col] = row[col]
        else:
            updated.loc[staff_id, edited.columns] = row
    updated = updated.reset_index()
    return updated


def build_visual_staff_columns(
    constraints_df: pd.DataFrame,
    selected_store: str,
    include_help_staff: bool,
) -> list[tuple[str, str]]:
    if constraints_df.empty:
        return []

    base = constraints_df.copy()
    base["staff_id"] = base["staff_id"].astype(str).str.strip()
    base["staff_name"] = base["staff_name"].astype(str).str.strip()
    base["home_store"] = base["home_store"].astype(str).str.strip()
    base["can_work"] = base["can_work"].apply(to_bool)
    base["can_help"] = base["can_help"].apply(to_bool)

    if include_help_staff:
        base = base[
            base["can_work"]
            & ((base["home_store"] == str(selected_store)) | base["can_help"])
        ].copy()
    else:
        base = base[(base["can_work"]) & (base["home_store"] == str(selected_store))].copy()

    if base.empty:
        return []

    base = base.drop_duplicates(subset=["staff_id"])
    base["is_help_col"] = base["home_store"] != str(selected_store)
    base = base.sort_values(["is_help_col", "staff_name", "staff_id"])

    staff_cols: list[tuple[str, str]] = []
    for row in base.itertuples(index=False):
        staff_id = str(row.staff_id)
        label = f"{row.staff_name}({staff_id})"
        staff_cols.append((staff_id, label))
    return staff_cols


def build_vertical_shift_table(
    slot_df: pd.DataFrame,
    constraints_df: pd.DataFrame,
    selected_store: str,
    start_date: object,
    end_date: object,
    min_staff: int,
    max_staff: int,
    enforce_reg: bool,
    include_help_staff: bool,
    staff_columns: list[tuple[str, str]],
) -> pd.DataFrame:
    if slot_df.empty or not staff_columns:
        return pd.DataFrame()

    start_ts = pd.to_datetime(start_date).normalize()
    end_ts = pd.to_datetime(end_date).normalize()
    if end_ts < start_ts:
        start_ts, end_ts = end_ts, start_ts

    weekday_jp = ["月", "火", "水", "木", "金", "土", "日"]
    rows: list[dict[str, object]] = []

    for current_ts in pd.date_range(start_ts, end_ts, freq="D"):
        day_slots = slot_df[
            (slot_df["business_date"].dt.normalize() == current_ts)
            & (slot_df["store_code"].astype(str) == str(selected_store))
        ].copy()

        row: dict[str, object] = {
            "日付": current_ts.strftime("%Y-%m-%d"),
            "曜日": weekday_jp[current_ts.weekday()],
            "充足率": "-",
            "不足枠": 0,
            "REG不足": 0,
            "備考": "",
        }
        for _, label in staff_columns:
            row[label] = ""

        if day_slots.empty:
            row["備考"] = "POSデータなし"
            rows.append(row)
            continue

        demand_df = build_required_staff_plan(
            day_slots,
            min_staff=int(min_staff),
            max_staff=int(max(max_staff, min_staff)),
            enforce_reg=enforce_reg,
        )
        result = generate_shift_plan(
            demand_df=demand_df,
            constraints_df=constraints_df,
            selected_date=current_ts,
            selected_store=str(selected_store),
            include_help_staff=include_help_staff,
        )

        slot_result = result.get("slot_result", pd.DataFrame())
        staff_result = result.get("staff_result", pd.DataFrame())
        if not staff_result.empty:
            staff_result = staff_result.copy()
            staff_result["staff_id"] = staff_result["staff_id"].astype(str).str.strip()
            shift_map = (
                staff_result.set_index("staff_id")["shift_ranges"].astype(str).to_dict()
            )
        else:
            shift_map = {}

        for staff_id, label in staff_columns:
            row[label] = shift_map.get(str(staff_id), "")

        fill_rate = float(result.get("fill_rate", 0.0))
        row["充足率"] = f"{fill_rate * 100:.0f}%"
        if not slot_result.empty:
            row["不足枠"] = int(slot_result["staff_shortage"].sum())
            row["REG不足"] = int(slot_result["reg_shortage"].sum())
        warning_messages = result.get("warnings", [])
        if warning_messages:
            row["備考"] = " / ".join(warning_messages[:2])
        rows.append(row)

    column_order = ["日付", "曜日", "充足率", "不足枠", "REG不足"] + [
        label for _, label in staff_columns
    ] + ["備考"]
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out[column_order]


def render_sidebar_io() -> None:
    st.sidebar.markdown("## データコントロール")
    st.sidebar.caption("POS / 予算を読み込み、画面へ反映します。")

    if st.sidebar.button("デフォルトPOSを読込", use_container_width=True):
        if DEFAULT_POS_PATH.exists():
            try:
                st.session_state.sales_df = load_pos_from_path(DEFAULT_POS_PATH)
                ensure_store_master_from_sales()
                st.sidebar.success("デフォルトPOSを読込みました。")
            except Exception as exc:  # noqa: PERF203
                st.sidebar.error(str(exc))
        else:
            st.sidebar.error(f"ファイルが見つかりません: {DEFAULT_POS_PATH}")

    uploaded_pos = st.sidebar.file_uploader("POS CSVアップロード", type=["csv"], key="sidebar_pos")
    if uploaded_pos is not None and st.sidebar.button("アップロードPOSを反映", use_container_width=True):
        try:
            st.session_state.sales_df = load_pos_from_uploaded(uploaded_pos.getvalue())
            ensure_store_master_from_sales()
            st.sidebar.success("POS CSVを読込みました。")
        except Exception as exc:  # noqa: PERF203
            st.sidebar.error(str(exc))

    uploaded_budget = st.sidebar.file_uploader(
        "日割り予算Excelアップロード",
        type=["xlsx"],
        key="sidebar_budget",
    )
    if uploaded_budget is not None and st.sidebar.button("予算データを反映", use_container_width=True):
        try:
            budget_raw = pd.read_excel(uploaded_budget)
            st.session_state.budget_df = normalize_budget_df(budget_raw)
            st.sidebar.success("予算Excelを読込みました。")
        except Exception as exc:  # noqa: PERF203
            st.sidebar.error(str(exc))

    st.sidebar.divider()
    sales_df = st.session_state.sales_df
    if sales_df is None:
        st.sidebar.warning("POS未読込")
    else:
        min_date = sales_df["business_date"].min()
        max_date = sales_df["business_date"].max()
        st.sidebar.markdown(
            f"""
            <div class="section-note">
              <b>POSステータス</b><br>
              行数: {len(sales_df):,}<br>
              店舗数: {sales_df['store_code'].nunique():,}<br>
              期間: {min_date.date()} ～ {max_date.date()}
            </div>
            """,
            unsafe_allow_html=True,
        )

    if st.session_state.budget_df is None:
        st.sidebar.warning("予算未読込")
    else:
        st.sidebar.markdown(
            f"""
            <div class="section-note">
              <b>予算ステータス</b><br>
              行数: {len(st.session_state.budget_df):,}
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_overview() -> None:
    render_page_header(
        title="シフト管理ダッシュボード",
        subtitle="要件確認フェーズの使用感を、実データで即チェックできます。",
        chips=["プロトタイプ", "POS分析", "マスタ管理"],
    )
    sales_df = st.session_state.sales_df
    budget_df = st.session_state.budget_df

    sales_rows = f"{len(sales_df):,}" if sales_df is not None else "0"
    budget_rows = f"{len(budget_df):,}" if budget_df is not None else "0"
    stores = f"{len(st.session_state.stores_df):,}"
    staff = f"{len(st.session_state.staff_df):,}"
    render_kpi_cards(
        [
            ("POSデータ", "読込済" if sales_df is not None else "未読込", f"行数: {sales_rows}"),
            ("予算データ", "読込済" if budget_df is not None else "未読込", f"行数: {budget_rows}"),
            ("店舗マスタ", stores, "店舗定義"),
            ("スタッフ", staff, "販売力 / スキル"),
        ]
    )

    st.markdown(
        """
        <div class="section-note">
          <b>この画面で確認できる範囲</b>
          <ul>
            <li>マスタ登録（店舗 / スキル / スタッフ）</li>
            <li>POS取込プレビュー（商品分解 / カテゴリ / 30分帯売上構成比）</li>
            <li>指定日付の全店サマリー（売上 / 予算達成率 / ピーク帯）</li>
            <li>時間帯別の必要人員シミュレーション（簡易）</li>
            <li>日別・店舗別の自動シフト作成（制約編集 / 不足検知）</li>
          </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_master_page() -> None:
    render_page_header(
        title="マスタ登録",
        subtitle="店舗 / スキル / スタッフの定義を一元管理します。",
        chips=["マスタ", "編集", "権限対応"],
    )
    st.markdown(
        """
        <div class="section-note">
          <b>運用メモ</b>
          <ul>
            <li>POSから店舗一覧を初期生成し、その後は直接編集できます。</li>
            <li>スキルは将来追加を見越して自由に増やせます。</li>
            <li>スタッフの販売力 / REG対応を入力すると集計画面に反映されます。</li>
          </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_stores, tab_skills, tab_staff = st.tabs(["店舗", "スキル", "スタッフ"])

    with tab_stores:
        if st.button("POSから店舗一覧を再生成"):
            if st.session_state.sales_df is None:
                st.warning("POSデータを先に読込んでください。")
            else:
                stores = (
                    st.session_state.sales_df[["store_code", "store_name"]]
                    .drop_duplicates()
                    .copy()
                )
                stores["area"] = ""
                stores["min_staff"] = 2
                stores["max_staff"] = 8
                st.session_state.stores_df = stores[
                    ["store_code", "store_name", "area", "min_staff", "max_staff"]
                ]
                st.success("店舗マスタを更新しました。")
        edited_stores = st.data_editor(
            st.session_state.stores_df,
            num_rows="dynamic",
            use_container_width=True,
            key="stores_editor",
        )
        if st.button("店舗マスタを保存", key="save_stores"):
            st.session_state.stores_df = edited_stores.copy()
            st.success("保存しました。")

    with tab_skills:
        edited_skills = st.data_editor(
            st.session_state.skills_df,
            num_rows="dynamic",
            use_container_width=True,
            key="skills_editor",
        )
        if st.button("スキルマスタを保存", key="save_skills"):
            st.session_state.skills_df = edited_skills.copy()
            st.success("保存しました。")

    with tab_staff:
        edited_staff = st.data_editor(
            st.session_state.staff_df,
            num_rows="dynamic",
            use_container_width=True,
            key="staff_editor",
        )
        if st.button("スタッフマスタを保存", key="save_staff"):
            st.session_state.staff_df = edited_staff.copy()
            sync_shift_constraints_with_staff()
            st.success("保存しました。")

def render_pos_preview() -> None:
    render_page_header(
        title="POS取込プレビュー",
        subtitle="商品コード分解と30分帯売上構成比を、店舗ごとに可視化します。",
        chips=["30分帯", "カテゴリ分析", "プレビュー"],
    )
    sales_df = st.session_state.sales_df
    if sales_df is None or sales_df.empty:
        st.info("サイドバーからPOS CSVを読込んでください。")
        return

    slot_df = compute_slot_summary(sales_df)
    available_dates = sorted(sales_df["business_date"].dt.date.unique())

    control_col1, control_col2 = st.columns(2)
    selected_date = control_col1.selectbox("営業日", available_dates, index=len(available_dates) - 1)
    stores = (
        slot_df[slot_df["business_date"].dt.date == selected_date]["store_code"]
        .dropna()
        .unique()
        .tolist()
    )
    selected_store = control_col2.selectbox("店舗コード", stores, index=0)

    filtered_slots = slot_df[
        (slot_df["business_date"].dt.date == selected_date)
        & (slot_df["store_code"] == selected_store)
    ].copy()
    filtered_slots["slot_sales_ratio_pct"] = (filtered_slots["slot_sales_ratio"] * 100.0).round(2)

    peak_slot = "-"
    if not filtered_slots.empty:
        peak_slot = (
            filtered_slots.sort_values("slot_sales_ratio_pct", ascending=False)
            .iloc[0]["slot_label"]
        )

    c1, c2, c3 = st.columns(3)
    c1.metric("30分帯件数", f"{len(filtered_slots):,}")
    c2.metric("日次売上", f"{filtered_slots['slot_sales_amount'].sum():,.0f}")
    c3.metric("ピーク帯", peak_slot)

    left, right = st.columns([1.65, 1.0])

    with left:
        st.markdown("時間帯売上（30分）")
        left_table = filtered_slots[
            [
                "slot_label",
                "slot_sales_amount",
                "slot_sales_ratio_pct",
                "slot_qty",
                "slot_ticket_count",
            ]
        ].rename(
            columns={
                "slot_label": "時間帯",
                "slot_sales_amount": "売上",
                "slot_sales_ratio_pct": "売上構成比(%)",
                "slot_qty": "数量",
                "slot_ticket_count": "伝票件数",
            }
        )
        st.dataframe(
            left_table,
            column_config={
                "売上": st.column_config.NumberColumn(format="%.0f"),
                "売上構成比(%)": st.column_config.NumberColumn(format="%.2f"),
                "数量": st.column_config.NumberColumn(format="%.0f"),
                "伝票件数": st.column_config.NumberColumn(format="%.0f"),
            },
            hide_index=True,
            height=360,
            use_container_width=True,
        )

        chart_base = alt.Chart(filtered_slots).encode(
            x=alt.X(
                "slot_start:T",
                title="時間帯",
                axis=alt.Axis(
                    format="%H:%M",
                    labelAngle=0,
                    tickCount=12,
                    labelColor="#1f2429",
                    titleColor="#1f2429",
                    labelFontSize=12,
                    titleFontSize=13,
                ),
            ),
            y=alt.Y(
                "slot_sales_ratio_pct:Q",
                title="売上構成比(%)",
                axis=alt.Axis(
                    labelColor="#1f2429",
                    titleColor="#1f2429",
                    labelFontSize=12,
                    titleFontSize=13,
                ),
            ),
            tooltip=[
                alt.Tooltip("slot_label:N", title="時間帯"),
                alt.Tooltip("slot_sales_ratio_pct:Q", title="構成比(%)", format=".2f"),
                alt.Tooltip("slot_sales_amount:Q", title="売上", format=",.0f"),
                alt.Tooltip("slot_ticket_count:Q", title="伝票件数"),
            ],
        )
        area = chart_base.mark_area(color=CHART_SOFT, opacity=0.55)
        line = chart_base.mark_line(
            color=CHART_PRIMARY,
            strokeWidth=2.8,
            point=alt.OverlayMarkDef(color=CHART_SECONDARY, size=44),
        )
        slot_chart = (
            (area + line)
            .properties(height=290)
            .configure_axis(gridColor="#c6d7f3", domainColor="#88a6d8", tickColor="#88a6d8")
            .configure_view(strokeWidth=0)
        )
        st.altair_chart(slot_chart, use_container_width=True)

    detail = sales_df[
        (sales_df["business_date"].dt.date == selected_date)
        & (sales_df["store_code"] == selected_store)
    ].copy()
    category_sales = (
        detail.groupby(["item_category_cd", "item_category_name"], as_index=False)
        .agg(sales_amount=("sales_amount", "sum"))
        .sort_values("sales_amount", ascending=False)
    )
    category_total = category_sales["sales_amount"].sum()
    if category_total > 0:
        category_sales["sales_share_pct"] = (category_sales["sales_amount"] / category_total * 100).round(2)
    else:
        category_sales["sales_share_pct"] = 0.0

    with right:
        st.markdown("カテゴリ別売上")
        top_category = category_sales.head(10)
        cat_chart = alt.Chart(top_category).mark_bar(color=CHART_TERTIARY).encode(
            x=alt.X("sales_amount:Q", title="売上"),
            y=alt.Y("item_category_name:N", sort="-x", title="カテゴリ"),
            tooltip=[
                alt.Tooltip("item_category_cd:N", title="CD"),
                alt.Tooltip("item_category_name:N", title="カテゴリ"),
                alt.Tooltip("sales_amount:Q", title="売上", format=",.0f"),
                alt.Tooltip("sales_share_pct:Q", title="構成比(%)", format=".2f"),
            ],
        )
        st.altair_chart(cat_chart.properties(height=300), use_container_width=True)
        st.dataframe(
            category_sales[["item_category_cd", "item_category_name", "sales_amount", "sales_share_pct"]],
            hide_index=True,
            use_container_width=True,
        )

    st.markdown("商品明細プレビュー")
    st.dataframe(
        detail[
            [
                "receipt_no",
                "product_code_10",
                "color_cd",
                "size_cd",
                "item_category_cd",
                "item_category_name",
                "product_name",
                "sales_amount",
                "qty",
                "sales_datetime",
            ]
        ].head(200),
        hide_index=True,
        use_container_width=True,
    )

def render_daily_summary() -> None:
    render_page_header(
        title="指定日付の全店サマリー",
        subtitle="売上・予算・ピーク帯を1画面で比較し、必要人員の簡易シミュレーションまで確認します。",
        chips=["全店比較", "予算", "人員"],
    )
    sales_df = st.session_state.sales_df
    if sales_df is None or sales_df.empty:
        st.info("サイドバーからPOS CSVを読込んでください。")
        return

    slot_df = compute_slot_summary(sales_df)
    available_dates = sorted(sales_df["business_date"].dt.date.unique())
    control_col1, control_col2 = st.columns([1.0, 1.0])
    selected_date = control_col1.selectbox(
        "対象営業日",
        available_dates,
        index=len(available_dates) - 1,
        key="summary_date",
    )
    labor_rate = control_col2.slider(
        "推定人件費率（売上比）",
        min_value=0.05,
        max_value=0.40,
        value=0.18,
        step=0.01,
        format="%.2f",
    )

    day_sales = (
        sales_df[sales_df["business_date"].dt.date == selected_date]
        .groupby(["business_date", "store_code", "store_name"], as_index=False)
        .agg(
            sales_amount=("sales_amount", "sum"),
            qty=("qty", "sum"),
            tickets=("receipt_no", "nunique"),
        )
    )

    day_slot = slot_df[slot_df["business_date"].dt.date == selected_date].copy()
    peak = (
        day_slot.sort_values(["store_code", "slot_sales_ratio"], ascending=[True, False])
        .groupby("store_code", as_index=False)
        .first()[["store_code", "slot_label", "slot_sales_ratio"]]
        .rename(columns={"slot_label": "peak_slot", "slot_sales_ratio": "peak_ratio"})
    )

    summary = day_sales.merge(peak, on="store_code", how="left")

    if not st.session_state.staff_df.empty:
        staff_df = st.session_state.staff_df.copy()
        staff_df["sales_power"] = pd.to_numeric(staff_df["sales_power"], errors="coerce")
        staff_df["reg_skill"] = staff_df["reg_skill"].astype(str).str.lower().isin(
            ["true", "1", "yes", "y", "reg", "対応"]
        )
        staff_df["productivity_coeff"] = staff_df.apply(
            lambda row: sales_power_to_coeff(row["sales_power"], row["reg_skill"]), axis=1
        )
        staff_summary = (
            staff_df.groupby("home_store", as_index=False)
            .agg(
                store_staff_count=("staff_id", "count"),
                avg_sales_power=("sales_power", "mean"),
                productivity_coeff_sum=("productivity_coeff", "sum"),
            )
            .rename(columns={"home_store": "store_code"})
        )
        summary = summary.merge(staff_summary, on="store_code", how="left")

    if st.session_state.budget_df is not None and not st.session_state.budget_df.empty:
        budget = st.session_state.budget_df.copy()
        budget["date"] = pd.to_datetime(budget["date"]).dt.date
        day_budget = budget[budget["date"] == selected_date][["store_code", "budget_amount"]]
        summary = summary.merge(day_budget, on="store_code", how="left")
        summary["budget_attainment"] = (
            summary["sales_amount"] / summary["budget_amount"].replace(0, pd.NA)
        )
        summary["estimated_labor_cost"] = summary["sales_amount"] * labor_rate
        summary["budget_vs_labor_cost"] = (
            summary["estimated_labor_cost"] / summary["budget_amount"].replace(0, pd.NA)
        )

    summary = summary.sort_values("sales_amount", ascending=False)
    if summary.empty:
        st.warning("対象日のデータがありません。")
        return

    total_sales = summary["sales_amount"].sum()
    avg_peak = summary["peak_ratio"].mean() * 100 if "peak_ratio" in summary.columns else 0
    avg_attainment = (
        summary["budget_attainment"].dropna().mean() * 100
        if "budget_attainment" in summary.columns
        else float("nan")
    )
    render_kpi_cards(
        [
            ("対象店舗", f"{summary['store_code'].nunique():,}", selected_date.strftime("%Y-%m-%d")),
            ("全店売上", f"{total_sales:,.0f}", "指定日合計"),
            ("平均ピーク構成比", f"{avg_peak:.1f}%", "各店ピークの平均"),
            (
                "予算達成率",
                "-" if pd.isna(avg_attainment) else f"{avg_attainment:.1f}%",
                "平均値",
            ),
        ]
    )

    display = summary.copy()
    if "peak_ratio" in display.columns:
        display["peak_ratio"] = (display["peak_ratio"] * 100).round(2)
    if "budget_attainment" in display.columns:
        display["budget_attainment"] = (display["budget_attainment"] * 100).round(2)
    if "budget_vs_labor_cost" in display.columns:
        display["budget_vs_labor_cost"] = (display["budget_vs_labor_cost"] * 100).round(2)

    st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
    )

    chart_cols = st.columns([1.35, 1.0])
    with chart_cols[0]:
        sales_chart = alt.Chart(summary).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
            x=alt.X("store_code:N", sort="-y", title="店舗"),
            y=alt.Y("sales_amount:Q", title="売上"),
            color=alt.Color(
                "sales_amount:Q",
                scale=alt.Scale(range=[CHART_SOFT, CHART_PRIMARY]),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("store_code:N", title="店舗"),
                alt.Tooltip("sales_amount:Q", title="売上", format=",.0f"),
                alt.Tooltip("tickets:Q", title="伝票件数"),
                alt.Tooltip("peak_slot:N", title="ピーク帯"),
            ],
        )
        st.altair_chart(sales_chart.properties(height=320), use_container_width=True)

    with chart_cols[1]:
        peak_chart = alt.Chart(summary).mark_circle(size=130, color=CHART_SECONDARY).encode(
            x=alt.X("store_code:N", sort="-y", title="店舗"),
            y=alt.Y("peak_ratio:Q", title="ピーク構成比"),
            tooltip=[
                alt.Tooltip("store_code:N", title="店舗"),
                alt.Tooltip("peak_slot:N", title="ピーク帯"),
                alt.Tooltip("peak_ratio:Q", title="ピーク構成比", format=".2%"),
            ],
        )
        st.altair_chart(peak_chart.properties(height=320), use_container_width=True)

    st.markdown("---")
    st.markdown("### 時間帯シミュレーション")

    selected_store = st.selectbox("対象店舗", summary["store_code"].tolist())
    selected_store_slots = day_slot[day_slot["store_code"] == selected_store].copy()
    if selected_store_slots.empty:
        st.warning("対象店舗の時間帯データがありません。")
        return

    stores_df = st.session_state.stores_df
    default_min, default_max = 2, 8
    if not stores_df.empty and selected_store in stores_df["store_code"].values:
        row = stores_df[stores_df["store_code"] == selected_store].iloc[0]
        default_min = int(pd.to_numeric(row["min_staff"], errors="coerce") or 2)
        default_max = int(pd.to_numeric(row["max_staff"], errors="coerce") or 8)

    c1, c2, c3 = st.columns([1.0, 1.0, 1.2])
    min_staff = c1.number_input("最小人員", min_value=1, max_value=30, value=default_min)
    max_staff = c2.number_input("最大人員", min_value=1, max_value=30, value=max(default_max, min_staff))
    enforce_reg = c3.checkbox("各時間帯にREG対応者1名を必須", value=True)

    peak_ratio = selected_store_slots["slot_sales_ratio"].max()
    if peak_ratio <= 0:
        selected_store_slots["required_staff"] = min_staff
    else:
        scaled = selected_store_slots["slot_sales_ratio"] / peak_ratio
        selected_store_slots["required_staff"] = (
            min_staff + ((max_staff - min_staff) * scaled).round().astype(int)
        )
    selected_store_slots["required_staff"] = selected_store_slots["required_staff"].clip(
        lower=min_staff, upper=max_staff
    )
    selected_store_slots["required_reg_staff"] = 1 if enforce_reg else 0
    selected_store_slots["slot_sales_ratio_pct"] = (
        selected_store_slots["slot_sales_ratio"] * 100
    ).round(2)

    st.dataframe(
        selected_store_slots[
            [
                "slot_label",
                "slot_sales_ratio_pct",
                "slot_sales_amount",
                "required_staff",
                "required_reg_staff",
            ]
        ],
        hide_index=True,
        use_container_width=True,
    )

    sim_chart = alt.Chart(selected_store_slots).mark_line(
        color=CHART_PRIMARY,
        strokeWidth=2.7,
        point=alt.OverlayMarkDef(size=40, color=CHART_SECONDARY),
    ).encode(
        x=alt.X("slot_start:T", axis=alt.Axis(format="%H:%M", labelAngle=0), title="時間帯"),
        y=alt.Y("required_staff:Q", title="必要人員"),
        tooltip=[
            alt.Tooltip("slot_label:N", title="時間帯"),
            alt.Tooltip("required_staff:Q", title="必要人員"),
            alt.Tooltip("slot_sales_ratio_pct:Q", title="売上構成比(%)", format=".2f"),
        ],
    )
    st.altair_chart(sim_chart.properties(height=280), use_container_width=True)

    total_staff_hours = selected_store_slots["required_staff"].sum() * 0.5
    st.caption(f"推定総必要人時（30分単位換算）: {total_staff_hours:.1f} 人時")


def render_shift_builder_content() -> None:
    render_page_header(
        title="シフト作成",
        subtitle="30分単位の需要とスタッフ条件から、日別の自動シフト案を作成します。",
        chips=["自動作成", "制約編集", "不足可視化"],
    )
    sales_df = st.session_state.sales_df
    if sales_df is None or sales_df.empty:
        st.info("サイドバーからPOS CSVを読込んでください。")
        return
    if st.session_state.staff_df.empty:
        st.info("先にマスタ登録画面でスタッフマスタを入力してください。")
        return

    sync_shift_constraints_with_staff()
    slot_df = compute_slot_summary(sales_df)
    available_dates = sorted(sales_df["business_date"].dt.date.unique())

    top_col1, top_col2, top_col3 = st.columns([1.0, 1.0, 1.2])
    selected_date = top_col1.selectbox(
        "対象営業日",
        available_dates,
        index=len(available_dates) - 1,
        key="builder_date",
    )

    store_candidates = (
        slot_df[slot_df["business_date"].dt.date == selected_date]["store_code"]
        .dropna()
        .unique()
        .tolist()
    )
    if not store_candidates:
        st.warning("対象日の店舗データがありません。")
        return
    selected_store = top_col2.selectbox("対象店舗", store_candidates, key="builder_store")
    include_help_staff = top_col3.checkbox("他店ヘルプを候補に含める", value=True)

    selected_store_slots = slot_df[
        (slot_df["business_date"].dt.date == selected_date)
        & (slot_df["store_code"] == selected_store)
    ].copy()
    if selected_store_slots.empty:
        st.warning("選択店舗の時間帯データがありません。")
        return

    stores_df = st.session_state.stores_df
    default_min, default_max = 2, 8
    if not stores_df.empty and selected_store in stores_df["store_code"].astype(str).values:
        row = stores_df[stores_df["store_code"].astype(str) == str(selected_store)].iloc[0]
        default_min = int(pd.to_numeric(row["min_staff"], errors="coerce") or 2)
        default_max = int(pd.to_numeric(row["max_staff"], errors="coerce") or 8)

    req_col1, req_col2, req_col3 = st.columns([1.0, 1.0, 1.2])
    min_staff = req_col1.number_input(
        "最小人員",
        min_value=1,
        max_value=30,
        value=default_min,
        key="builder_min_staff",
    )
    max_staff = req_col2.number_input(
        "最大人員",
        min_value=1,
        max_value=30,
        value=max(default_max, min_staff),
        key="builder_max_staff",
    )
    enforce_reg = req_col3.checkbox("各時間帯にREG対応者を最低1名配置", value=True)

    demand_df = build_required_staff_plan(
        selected_store_slots,
        min_staff=int(min_staff),
        max_staff=int(max(max_staff, min_staff)),
        enforce_reg=enforce_reg,
    )

    st.markdown("### 需要（必要人員）の調整")
    st.caption("`required_staff` と `required_reg_staff` は手入力で調整できます。")
    demand_view = demand_df[
        [
            "slot_label",
            "slot_sales_ratio_pct",
            "slot_sales_amount",
            "required_staff",
            "required_reg_staff",
        ]
    ].copy()
    edited_demand = st.data_editor(
        demand_view,
        hide_index=True,
        use_container_width=True,
        column_config={
            "slot_label": st.column_config.TextColumn("時間帯", disabled=True),
            "slot_sales_ratio_pct": st.column_config.NumberColumn(
                "売上構成比(%)", format="%.2f", disabled=True
            ),
            "slot_sales_amount": st.column_config.NumberColumn("売上", format="%.0f", disabled=True),
            "required_staff": st.column_config.NumberColumn(
                "必要人員",
                min_value=0,
                max_value=30,
                step=1,
            ),
            "required_reg_staff": st.column_config.NumberColumn(
                "REG必要人数",
                min_value=0,
                max_value=5,
                step=1,
            ),
        },
        key=f"demand_editor_{selected_store}_{selected_date}",
    )
    demand_df["required_staff"] = pd.to_numeric(
        edited_demand["required_staff"], errors="coerce"
    ).fillna(0).astype(int)
    demand_df["required_reg_staff"] = pd.to_numeric(
        edited_demand["required_reg_staff"], errors="coerce"
    ).fillna(0).astype(int)

    st.markdown("### スタッフ制約")
    st.caption(
        "曜日は `0-6`（月=0）や `月,火` で入力可。休み希望は `YYYY-MM-DD` をカンマ区切り。"
    )

    constraints_master = st.session_state.shift_constraints_df.copy()
    constraints_master["home_store"] = constraints_master["home_store"].astype(str).str.strip()
    constraints_master["can_help"] = constraints_master["can_help"].apply(to_bool)
    candidate_constraints = constraints_master[
        (constraints_master["home_store"] == str(selected_store))
        | (include_help_staff & constraints_master["can_help"])
    ].copy()
    if candidate_constraints.empty:
        st.warning("対象店舗に割当可能なスタッフがいません。")
        return

    edit_cols = [
        "staff_id",
        "staff_name",
        "home_store",
        "sales_power",
        "reg_skill",
        "can_work",
        "can_help",
        "available_weekdays",
        "earliest_start",
        "latest_end",
        "min_shift_hours",
        "max_shift_hours",
        "day_off_dates",
        "preferred_shift",
    ]
    edited_constraints = st.data_editor(
        candidate_constraints[edit_cols],
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "staff_id": st.column_config.TextColumn("ID", disabled=True),
            "staff_name": st.column_config.TextColumn("スタッフ名", disabled=True),
            "home_store": st.column_config.TextColumn("所属店舗", disabled=True),
            "sales_power": st.column_config.NumberColumn("販売力"),
            "reg_skill": st.column_config.CheckboxColumn("REG"),
            "can_work": st.column_config.CheckboxColumn("勤務対象"),
            "can_help": st.column_config.CheckboxColumn("ヘルプ可"),
            "available_weekdays": st.column_config.TextColumn("勤務曜日"),
            "earliest_start": st.column_config.TextColumn("開始時刻"),
            "latest_end": st.column_config.TextColumn("終了時刻"),
            "min_shift_hours": st.column_config.NumberColumn("最小時間", format="%.1f"),
            "max_shift_hours": st.column_config.NumberColumn("最大時間", format="%.1f"),
            "day_off_dates": st.column_config.TextColumn("休み希望"),
            "preferred_shift": st.column_config.SelectboxColumn(
                "希望帯",
                options=["any", "early", "late"],
            ),
        },
        key=f"constraints_editor_{selected_store}_{selected_date}",
    )

    action_col1, action_col2 = st.columns([1.0, 1.0])
    working_constraints = upsert_constraints(st.session_state.shift_constraints_df, edited_constraints)
    if action_col1.button("スタッフ制約を保存", use_container_width=True):
        st.session_state.shift_constraints_df = working_constraints
        st.success("スタッフ制約を保存しました。")

    if action_col2.button("自動シフトを作成", use_container_width=True, type="primary"):
        merged_constraints = working_constraints
        st.session_state.shift_constraints_df = merged_constraints
        result = generate_shift_plan(
            demand_df=demand_df,
            constraints_df=merged_constraints,
            selected_date=selected_date,
            selected_store=str(selected_store),
            include_help_staff=include_help_staff,
        )
        st.session_state.last_shift_result = {
            "date": selected_date,
            "store_code": str(selected_store),
            "constraints_df": merged_constraints.copy(),
            "include_help_staff": bool(include_help_staff),
            "min_staff": int(min_staff),
            "max_staff": int(max(max_staff, min_staff)),
            "enforce_reg": bool(enforce_reg),
            "result": result,
        }
        st.session_state.last_vertical_shift_table = None

    last_shift = st.session_state.last_shift_result
    if not last_shift:
        return
    if (
        last_shift.get("date") != selected_date
        or last_shift.get("store_code") != str(selected_store)
    ):
        st.info("この条件での結果を表示するには「自動シフトを作成」を実行してください。")
        return

    result = last_shift["result"]
    slot_result = result.get("slot_result", pd.DataFrame())
    assignment_result = result.get("assignment_result", pd.DataFrame())
    staff_result = result.get("staff_result", pd.DataFrame())

    if slot_result.empty:
        st.warning("シフトを作成できませんでした。制約を見直してください。")
        for msg in result.get("warnings", []):
            st.caption(f"- {msg}")
        return

    render_kpi_cards(
        [
            (
                "充足率",
                f"{(result.get('fill_rate', 0.0) * 100):.1f}%",
                f"必要枠 {result.get('total_required', 0):,}",
            ),
            (
                "REG充足率",
                f"{(result.get('reg_fill_rate', 0.0) * 100):.1f}%",
                "各時間帯のREG必須枠",
            ),
            (
                "割当スタッフ数",
                f"{len(staff_result):,}",
                f"総人時 {staff_result['assigned_hours'].sum():.1f}h" if not staff_result.empty else "0h",
            ),
            (
                "不足時間帯",
                f"{int((slot_result['staff_shortage'] > 0).sum()):,}",
                "要調整",
            ),
        ]
    )

    warning_messages = result.get("warnings", [])
    if warning_messages:
        st.markdown(
            "<div class='section-note'><b>制約アラート</b></div>",
            unsafe_allow_html=True,
        )
        for message in warning_messages:
            st.warning(message)

    st.markdown("### 時間帯別の割当結果")
    display_slot = slot_result[
        [
            "slot_label",
            "slot_sales_ratio_pct",
            "required_staff",
            "assigned_staff",
            "staff_shortage",
            "required_reg_staff",
            "assigned_reg_staff",
            "reg_shortage",
            "assigned_staff_names",
        ]
    ].copy()
    display_slot = display_slot.rename(
        columns={
            "slot_label": "時間帯",
            "slot_sales_ratio_pct": "売上構成比(%)",
            "required_staff": "必要人員",
            "assigned_staff": "割当人数",
            "staff_shortage": "不足人数",
            "required_reg_staff": "REG必要",
            "assigned_reg_staff": "REG割当",
            "reg_shortage": "REG不足",
            "assigned_staff_names": "割当スタッフ",
        }
    )
    st.dataframe(
        display_slot,
        hide_index=True,
        use_container_width=True,
        column_config={
            "売上構成比(%)": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    chart_df = slot_result.copy()
    need_line = alt.Chart(chart_df).mark_line(
        color=CHART_PRIMARY,
        strokeWidth=2.8,
    ).encode(
        x=alt.X("slot_start:T", axis=alt.Axis(format="%H:%M", labelAngle=0), title="時間帯"),
        y=alt.Y("required_staff:Q", title="人数"),
        tooltip=[
            alt.Tooltip("slot_label:N", title="時間帯"),
            alt.Tooltip("required_staff:Q", title="必要人員"),
            alt.Tooltip("assigned_staff:Q", title="割当人数"),
        ],
    )
    assigned_line = alt.Chart(chart_df).mark_line(
        color=CHART_TERTIARY,
        strokeWidth=2.8,
        strokeDash=[6, 4],
    ).encode(
        x=alt.X("slot_start:T", axis=alt.Axis(format="%H:%M", labelAngle=0), title="時間帯"),
        y=alt.Y("assigned_staff:Q", title="人数"),
    )
    st.altair_chart((need_line + assigned_line).properties(height=280), use_container_width=True)

    st.markdown("### スタッフ別シフト")
    if staff_result.empty:
        st.info("割当されたスタッフがいません。")
    else:
        display_staff = staff_result.rename(
            columns={
                "staff_id": "ID",
                "staff_name": "スタッフ名",
                "home_store": "所属店舗",
                "is_help": "ヘルプ",
                "assigned_slots": "割当コマ数",
                "assigned_hours": "割当時間",
                "shift_blocks": "分割数",
                "shift_ranges": "シフト帯",
                "avg_sales_power": "販売力",
                "productivity_coeff": "人時係数",
                "estimated_labor_cost": "推定人件費",
                "alerts": "アラート",
            }
        )
        st.dataframe(
            display_staff,
            hide_index=True,
            use_container_width=True,
            column_config={
                "割当時間": st.column_config.NumberColumn(format="%.1f"),
                "販売力": st.column_config.NumberColumn(format="%.1f"),
                "人時係数": st.column_config.NumberColumn(format="%.2f"),
                "推定人件費": st.column_config.NumberColumn(format="%.0f"),
            },
        )

    st.markdown("### 日別シフト表（縦型 / 1人1列）")
    st.caption("下方向に日付が進み、1スタッフを1列で表示します。")
    min_available_date = min(available_dates)
    max_available_date = max(available_dates)
    default_end_date = min(
        (pd.Timestamp(selected_date) + pd.Timedelta(days=6)).date(),
        max_available_date,
    )

    view_col1, view_col2, view_col3 = st.columns([1.0, 1.0, 1.1])
    view_start_date = view_col1.date_input(
        "表示開始日",
        value=selected_date,
        min_value=min_available_date,
        max_value=max_available_date,
        key=f"vertical_start_{selected_store}",
    )
    view_end_date = view_col2.date_input(
        "表示終了日",
        value=default_end_date,
        min_value=min_available_date,
        max_value=max_available_date,
        key=f"vertical_end_{selected_store}",
    )
    regenerate_vertical = view_col3.button("縦型シフト表を更新", use_container_width=True)

    if view_start_date > view_end_date:
        st.error("表示開始日が終了日を超えています。")
    elif regenerate_vertical:
        visual_constraints = last_shift.get("constraints_df", st.session_state.shift_constraints_df)
        include_help_for_view = bool(last_shift.get("include_help_staff", include_help_staff))
        min_staff_for_view = int(last_shift.get("min_staff", int(min_staff)))
        max_staff_for_view = int(last_shift.get("max_staff", int(max(max_staff, min_staff))))
        enforce_reg_for_view = bool(last_shift.get("enforce_reg", enforce_reg))

        staff_columns = build_visual_staff_columns(
            visual_constraints,
            selected_store=str(selected_store),
            include_help_staff=include_help_for_view,
        )
        if not staff_columns:
            st.warning("縦型シフト表に表示するスタッフがいません。")
            st.session_state.last_vertical_shift_table = None
        else:
            with st.spinner("縦型シフト表を作成中..."):
                vertical_table = build_vertical_shift_table(
                    slot_df=slot_df,
                    constraints_df=visual_constraints,
                    selected_store=str(selected_store),
                    start_date=view_start_date,
                    end_date=view_end_date,
                    min_staff=min_staff_for_view,
                    max_staff=max_staff_for_view,
                    enforce_reg=enforce_reg_for_view,
                    include_help_staff=include_help_for_view,
                    staff_columns=staff_columns,
                )
            st.session_state.last_vertical_shift_table = {
                "store_code": str(selected_store),
                "start_date": view_start_date,
                "end_date": view_end_date,
                "table": vertical_table,
            }

    vertical_payload = st.session_state.last_vertical_shift_table
    vertical_table = pd.DataFrame()
    if (
        vertical_payload
        and vertical_payload.get("store_code") == str(selected_store)
        and isinstance(vertical_payload.get("table"), pd.DataFrame)
    ):
        vertical_table = vertical_payload["table"]

    if vertical_table.empty:
        st.info("縦型シフト表は「縦型シフト表を更新」で表示されます。")
    else:
        st.dataframe(
            vertical_table,
            hide_index=True,
            use_container_width=True,
            height=min(780, 180 + (len(vertical_table) * 36)),
        )
        vertical_csv = vertical_table.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "縦型シフト表CSVをダウンロード",
            data=vertical_csv,
            file_name=f"shift_calendar_vertical_{selected_store}_{vertical_payload['start_date']}_{vertical_payload['end_date']}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with st.expander("30分シフトマトリクス（詳細）", expanded=False):
        if assignment_result.empty:
            st.info("マトリクス表示対象がありません。")
        else:
            matrix_src = assignment_result.copy()
            matrix_src["mark"] = "●"
            matrix = matrix_src.pivot_table(
                index="slot_label",
                columns="staff_name",
                values="mark",
                aggfunc="first",
                fill_value="",
            )
            slot_order = (
                slot_result[["slot_label", "slot_start"]]
                .drop_duplicates()
                .sort_values("slot_start")["slot_label"]
                .tolist()
            )
            matrix = matrix.reindex(slot_order)
            st.dataframe(matrix, use_container_width=True)

    slot_csv = slot_result.to_csv(index=False).encode("utf-8-sig")
    staff_csv = staff_result.to_csv(index=False).encode("utf-8-sig")
    dl_col1, dl_col2 = st.columns([1.0, 1.0])
    dl_col1.download_button(
        "時間帯割当CSVをダウンロード",
        data=slot_csv,
        file_name=f"shift_slot_{selected_store}_{selected_date}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    dl_col2.download_button(
        "スタッフ割当CSVをダウンロード",
        data=staff_csv,
        file_name=f"shift_staff_{selected_store}_{selected_date}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.markdown(
        """
        <div class="section-note">
          <b>制約の適用範囲（現時点）</b><br>
          休み希望・曜日・開始/終了時刻・最大勤務時間・REG必須を反映しています。<br>
          連勤日数（3〜4優先 / 最大6）や月間最適化は次ステップで拡張します。
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_manual_shift_builder() -> None:
    st.markdown("### 手入力シフト作成")
    st.caption("記号入力と時間入力を併用して、手動でシフトを作成できます。")

    sales_df = st.session_state.sales_df
    if sales_df is None or sales_df.empty:
        st.info("サイドバーからPOS CSVを読込んでください。")
        return
    if st.session_state.staff_df.empty:
        st.info("先にマスタ登録画面でスタッフマスタを入力してください。")
        return

    sync_shift_constraints_with_staff()
    available_dates = sorted(sales_df["business_date"].dt.date.unique())
    min_date = min(available_dates)
    max_date = max(available_dates)

    if not st.session_state.stores_df.empty:
        store_candidates = (
            st.session_state.stores_df["store_code"]
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .unique()
            .tolist()
        )
    else:
        store_candidates = (
            sales_df["store_code"].astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist()
        )
    store_candidates = sorted(store_candidates)
    if not store_candidates:
        st.warning("店舗候補がありません。")
        return

    ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns([1.0, 1.0, 1.0, 1.2])
    selected_store = ctrl_col1.selectbox("対象店舗", store_candidates, key="manual_store")
    start_date = ctrl_col2.date_input(
        "開始日",
        value=max_date,
        min_value=min_date,
        max_value=max_date,
        key="manual_start_date",
    )
    default_end = min((pd.Timestamp(start_date) + pd.Timedelta(days=6)).date(), max_date)
    end_date = ctrl_col3.date_input(
        "終了日",
        value=default_end,
        min_value=min_date,
        max_value=max_date,
        key="manual_end_date",
    )
    include_help_staff = ctrl_col4.checkbox("他店ヘルプも表示", value=True, key="manual_include_help")

    if start_date > end_date:
        st.error("開始日が終了日を超えています。")
        return

    staff_columns = build_visual_staff_columns(
        st.session_state.shift_constraints_df,
        selected_store=str(selected_store),
        include_help_staff=include_help_staff,
    )
    if not staff_columns:
        st.warning("手入力対象のスタッフがいません。")
        return

    shift_ranges = resolve_shift_time_ranges_for_store(selected_store)
    st.markdown(
        f"""
        <div class="section-note">
          <b>記号入力ルール</b><br>
          〇 = 早番（{shift_ranges['early'][0]}-{shift_ranges['early'][1]}）<br>
          △ = 中番（{shift_ranges['middle'][0]}-{shift_ranges['middle'][1]}）<br>
          ✕ = 遅番（{shift_ranges['late'][0]}-{shift_ranges['late'][1]}）<br>
          直接入力: <code>10:00-18:30</code> も利用できます。
        </div>
        """,
        unsafe_allow_html=True,
    )

    context_key = "|".join(
        [
            str(selected_store),
            str(start_date),
            str(end_date),
            "1" if include_help_staff else "0",
            ",".join([staff_id for staff_id, _ in staff_columns]),
        ]
    )
    if st.session_state.manual_shift_context != context_key:
        st.session_state.manual_shift_context = context_key
        st.session_state.manual_shift_input_df = build_manual_shift_template(
            start_date=start_date,
            end_date=end_date,
            staff_columns=staff_columns,
        )
        st.session_state.manual_shift_result = None

    action_col1, action_col2 = st.columns([1.0, 1.0])
    if action_col1.button("手入力表を初期化", use_container_width=True, key="manual_reset"):
        st.session_state.manual_shift_input_df = build_manual_shift_template(
            start_date=start_date,
            end_date=end_date,
            staff_columns=staff_columns,
        )
        st.session_state.manual_shift_result = None
        st.success("入力表を初期化しました。")

    run_parse = action_col2.button(
        "記号を展開して確定プレビュー",
        use_container_width=True,
        type="primary",
        key="manual_parse",
    )

    manual_df = st.session_state.manual_shift_input_df.copy()
    edited_manual = st.data_editor(
        manual_df,
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "日付": st.column_config.TextColumn("日付", disabled=True),
            "曜日": st.column_config.TextColumn("曜日", disabled=True),
        },
        key=f"manual_editor_{selected_store}_{start_date}_{end_date}_{1 if include_help_staff else 0}",
    )
    st.session_state.manual_shift_input_df = edited_manual.copy()

    if run_parse:
        normalized_table, detail_df = parse_manual_shift_table(
            manual_df=edited_manual,
            staff_columns=staff_columns,
            shift_time_ranges=shift_ranges,
        )
        st.session_state.manual_shift_result = {
            "context_key": context_key,
            "table": normalized_table,
            "detail": detail_df,
        }

    manual_result = st.session_state.manual_shift_result
    if (
        not manual_result
        or manual_result.get("context_key") != context_key
        or not isinstance(manual_result.get("table"), pd.DataFrame)
    ):
        st.info("入力後に「記号を展開して確定プレビュー」を押してください。")
        return

    normalized_table = manual_result["table"]
    detail_df = manual_result.get("detail", pd.DataFrame())

    st.markdown("### 確定プレビュー（記号展開後）")
    st.dataframe(
        normalized_table,
        hide_index=True,
        use_container_width=True,
        height=min(780, 180 + (len(normalized_table) * 36)),
    )

    if isinstance(detail_df, pd.DataFrame) and not detail_df.empty:
        error_df = detail_df[detail_df["error"].astype(str).str.strip().ne("")]
        if not error_df.empty:
            st.warning(f"入力エラー: {len(error_df):,}件")
            st.dataframe(
                error_df[["date", "staff_label", "input_text", "error"]],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.success("入力エラーはありません。")

    csv_col1, csv_col2 = st.columns([1.0, 1.0])
    csv_col1.download_button(
        "手入力シフト表CSV",
        data=normalized_table.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"manual_shift_{selected_store}_{start_date}_{end_date}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    if isinstance(detail_df, pd.DataFrame):
        csv_col2.download_button(
            "手入力シフト明細CSV",
            data=detail_df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"manual_shift_detail_{selected_store}_{start_date}_{end_date}.csv",
            mime="text/csv",
            use_container_width=True,
        )


def render_shift_builder() -> None:
    shift_tab = st.tabs(["シフト作成"])[0]
    with shift_tab:
        sub_auto, sub_manual = st.tabs(["自動作成", "手入力作成"])
        with sub_auto:
            render_shift_builder_content()
        with sub_manual:
            render_manual_shift_builder()


def main() -> None:
    st.set_page_config(
        page_title="シフト管理プロトタイプ",
        page_icon=":material/insights:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_modern_theme()

    init_session_state()
    render_sidebar_io()

    page = st.sidebar.radio(
        "画面",
        ["概要", "マスタ登録", "POS取込プレビュー", "日別全店サマリー", "シフト作成"],
        index=0,
    )

    if page == "概要":
        render_overview()
    elif page == "マスタ登録":
        render_master_page()
    elif page == "POS取込プレビュー":
        render_pos_preview()
    elif page == "日別全店サマリー":
        render_daily_summary()
    elif page == "シフト作成":
        st.sidebar.caption("サイドバー左上の矢印で、表示/非表示を切り替えできます。")
        render_shift_builder()


if __name__ == "__main__":
    main()





