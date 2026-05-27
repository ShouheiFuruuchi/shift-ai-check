import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd


@dataclass
class StepResult:
    name: str
    ok: bool
    command: List[str]
    output_paths: List[Path]
    stdout_tail: str
    stderr_tail: str


def detect_month(attendance_path: Path) -> Tuple[int, int]:
    df = pd.read_csv(attendance_path, encoding="utf-8-sig", usecols=["date"])
    dt = pd.to_datetime(df["date"], errors="coerce").dropna()
    if dt.empty:
        raise ValueError("attendance_summary.csv から年月を判定できません。")
    latest = dt.max()
    return int(latest.year), int(latest.month)


def detect_pos_file(base_dir: Path, year: int) -> Path:
    cands = sorted(
        [p for p in base_dir.glob(f"*{year}*.csv") if p.stat().st_size > 100_000_000],
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not cands:
        raise FileNotFoundError(f"{year}年のPOS CSVが見つかりません。")
    return cands[0]


def run_step(
    name: str,
    cmd: Sequence[str],
    output_paths: Sequence[Path],
    cwd: Path,
    timeout_sec: int = 1800,
) -> StepResult:
    proc = subprocess.run(
        list(cmd),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
    )
    stdout_tail = proc.stdout[-4000:] if proc.stdout else ""
    stderr_tail = proc.stderr[-4000:] if proc.stderr else ""
    ok = proc.returncode == 0
    return StepResult(
        name=name,
        ok=ok,
        command=list(cmd),
        output_paths=list(output_paths),
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
    )


def write_manifest(results: List[StepResult], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, str]] = []
    for r in results:
        for p in r.output_paths:
            rows.append(
                {
                    "step": r.name,
                    "status": "OK" if r.ok else "NG",
                    "file": str(p),
                    "exists": str(p.exists()),
                }
            )
        if not r.output_paths:
            rows.append(
                {
                    "step": r.name,
                    "status": "OK" if r.ok else "NG",
                    "file": "",
                    "exists": "",
                }
            )

    pd.DataFrame(rows).to_csv(
        out_dir / "analysis_suite_manifest.csv", index=False, encoding="utf-8-sig"
    )

    details = [
        {
            "step": r.name,
            "ok": r.ok,
            "command": r.command,
            "stdout_tail": r.stdout_tail,
            "stderr_tail": r.stderr_tail,
        }
        for r in results
    ]
    with open(out_dir / "analysis_suite_manifest.json", "w", encoding="utf-8") as f:
        json.dump(details, f, ensure_ascii=False, indent=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run shift/POS analytics set and collect outputs."
    )
    parser.add_argument("--year", type=int, default=None, help="Target year")
    parser.add_argument("--month", type=int, default=None, help="Target month")
    parser.add_argument(
        "--attendance",
        default="attendance_summary.csv",
        help="attendance_summary.csv path",
    )
    parser.add_argument(
        "--pos-year",
        default="",
        help="POS CSV for target year (optional, auto-detect if omitted)",
    )
    parser.add_argument(
        "--pos-2024",
        default="",
        help="POS CSV for 2024 (for shift_analytics / budget)",
    )
    parser.add_argument(
        "--pos-2025",
        default="",
        help="POS CSV for 2025 (for shift_analytics / budget)",
    )
    parser.add_argument(
        "--budget-daily-xlsx",
        default="",
        help="Daily budget xlsx path (optional; when set, budget allocation runs)",
    )
    parser.add_argument(
        "--budget-daily-sheet",
        default="DATA",
        help="Sheet name for daily budget xlsx",
    )
    parser.add_argument(
        "--feedback-emp-cd",
        default="1778",
        help="Employee code for individual feedback",
    )
    parser.add_argument(
        "--output-dir",
        default="analysis_suite_output",
        help="Output directory for suite artifacts",
    )
    return parser.parse_args()


def resolve_path(base_dir: Path, p: str) -> Path:
    path = Path(p)
    if path.is_absolute():
        return path
    cwd_candidate = path.resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    return (base_dir / path).resolve()


