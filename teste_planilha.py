import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credenciais.json", scope)
client = gspread.authorize(creds)
sheet = client.open_by_key("13yoi6VkBbeCnq0dmn77GRrCf_lcX6ilx2Dy279KusrA").sheet1

df = pd.DataFrame(sheet.get_all_records())
print(df)
