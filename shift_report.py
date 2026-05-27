from pathlib import Path
import datetime
import json

import pandas as pd


APP_ROOT = Path(__file__).resolve().parent
FILE_PATH = APP_ROOT / "attendance_summary.csv"

r_file = pd.DataFrame(pd.read_csv(FILE_PATH, encoding="utf-8-sig"))

print(r_file)


Target = datetime.date(2026, 3, 1)
Target_Y = Target.year
Target_M = Target.month
Target_D = Target.day

SHOP = "FUN柏"
TARGET_DATE = str(Target_Y) + "-" + str(Target_M).zfill(2) + "-" + str(Target_D).zfill(2)
print(r_file[(r_file["date"] == TARGET_DATE) & (r_file["store_full_name"] == SHOP)])
with open(APP_ROOT / "store_master.json", encoding="utf-8-sig") as f:
    store_master = json.load(f)
    # If store_master is a dict, access the list of stores; otherwise use it directly
    stores = store_master if isinstance(store_master, list) else store_master.get("stores", [])
    store_names = [store["store_full_name"] for store in stores]
    print(store_names)

for SHOP in store_names:
    Target_Shift = r_file[(r_file["date"] == TARGET_DATE) & (r_file["store_full_name"] == SHOP)]
    print(SHOP)
    Target_Shift_row = Target_Shift[["time_slot", "staff_count", "avg_sales", "index_sum","member_1","member_2","member_3","member_4","member_5","member_6","member_7"]]
    print(Target_Shift_row)
    
    
    
    

low_sales = r_file[r_file["avg_sales"] < 4]
print(low_sales)

SHOP = "FUN柏"
TARGET_DATE = str(Target_Y) + "-" + str(Target_M).zfill(2) + "-" + str(Target_D).zfill(2)


low_sales_filtered = low_sales[(low_sales["date"] == TARGET_DATE) & (low_sales["store_full_name"] == SHOP)]


select_low_sales_filtered = low_sales_filtered[["time_slot", "staff_count", "avg_sales", "index_sum","member_1","member_2","member_3","member_4","member_5","member_6","member_7"]]
select_low_sales_filtered_staffs = low_sales_filtered[["member_1","member_2","member_3","member_4","member_5","member_6","member_7"]]

print(SHOP,TARGET_DATE,select_low_sales_filtered)
print(select_low_sales_filtered_staffs)

