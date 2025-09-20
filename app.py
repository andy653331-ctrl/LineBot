from flask import Flask, request, abort
import requests
import os, re, csv
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime
import yfinance as yf   # ✅ 即時股價

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# 載入本地 .env（Render 會用 Environment Variables）
load_dotenv()

app = Flask(__name__)

# === 環境變數 ===
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "").strip()
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

print(f"[DEBUG] LINE_CHANNEL_SECRET set? {'✅' if bool(CHANNEL_SECRET) else '❌'}")
print(f"[DEBUG] LINE_CHANNEL_ACCESS_TOKEN 前10碼 = {CHANNEL_ACCESS_TOKEN[:10] if CHANNEL_ACCESS_TOKEN else '❌ None'}")
print(f"[DEBUG] OPENROUTER_API_KEY 前10碼 = {OPENROUTER_API_KEY[:10] if OPENROUTER_API_KEY else '❌ None'}")

if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
    raise ValueError("❌ 請確認 LINE_CHANNEL_SECRET 與 LINE_CHANNEL_ACCESS_TOKEN 已設定")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# === DeepSeek (OpenRouter) ===
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# === 本地股價資料 ===
DATA_DIR = Path(__file__).parent / "stock_data"

# 股票別名 → Yahoo Finance 代號
STOCK_ALIASES = {
    "2330": "TSM",
    "台積電": "TSM",
    "tsmc": "TSM",

    "鴻海": "HNHPF",
    "hon hai": "HNHPF",

    "2454": "2454.TW",
    "聯發科": "2454.TW",
    "mediatek": "2454.TW",

    "2303": "2303.TW",
    "聯電": "2303.TW",
    "umc": "2303.TW",

    "2379": "2379.TW",
    "瑞昱": "2379.TW",
    "realtek": "2379.TW",

    "cht": "CHT",
    "中華電信": "CHT",

    "3008": "3008.TW",
    "大立光": "3008.TW",
    "largan": "3008.TW",

    "2382": "2382.TW",
    "廣達": "2382.TW",
    "quanta": "2382.TW",

    "2301": "2301.TW",
    "光寶科": "2301.TW",
    "lite-on": "2301.TW",

    "6669": "6669.TWO",
    "緯穎": "6669.TWO",
    "wiwynn": "6669.TWO"
}

# === 工具函式 ===
def norm_date(txt: str) -> str | None:
    if any(w in txt for w in ["今天", "今日", "最新"]):
        return None
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", txt)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
    except:
        return None

def parse_stock_query(user_text: str) -> tuple[str | None, str | None]:
    text = user_text.lower().strip()
    code = None
    m = re.search(r"\b(\d{4})\b", text)
    if m: code = m.group(1)
    for alias, real in STOCK_ALIASES.items():
        if alias.lower() in text:
            code = real
            break
    d = norm_date(user_text)
    return code, d

def read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def pick_field(row: dict, candidates: list[str]) -> str | None:
    for c in candidates:
        for k in row.keys():
            if k.lower() == c.lower():
                return row[k]
    return None

def get_stock_price_local(code: str, on_date: str | None) -> str:
    path = DATA_DIR / f"{code}.csv"
    if not path.exists():
        return f"⚠️ 找不到 {code} 的歷史資料檔"
    rows = read_csv_rows(path)
    if not rows: return f"⚠️ {code} 的資料檔是空的"
    if on_date:
        for r in reversed(rows):
            if on_date in (pick_field(r, ["Date", "日期"]) or "").replace("/", "-"):
                return f"{code} {on_date} 收盤價 {pick_field(r, ['Close','收盤'])} 元"
        return f"⚠️ 找不到 {code} 在 {on_date} 的資料"
    last = rows[-1]
    return f"{code} 最新歷史收盤 {pick_field(last,['Close','收盤'])} 元（日期 {pick_field(last,['Date','日期'])}）"

def get_realtime_stock_price(ticker: str) -> str:
    try:
        stock = yf.Ticker(ticker)
        data = stock.history(period="1d")
        if data.empty:
            return f"⚠️ 找不到 {ticker} 的即時資料"
        last_price = data["Close"].iloc[-1]
        return f"{ticker} 即時收盤價：{last_price:.2f}"
    except Exception as e:
        return f"⚠️ 查詢 {ticker} 發生錯誤：{e}"

def call_deepseek(user_message: str) -> str:
    if not OPENROUTER_API_KEY:
        return "⚠️ 沒有設定 AI 金鑰"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek/deepseek-chat-v3.1:free",
        "messages": [
            {"role": "system", "content": "你是智慧助理。若使用者詢問股價，請盡量簡短回答。"},
            {"role": "user", "content": user_message}
        ]
    }
    try:
        resp = requests.post(OPENROUTER_URL, headers=headers, json=data, timeout=30)
        js = resp.json()
        if "choices" in js:
            return js["choices"][0]["message"]["content"]
        return f"⚠️ AI 錯誤: {js}"
    except Exception as e:
        return f"⚠️ 呼叫 AI 發生錯誤: {e}"

# === LINE Webhook ===
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()
    code, on_date = parse_stock_query(user_text)
    if code:
        if on_date is None:  # 沒有日期 → 即時資料
            reply_text = get_realtime_stock_price(code)
        else:                # 有日期 → 歷史 CSV
            reply_text = get_stock_price_local(code, on_date)
    else:
        reply_text = call_deepseek(user_text)

    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=True)
