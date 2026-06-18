import glob

import pandas as pd

for f in sorted(glob.glob(r"datasets/NT/source_data/*.xls*")):
    try:
        xl = pd.ExcelFile(f)
        print("===", f, "| sheets:", xl.sheet_names)
        df = xl.parse(xl.sheet_names[0], header=None, nrows=10)
        print(df.to_string(max_colwidth=22))
        print()
    except Exception as e:
        print("ERR", f, e)
