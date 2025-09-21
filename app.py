from flask import Flask, request, abort
import os
import re
import pandas as pd
from dotenv import load_dotenv

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# ---------- 基本設定 ----------
load_dotenv()
app = Flask(__name__)

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

DATA_DIR = "stock_data"

# 你已下載並放在 stock_data/ 的 10 檔
STOCK_SYMBOLS = {
    "台積電": "TSM",
    "鴻海": "HNHPF",
    "聯發科": "2454.TW",
    "聯電": "2303.TW",
    "瑞昱": "2379.TW",
    "中華電": "CHT",
    "大立光": "3008.TW",
    "廣達": "2382.TW",
    "光寶科": "2301.TW",
    "緯穎": "6669.TW",
}

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

# ---------- 資料處理工具 ----------

def _standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    # Date 欄
    if "Date" not in df.columns:
        for c in df.columns:
            if c.lower() == "date":
                df = df.rename(columns={c: "Date"})
                break
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    # Close 欄：若沒有 Close，就用 Adj Close；同時確保為數字
    if "Close" not in df.columns:
        for c in df.columns:
            if c.replace(" ", "").lower() in ("adjclose", "close", "close*"):
                df = df.rename(columns={c: "Close"})
                break

    if "Close" not in df.columns:
        raise ValueError("缺少 Close/Adj Close 欄位")

    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df = df.sort_values("Date").dropna(subset=["Date", "Close"]).reset_index(drop=True)
    return df

def load_stock_data(symbol: str) -> pd.DataFrame | None:
    path = os.path.join(DATA_DIR, f"{symbol}.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    return _standardize_columns(df)

def price_on_or_before(df: pd.DataFrame, date: pd.Timestamp):
    """回傳 <= 指定日期的最近一筆 (date, price)。若無則回傳 (None, None)"""
    mask = df["Date"] <= date
    if not mask.any():
        return None, None
    row = df.loc[mask].iloc[-1]
    return pd.to_datetime(row["Date"]), float(row["Close"])

def fmt_price(p: float) -> str:
    return f"{float(p):.2f}"

# ---------- 指令處理 ----------

def process_command(text: str) -> str:
    t = text.strip()
    if t in ("幫助", "help", "說明"):
        return HELP_TEXT

    parts = t.split()
    replies: list[str] = []

    # 多股票同一天：最後一個 token 是日期，前面都是股票名
    if len(parts) >= 2 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[-1]):
        the_date = pd.to_datetime(parts[-1], errors="coerce")
        stocks = parts[:-1]
        for name in stocks:
            sym = STOCK_SYMBOLS.get(name)
            if not sym:
                replies.append(f"⚠ 找不到股票「{name}」")
                continue
            df = load_stock_data(sym)
            if df is None:
                replies.append(f"⚠ 沒有 {name} 的歷史資料檔")
                continue
            d, p = price_on_or_before(df, the_date)
            if d is None:
                replies.append(f"⚠ 找不到 {name} 在 {the_date.date()} 之前的股價")
            else:
                replies.append(f"{name} {d.date()} 收盤價：{fmt_price(p)}")
        return "\n".join(replies) if replies else "⚠ 指令格式錯誤，輸入「幫助」查看"

    # 單檔 + 功能
    if len(parts) >= 1:
        name = parts[0]
        sym = STOCK_SYMBOLS.get(name)
        if not sym:
            return f"⚠ 找不到股票「{name}」，請用以下任一名稱：\n" + "、".join(STOCK_SYMBOLS.keys())

        df = load_stock_data(sym)
        if df is None:
            return f"⚠ 沒有 {name} 的歷史資料檔"

        # 台積電 2023-07-01
        if len(parts) == 2 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[1]):
            the_date = pd.to_datetime(parts[1], errors="coerce")
            d, p = price_on_or_before(df, the_date)
            if d is None:
                return f"⚠ 找不到 {name} 在 {the_date.date()} 之前的股價"
            return f"{name} {d.date()} 收盤價：{fmt_price(p)}"

        # 台積電 平均
        if len(parts) == 2 and parts[1] == "平均":
            price = float(df["Close"].mean())
            return f"{name} 全期間平均收盤價：{fmt_price(price)}"

        # 台積電 平均 2023-01-01 2023-06-30
        if len(parts) == 4 and parts[1] == "平均":
            start = pd.to_datetime(parts[2], errors="coerce")
            end = pd.to_datetime(parts[3], errors="coerce")
            if start > end:
                start, end = end, start
            mask = (df["Date"] >= start) & (df["Date"] <= end)
            sub = df.loc[mask]
            if sub.empty:
                # 找最近靠近區間終點的交易日
                d, p = price_on_or_before(df, end)
                if d is None:
                    return f"⚠ 此區間無資料，且找不到 {end.date()} 之前的交易日"
                return f"⚠ 區間無資料；改報告 {d.date()}：{name} 收盤價 {fmt_price(p)}"
            price = float(sub["Close"].mean())
            return f"{name} {start.date()}~{end.date()} 平均收盤價：{fmt_price(price)}"

        # 台積電 最近10天
        m = re.fullmatch(rf"{re.escape(name)}\s+最近(\d+)\s*天?", t)
        if m:
            n = max(1, int(m.group(1)))
            sub = df.tail(n)
            price = float(sub["Close"].mean())
            return f"{name} 最近{n}個交易日平均收盤價：{fmt_price(price)}"

        # 台積電 最高 / 最低
        if len(parts) == 2 and parts[1] in ("最高", "最低"):
            if parts[1] == "最高":
                p = float(df["Close"].max())
                d = df.loc[df["Close"].idxmax(), "Date"]
            else:
                p = float(df["Close"].min())
                d = df.loc[df["Close"].idxmin(), "Date"]
            return f"{name} 歷史{parts[1]}收盤價：{fmt_price(p)}（{pd.to_datetime(d).date()}）"

    return "⚠ 指令格式錯誤，輸入「幫助」查看說明"

# ---------- LINE Webhook ----------

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
    # 保險：避免文字超長（LINE 5000 字上限）
    if len(reply_text) > 4800:
        reply_text = reply_text[:4800] + "\n…(內容過長已截斷)"
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

if __name__ == "__main__":
    # Render 會注入 PORT（若沒有就用 10000）
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=True)
