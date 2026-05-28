"""
POSデータのロードを抽象化するモジュール。

path_settings.json に sql_server セクションが設定されていれば SQL Server から取得し、
なければローカルの大容量CSVを自動検出する。

取得したデータはスクリプトと同じディレクトリの .pos_cache/ にCSVとしてキャッシュされる。
キャッシュが当日より新しければ再取得しない（毎日1回のみSQL Server に接続）。
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from runtime_paths import APP_ROOT, load_path_settings


def resolve_pos_path(year: int, pos_arg: str = "", base_dir: Optional[Path] = None) -> Path:
    """
    POSデータのファイルパスを解決して返す。

    優先順位:
      1. pos_arg が指定されている → そのパスを使用
      2. path_settings.json の sql_server が設定済み → SQL Server から取得してキャッシュCSVを返す
      3. それ以外 → base_dir 内で 100MB 超の *{year}*.csv を自動検出

    Args:
        year: 対象年
        pos_arg: --pos 等で渡された明示的なファイルパス（省略可）
        base_dir: 自動検出の基準ディレクトリ（省略時は shift-ai-check ディレクトリ）

    Returns:
        POSデータCSVのパス
    """
    if base_dir is None:
        base_dir = APP_ROOT

    if pos_arg:
        p = Path(pos_arg)
        if p.is_absolute():
            return p
        candidate = (base_dir / p).resolve()
        return candidate

    cfg = load_path_settings()
    sql_cfg = cfg.get("sql_server")

    if _is_sql_configured(sql_cfg):
        cache_dir = base_dir / ".pos_cache"
        cache_dir.mkdir(exist_ok=True)
        return _load_from_sql(sql_cfg, year, cache_dir)  # type: ignore[arg-type]

    return _detect_local_csv(base_dir, year)


def _is_sql_configured(sql_cfg: object) -> bool:
    if not isinstance(sql_cfg, dict):
        return False
    return bool(
        sql_cfg.get("server")
        and sql_cfg.get("database")
        and sql_cfg.get("pos_table")
    )


def _build_conn_str(sql_cfg: dict) -> str:
    server = sql_cfg.get("server", "localhost")
    database = sql_cfg.get("database", "")
    driver = sql_cfg.get("driver", "ODBC Driver 17 for SQL Server")

    if sql_cfg.get("trusted_connection", True):
        return (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            "Trusted_Connection=yes;"
        )
    uid = sql_cfg.get("username", "")
    pwd = sql_cfg.get("password", "")
    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={uid};PWD={pwd};"
    )


def _load_from_sql(sql_cfg: dict, year: int, cache_dir: Path) -> Path:
    """SQL Server からPOSデータを取得し、キャッシュCSVとして保存して返す。"""
    cache_path = cache_dir / f"pos_cache_{year}.csv"

    # 当日中のキャッシュがあれば再利用
    if cache_path.exists():
        mtime = datetime.date.fromtimestamp(cache_path.stat().st_mtime)
        if mtime >= datetime.date.today():
            return cache_path

    try:
        import pyodbc  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "pyodbc がインストールされていません。"
            "`pip install pyodbc` を実行してください。"
        ) from exc

    table = sql_cfg["pos_table"]
    column_map: dict[str, str] = sql_cfg.get("column_map", {})
    date_col_sql = column_map.get("営業日付", "営業日付")

    conn_str = _build_conn_str(sql_cfg)

    print(f"[pos_loader] SQL Server に接続中: {sql_cfg.get('server')} / {sql_cfg.get('database')}")
    conn = pyodbc.connect(conn_str)
    try:
        query = f"SELECT * FROM [{table}] WHERE YEAR([{date_col_sql}]) = {year}"
        df = pd.read_sql(query, conn)
    finally:
        conn.close()

    df = _apply_column_map(df, column_map)
    df = _normalize_date_column(df)
    df.to_csv(cache_path, index=False, encoding="utf-8-sig")
    print(f"[pos_loader] キャッシュ保存: {cache_path} ({len(df):,} 行)")
    return cache_path


def _apply_column_map(df: pd.DataFrame, column_map: dict[str, str]) -> pd.DataFrame:
    """column_map の値（SQL列名）→ キー（スクリプトが期待する列名）にリネーム。"""
    rename = {v: k for k, v in column_map.items() if v and v != k}
    if rename:
        df = df.rename(columns=rename)
    return df


def _normalize_date_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    営業日付 を YYYYMMDD 整数形式に統一する。
    既存スクリプトは pd.to_datetime でも整数比較でも読めるように
    YYYYMMDD 整数として保存する。
    """
    if "営業日付" not in df.columns:
        return df
    col = pd.to_datetime(df["営業日付"], errors="coerce")
    df["営業日付"] = col.dt.strftime("%Y%m%d").where(col.notna(), other=None)
    return df


def _detect_local_csv(base_dir: Path, year: int) -> Path:
    """base_dir 内で 100MB 超の *{year}*.csv を最大サイズ順に検索。"""
    candidates = sorted(
        [p for p in base_dir.glob(f"*{year}*.csv") if p.stat().st_size > 100_000_000],
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            f"{year}年のPOS CSVが見つかりません。\n"
            f"  - CSVを {base_dir} に置く\n"
            f"  - または shift-ai-check/path_settings.json の sql_server を設定する\n"
            "  のどちらかを行ってください。"
        )
    return candidates[0]
