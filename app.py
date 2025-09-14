import os
import pandas as pd
from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)

# ===== 股票代碼對應表 =====
symbol_map = {
    "2330": "TSM_TSMC.csv",
    "2317": "HNHPF_Hon Hai.csv",
    "2454": "2454.TW_MediaTek.csv",
    "2303": "2303.TW_UMC.csv",
    "2379": "2379.TW_Realtek.csv",
    "2412": "CHT_Chunghwa Telecom.csv",
    "3008": "3008.TW_Largan.csv",
    "2382": "2382.TW_Quanta.csv",
    "2301": "2301.TW_Lite-On.csv",
    "6669": "6669.TWO_WiWynn.csv"
}

# ===== 從環境變數讀取 Channel Access Token 與 Channel Secret =====
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")

if not CHANNEL_ACCESS_TOKEN or not CHANNEL_SECRET:
    raise ValueError("❌ 環境變數 LINE_CHANNEL_ACCESS_TOKEN 或 LINE_CHANNEL_SECRET 沒有設定好！")

# ✅ 建立 Flask app 與 LINE 設定
app = Flask(__name__)
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)
    return 'OK'


# ===== 通用 CSV 讀取函式 =====
def load_stock_data(symbol_code):
    if symbol_code not in symbol_map:
        return None, f"⚠️ 股票代碼錯誤：{symbol_code}"

    file_name = symbol_map[symbol_code]
    file_path = f"stock_data/{file_name}"

    if not os.path.exists(file_path):
        return None, f"❌ 找不到 {symbol_code} 的資料"

    try:
        df = pd.read_csv(
            file_path,
            skiprows=3,
            names=["Date", "Open", "High", "Low", "Close", "Volume", "Change (%)"]
        )
        df["Date"] = pd.to_datetime(df["Date"], format="%Y-%m-%d", errors="coerce")
        df.dropna(subset=["Date"], inplace=True)
        return df, None
    except Exception as e:
        print("❗[讀取資料錯誤]", e)
        return None, "❌ 讀取股票資料時發生錯誤"


# ===== 查詢函式 =====
def get_stock_info_year(symbol_code, year):
    df, err = load_stock_data(symbol_code)
    if err:
        return err

    df_year = df[df["Date"].dt.year == int(year)]
    if df_year.empty:
        return f"⚠️ {symbol_code} 在 {year} 沒有資料"

    avg_close = df_year["Close"].mean()
    avg_change = df_year["Change (%)"].mean()
    return f"📊 {symbol_code} 在 {year}：\n平均收盤價：{avg_close:.2f} 元\n平均日漲幅：{avg_change:.2f}%"


def get_stock_info_month(symbol_code, year, month):
    df, err = load_stock_data(symbol_code)
    if err:
        return err

    df_month = df[(df["Date"].dt.year == int(year)) & (df["Date"].dt.month == int(month))]
    if df_month.empty:
        return f"⚠️ {symbol_code} 在 {year}/{month} 沒有資料"

    avg_close = df_month["Close"].mean()
    avg_change = df_month["Change (%)"].mean()
    return f"📈 {symbol_code} 在 {year}/{month}：\n平均收盤價：{avg_close:.2f} 元\n平均日漲幅：{avg_change:.2f}%"


def get_stock_info_day(symbol_code, year, month, day):
    df, err = load_stock_data(symbol_code)
    if err:
        return err

    target_date = pd.to_datetime(f"{year}-{month.zfill(2)}-{day.zfill(2)}")
    df_day = df[df["Date"] == target_date]

    if df_day.empty:
        return f"⚠️ {symbol_code} 在 {target_date.date()} 沒有資料（可能是假日或停市）"

    row = df_day.iloc[0]
    return (
        f"📅 {symbol_code} 在 {target_date.date()} 的資料如下：\n"
        f"開盤：{row['Open']:.2f} 元\n"
        f"最高：{row['High']:.2f} 元\n"
        f"最低：{row['Low']:.2f} 元\n"
        f"收盤：{row['Close']:.2f} 元\n"
        f"成交量：{int(row['Volume']):,} 股\n"
        f"漲幅：{row['Change (%)']:.2f}%"
    )


# ===== LINE 事件處理 =====
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text.strip()
    msg = msg.replace("　", " ")  # 全形空格
    msg = " ".join(msg.split())  # 多餘空格
    print("🪵 處理後的訊息：", repr(msg))

    if msg.startswith("查詢"):
        try:
            parts = msg.split()
            symbol = parts[1]
            date_parts = parts[2].split("/")
            print("📦 symbol:", symbol)
            print("📆 date_parts:", date_parts)

            if len(date_parts) == 1:
                year = date_parts[0]
                reply_text = get_stock_info_year(symbol, year)
            elif len(date_parts) == 2:
                year, month = date_parts
                reply_text = get_stock_info_month(symbol, year, month)
            elif len(date_parts) == 3:
                year, month, day = date_parts
                reply_text = get_stock_info_day(symbol, year, month, day)
            else:
                reply_text = "⚠️ 請輸入正確格式：查詢 股票代碼 年 或 年/月 或 年/月/日"
        except Exception as e:
            print("❗錯誤訊息：", e)
            reply_text = "❗請輸入格式：查詢 股票代碼 年 或 年/月 或 年/月/日（例如：查詢 2330 2023 或 查詢 2330 2023/07 或 查詢 2330 2023/07/20）"
    else:
        reply_text = f"你說的是：{msg}"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )


if __name__ == "__main__":
    # 啟動時確認有讀到 Token（只印部分，避免洩漏）
    print("TOKEN 前10碼:", CHANNEL_ACCESS_TOKEN[:10])
    print("SECRET 前5碼:", CHANNEL_SECRET[:5])
    app.run(host="0.0.0.0", port=5000)