def main() -> None:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent

    attendance = resolve_path(base_dir, args.attendance)
    if not attendance.exists():
        raise FileNotFoundError(f"attendance file not found: {attendance}")

    year = args.year
    month = args.month
    if year is None or month is None:
        auto_year, auto_month = detect_month(attendance)
        year = auto_year if year is None else year
        month = auto_month if month is None else month

    pos_year = resolve_path(base_dir, args.pos_year) if args.pos_year else detect_pos_file(base_dir, year)

    pos_2024 = resolve_path(base_dir, args.pos_2024) if args.pos_2024 else detect_pos_file(base_dir, 2024)
    pos_2025 = resolve_path(base_dir, args.pos_2025) if args.pos_2025 else detect_pos_file(base_dir, 2025)

    if args.output_dir == "analysis_suite_output":
        out_dir = (base_dir / args.output_dir).resolve()
    else:
        out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    tendency_output = out_dir / f"staff_tendency_analysis_{year:04d}-{month:02d}.csv"
    tendency_top20 = out_dir / f"staff_tendency_top20_{year:04d}-{month:02d}.csv"
    corr_dir = out_dir / f"sales_power_correlation_charts_{year:04d}-{month:02d}"
    loss_detail = out_dir / "人員不足_売上ロス分析.csv"
    loss_top50 = out_dir / "売上ロス上位50.csv"
    feedback_prefix = out_dir / f"feedback_{args.feedback_emp_cd}_{year:04d}-{month:02d}"
    product_prefix = out_dir / f"product_feedback_{args.feedback_emp_cd}_{year:04d}-{month:02d}"
    budget_hourly = out_dir / "時間帯予算_日割入力.csv"
    budget_store = out_dir / "店舗別予算配分_日割入力.csv"

    python_executable = sys.executable
    steps: List[Tuple[str, List[str], List[Path]]] = []

    steps.append(
        (
            "staff_tendency_analysis",
            [
                python_executable,
                "staff_tendency_analysis.py",
                "--year",
                str(year),
                "--month",
                str(month),
                "--attendance",
                str(attendance),
                "--pos",
                str(pos_year),
                "--presence-mode",
                "store_stay",
                "--weight-aov",
                "0.15",
                "--weight-set-line2",
                "0.10",
                "--weight-set-qty2",
                "0.05",
                "--weight-sales-power",
                "0.70",
                "--output",
                str(tendency_output),
                "--top-output",
                str(tendency_top20),
            ],
            [tendency_output, tendency_top20],
        )
    )

    steps.append(
        (
            "sales_power_correlation_plot",
            [
                python_executable,
                "sales_power_correlation_plot.py",
                "--year",
                str(year),
                "--month",
                str(month),
                "--attendance",
                str(attendance),
                "--pos",
                str(pos_year),
                "--output-dir",
                str(corr_dir),
                "--min-store-rows",
                "80",
            ],
            [
                corr_dir / "summary.csv",
                corr_dir / "by_store.csv",
                corr_dir / "scatter_total_sales_vs_power.png",
                corr_dir / "scatter_per_staff_sales_vs_power.png",
                corr_dir / "bar_store_correlation_per_staff.png",
            ],
        )
    )

    steps.append(
        (
            "shift_analytics",
            [
                python_executable,
                "shift_analytics.py",
                "--attendance",
                str(attendance),
                "--pos-2024",
                str(pos_2024),
                "--pos-2025",
                str(pos_2025),
                "--output-detail",
                str(loss_detail),
                "--output-top50",
                str(loss_top50),
                "--chunksize",
                "300000",
            ],
            [loss_detail, loss_top50],
        )
    )

    steps.append(
        (
            "staff_feedback_report",
            [
                python_executable,
                "staff_feedback_report.py",
                "--emp-cd",
                str(args.feedback_emp_cd),
                "--year",
                str(year),
                "--month",
                str(month),
                "--attendance",
                str(attendance),
                "--pos",
                str(pos_year),
                "--presence-mode",
                "store_stay",
                "--store-master",
                str(resolve_path(base_dir, "store_master.json")),
                "--output-prefix",
                str(feedback_prefix),
            ],
            [
                Path(f"{feedback_prefix}_summary.csv"),
                Path(f"{feedback_prefix}_store_hour.csv"),
                Path(f"{feedback_prefix}_daily.csv"),
                Path(f"{feedback_prefix}_report.md"),
            ],
        )
    )

    steps.append(
        (
            "staff_product_feedback",
            [
                python_executable,
                "staff_product_feedback.py",
                "--emp-cd",
                str(args.feedback_emp_cd),
                "--year",
                str(year),
                "--month",
                str(month),
                "--attendance",
                str(attendance),
                "--pos",
                str(pos_year),
                "--presence-mode",
                "store_stay",
                "--output-prefix",
                str(product_prefix),
            ],
            [
                Path(f"{product_prefix}_summary.csv"),
                Path(f"{product_prefix}_detail.csv"),
                Path(f"{product_prefix}_top_positive20.csv"),
                Path(f"{product_prefix}_top_negative20.csv"),
                Path(f"{product_prefix}_report.md"),
            ],
        )
    )

    if args.budget_daily_xlsx:
        budget_xlsx = resolve_path(base_dir, args.budget_daily_xlsx)
        steps.append(
            (
                "shift_budget_daily",
                [
                    python_executable,
                    "shift_budget.py",
                    "--attendance",
                    str(attendance),
                    "--pos-files",
                    str(pos_2024),
                    str(pos_2025),
                    "--target-year",
                    str(year),
                    "--target-month",
                    str(month),
                    "--daily-budget-xlsx",
                    str(budget_xlsx),
                    "--daily-budget-sheet",
                    str(args.budget_daily_sheet),
                    "--output",
                    str(budget_hourly),
                    "--output-store-summary",
                    str(budget_store),
                    "--chunksize",
                    "300000",
                ],
                [budget_hourly, budget_store],
            )
        )

    results: List[StepResult] = []
    for step_name, cmd, outputs in steps:
        result = run_step(step_name, cmd, outputs, cwd=base_dir, timeout_sec=1800)
        results.append(result)

    write_manifest(results, out_dir)

    ok_count = sum(1 for r in results if r.ok)
    ng_count = len(results) - ok_count
    print(f"analysis_suite finished: OK={ok_count}, NG={ng_count}, out_dir={out_dir}")
    for r in results:
        print(f"[{'OK' if r.ok else 'NG'}] {r.name}")
        for p in r.output_paths:
            print(f"  - {p} ({'exists' if p.exists() else 'missing'})")


if __name__ == "__main__":
    main()
