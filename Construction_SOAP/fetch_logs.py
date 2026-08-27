import gspread
import pandas as pd

# 1. Authenticate with Google using your credentials file
gc = gspread.service_account(filename="credentials.json")

# 2. Open the spreadsheet by its exact name
SHEET_NAME = "SOAP_Daily_Logs"
sheet = gc.open(SHEET_NAME).sheet1

# 3. Pull all records into a Pandas DataFrame
records = sheet.get_all_records()
df = pd.DataFrame(records)

# 4. Display the retrieved data
print("\n=== SUCCESS: CONNECTED TO GOOGLE SHEETS ===")
print(f"Total Daily Logs Retrieved: {len(df)}")
print("-" * 50)
print(df.head())
print("-" * 50)