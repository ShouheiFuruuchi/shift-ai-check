from pathlib import Path

import pandas as pd


FILE_PATH = Path(__file__).resolve().parent / "attendance_summary.csv"
DF = pd.read_csv(FILE_PATH, encoding="utf-8-sig")
