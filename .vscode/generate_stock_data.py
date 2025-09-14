import yfinance as yf
import pandas as pd
import os

stock_symbols = {
    "TSMC": "TSM",
    "Hon Hai": "HNHPF",
    "MediaTek": "2454.TW",
    "UMC": "2303.TW",
    "Realtek": "2379.TW",
    "Chunghwa Telecom": "CHT",
    "Largan": "3008.TW",
    "Quanta": "2382.TW",
    "Lite-On": "2301.TW",
    "WiWynn": "6669.TWO"
}

start_date = "2023-01-01"
end_date = "2024-12-31"

os.makedirs("stock_data", exist_ok=True)

for name, symbol in stock_symbols.items():
    print(f"📈 Fetching {name} ({symbol})...")
    df = yf.download(symbol, start=start_date, end=end_date)
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
    df['Change (%)'] = df['Close'].pct_change() * 100
    df.dropna(inplace=True)
    df.to_csv(f"stock_data/{symbol}_{name}.csv")
    print(f"✅ Saved to stock_data/{symbol}_{name}.csv")
