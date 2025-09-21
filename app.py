import os
import pandas as pd
from flask import Flask, request, abort
from datetime import datetime, timedelta

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError

# ---------------- Flask 初始化 ----------------
app = Flask(__name__)

# ---------------- LINE BOT 設定 ----------------
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ---------------- 股票代號 (TW/TWO 台股代碼) ----------------
STOCKS = {
    "台積電": "2330.TW",
    "鴻海": "2317.TW",
    "聯發科": "2454.TW",
    "聯電": "2303.TW",
    "瑞昱": "2379.TW",
    "中華電信": "2412.TW",
    "大立光": "3008.TW",
    "廣達": "2382.TW",
    "光寶科": "2301.TW",
    "緯穎": "6669.TWO"
}

DATA_DIR = "stock_data"

HELP_TEXT = (
    "📊 可用功能指令：\n"
    "1️⃣ 指定日期收盤價：台積電 2023-07-01（遇休市會自動用前一交易日）\n"
    "2️⃣ 平均（全期間）：台積電 平均\n"
    "3️⃣ 區間平均：台積電 平均 2023-01-01 2023-06-30\n"
    "4️⃣ 最近 N 天平均：台積電 最近10天\n"
    "5️⃣ 歷史極值：台積電 最高｜台積電 最低\n"
    "6️⃣ 多股票同一天：台積電 鴻海 聯發科 2023-07-01\n"
    "🆘 輸入「幫助」隨時再看一次"
)

# ---------------- 輔助函式 ----------------
def load_stock_data(symbol):
    """讀取 CSV 並清理成 Date, Close"""
    path = os.path.join(DATA_DIR, f"{symbol}.csv")
    if not os.path.exists(path):
        return None

    df = pd.read_csv(path)
    if "Date" not in df.columns or "Close" not in df.columns:
        return None

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df = df.dropna(subset=["Date", "Close"]).sort_values("Date").reset_index(drop=True)
    return df

def get_nearest_trading_day(df, target_date):
    """若指定日不是交易日，往前找最近交易日"""
    date = target_date
    while date not in df["Date"].values:
        date -= timedelta(days=1)
        if date < df["Date"].min():
            return None
    return date

# ---------------- 指令處理 ----------------
def process_command(text):
    parts = text.strip().split()
    if not parts:
        return HELP_TEXT  # 空輸入 → 回傳幫助

    # 幫助
    if text in ["幫助", "help", "說明"]:
        return HELP_TEXT

    stock_name = parts[0]
    if stock_name not in STOCKS:
        return HELP_TEXT  # 無法識別股票 → 回傳幫助

    symbol = STOCKS[stock_name]
    df = load_stock_data(symbol)
    if df is None:
        return f"⚠️ 沒有 {stock_name} 的歷史資料"

    try:
        # 1️⃣ 指定日期收盤價
        if len(parts) == 2 and "-" in parts[1]:
            date = datetime.strptime(parts[1], "%Y-%m-%d")
            nearest = get_nearest_trading_day(df, date)
            if nearest is None:
                return f"⚠️ 找不到 {stock_name} {parts[1]} 附近的股價紀錄"
            price = float(df.loc[df["Date"] == nearest, "Close"].values[0])
            return f"{stock_name} {nearest.date()} 收盤價：{price:.2f}"

        # 2️⃣ 平均（全期間）
        if len(parts) == 2 and parts[1] == "平均":
            avg = float(df["Close"].mean())
            return f"{stock_name} 全期間平均收盤價：{avg:.2f}"

        # 3️⃣ 區間平均
        if len(parts) == 4 and parts[1] == "平均":
            start = datetime.strptime(parts[2], "%Y-%m-%d")
            end = datetime.strptime(parts[3], "%Y-%m-%d")
            mask = (df["Date"] >= start) & (df["Date"] <= end)
            sub = df.loc[mask]
            if sub.empty:
                return f"⚠️ {stock_name} 在該期間沒有資料"
            avg = float(sub["Close"].mean())
            return f"{stock_name} {parts[2]} ~ {parts[3]} 平均收盤價：{avg:.2f}"

        # 4️⃣ 最近 N 天平均
        if len(parts) == 2 and "最近" in parts[1]:
            n = int(parts[1].replace("最近", "").replace("天", ""))
            sub = df.tail(n)
            if sub.empty:
                return f"⚠️ {stock_name} 最近 {n} 天沒有資料"
            avg = float(sub["Close"].mean())
            return f"{stock_name} 最近 {n} 天平均收盤價：{avg:.2f}"

        # 5️⃣ 歷史極值
        if len(parts) == 2 and parts[1] == "最高":
            high = float(df["Close"].max())
            d = df.loc[df["Close"].idxmax(), "Date"].date()
            return f"{stock_name} 歷史最高收盤價：{high:.2f}（{d}）"

        if len(parts) == 2 and parts[1] == "最低":
            low = float(df["Close"].min())
            d = df.loc[df["Close"].idxmin(), "Date"].date()
            return f"{stock_name} 歷史最低收盤價：{low:.2f}（{d}）"

        # 6️⃣ 多股票同一天
        if len(parts) >= 3 and "-" in parts[-1]:
            date = datetime.strptime(parts[-1], "%Y-%m-%d")
            results = []
            for name in parts[:-1]:
                if name not in STOCKS:
                    results.append(f"{name} 無法識別")
                    continue
                sym = STOCKS[name]
                df2 = load_stock_data(sym)
                if df2 is None:
                    results.append(f"{name} 無資料")
                    continue
                nearest = get_nearest_trading_day(df2, date)
                if nearest is None:
                    results.append(f"{name} {date.date()} 無資料")
                    continue
                price = float(df2.loc[df2["Date"] == nearest, "Close"].values[0])
                results.append(f"{name} {nearest.date()} 收盤價：{price:.2f}")
            return "\n".join(results)

    except Exception as e:
        return f"⚠️ 錯誤：{str(e)}"

    # 其他狀況一律回幫助
    return HELP_TEXT

# ---------------- LINE Webhook ----------------
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()
    reply_text = process_command(user_text)
    if not reply_text:
        reply_text = HELP_TEXT

    # 避免 LINE 5000 字限制
    if len(reply_text) > 4900:
        reply_text = reply_text[:4900] + "\n…(回覆過長已截斷)"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

# ---------------- 啟動 ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
