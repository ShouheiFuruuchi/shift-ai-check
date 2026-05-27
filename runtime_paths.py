from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parent
PATH_SETTINGS_PATH = APP_ROOT / "path_settings.json"


@dataclass(frozen=True)
class ShiftRuntimePaths:
    shift_excel_path: Path
    copyfile_path: Path
    timescheduler_path: Path
    timescheduler_backup_path: Path
    budget_path: Path
    delivery_path: Path


def project_path(*parts: str) -> Path:
    return APP_ROOT.joinpath(*parts)


def load_path_settings() -> dict[str, Any]:
    if not PATH_SETTINGS_PATH.exists():
        return {}
    with PATH_SETTINGS_PATH.open("r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("path_settings.json must be a JSON object.")
    return data


def _expand_to_path(raw: str | None, *, base_dir: Path) -> Path | None:
    if not raw:
        return None
    expanded = os.path.expandvars(os.path.expanduser(str(raw)))
    path = Path(expanded)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _latest_match(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None
    matches = sorted(
        (path for path in directory.glob(pattern) if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def resolve_shift_runtime_paths(year: int, month: int) -> ShiftRuntimePaths:
    cfg = load_path_settings()
    home = Path.home()
    workspace_dir = home / "Desktop" / "TS" / "シフトコピー"

    shift_excel_path = _expand_to_path(cfg.get("shift_excel_path"), base_dir=home)
    if shift_excel_path is None:
        shift_excel_dir = _expand_to_path(cfg.get("shift_excel_dir"), base_dir=home) or (home / "Downloads")
        shift_excel_glob = cfg.get("shift_excel_glob") or f"{year} {month}月シフト 【販売部】 ver 18*.xls*"
        shift_excel_path = _latest_match(shift_excel_dir, shift_excel_glob)
        if shift_excel_path is None:
            raise FileNotFoundError(
                "Monthly shift workbook not found. "
                f"Set shift_excel_path in {PATH_SETTINGS_PATH.name} or place a file matching "
                f"'{shift_excel_glob}' under '{shift_excel_dir}'."
            )

    return ShiftRuntimePaths(
        shift_excel_path=shift_excel_path,
        copyfile_path=_expand_to_path(cfg.get("copyfile_path"), base_dir=home) or (workspace_dir / "SELECT_FILE.xlsm"),
        timescheduler_path=_expand_to_path(cfg.get("timescheduler_path"), base_dir=home) or (workspace_dir / "TimeScheduler.xlsx"),
        timescheduler_backup_path=_expand_to_path(cfg.get("timescheduler_backup_path"), base_dir=home)
        or (workspace_dir / "保管" / "TimeScheduler.xlsx"),
        budget_path=_expand_to_path(cfg.get("budget_path"), base_dir=home) or (workspace_dir / "年間予算.xlsx"),
        delivery_path=_expand_to_path(cfg.get("delivery_path"), base_dir=home) or (workspace_dir / "納品スケジュール.xlsx"),
    )
