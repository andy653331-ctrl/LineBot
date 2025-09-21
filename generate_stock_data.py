import yfinance as yf
import os

# 股票清單
stocks = {
    "TSMC": "TSM",
    "Hon Hai": "HNHPF",
    "MediaTek": "2454.TW",
    "UMC": "2303.TW",
    "Realtek": "2379.TW",
    "Chunghwa Telecom": "CHT",
    "Largan": "3008.TW",
    "Quanta": "2382.TW",
    "Lite-On": "2301.TW",
    "WiWynn": "6669.TW"
}

# 日期範圍
start_date = "2023-01-01"
end_date = "2024-12-31"

# 儲存資料夾
os.makedirs("stock_data", exist_ok=True)

for name, symbol in stocks.items():
    print(f"📈 Fetching {name} ({symbol})...")
    try:
        df = yf.download(symbol, start=start_date, end=end_date)

        # 把 index(Date) 變成欄位
        df.reset_index(inplace=True)

        # 存檔：檔名用代號
        filename = f"stock_data/{symbol}.csv"
        df.to_csv(filename, index=False)

        print(f"✅ Saved to {filename}")
    except Exception as e:
        print(f"❌ Failed to fetch {name} ({symbol}): {e}")
