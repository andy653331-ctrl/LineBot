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

# ===== 月查詢函式 =====
def get_stock_info_month(symbol_code, year, month):
    if symbol_code not in symbol_map:
        return "⚠️ 股票代碼錯誤"

    file_name = symbol_map[symbol_code]
    file_path = f"stock_data/{file_name}"

    if not os.path.exists(file_path):
        return f"❌ 找不到 {symbol_code} 的資料"

    try:
        # 修正：讀取 CSV 並還原 Date 欄位
        df = pd.read_csv(file_path, index_col=0)
        df.reset_index(inplace=True)
        df["Date"] = pd.to_datetime(df["Date"])

        df_month = df[(df["Date"].dt.year == int(year)) & (df["Date"].dt.month == int(month))]

        if df_month.empty:
            return f"⚠️ {symbol_code} 在 {year}/{month} 沒有資料"

        avg_close = df_month["Close"].mean()
        avg_change = df_month["Change (%)"].mean()

        return f"📈 {symbol_code} 在 {year}/{month}：\n平均收盤價：{avg_close:.2f} 元\n平均日漲幅：{avg_change:.2f}%"
    except Exception as e:
        print("❗[月查詢錯誤]", e)
        return "❌ 讀取月資料時發生錯誤，請稍後再試"


# ===== 日查詢函式 =====
def get_stock_info_day(symbol_code, year, month, day):
    if symbol_code not in symbol_map:
        return "⚠️ 股票代碼錯誤"

    file_name = symbol_map[symbol_code]
    file_path = f"stock_data/{file_name}"

    if not os.path.exists(file_path):
        return f"❌ 找不到 {symbol_code} 的資料"

    try:
        # 🛠️ 修正：跳過前 3 行（包括欄位名）並手動指定欄位名稱
        df = pd.read_csv(
            file_path,
            skiprows=3,
            names=["Date", "Open", "High", "Low", "Close", "Volume", "Change (%)"]
        )

        df["Date"] = pd.to_datetime(df["Date"], format="%Y-%m-%d", errors="coerce")
        df.dropna(subset=["Date"], inplace=True)  # 避免轉換失敗導致 NaT 資料殘留

        target_date = pd.to_datetime(f"{year}-{month.zfill(2)}-{day.zfill(2)}")
        df_day = df[df["Date"] == target_date]

        if df_day.empty:
            return f"⚠️ {symbol_code} 在 {target_date.date()} 沒有資料（可能是假日或停市）"

        row = df_day.iloc[0]

        return (
            f"📈 {symbol_code} 在 {target_date.date()} 的資料如下：\n"
            f"開盤：{row['Open']:.2f} 元\n"
            f"最高：{row['High']:.2f} 元\n"
            f"最低：{row['Low']:.2f} 元\n"
            f"收盤：{row['Close']:.2f} 元\n"
            f"成交量：{int(row['Volume']):,} 股\n"
            f"漲幅：{row['Change (%)']:.2f}%"
        )

    except Exception as e:
        print("❗[日查詢錯誤]", e)
        return "❌ 讀取每日資料時發生錯誤，請稍後再試"


app = Flask(__name__)

configuration = Configuration(access_token='RCspTXnVJXrV0w/xmBWr5XWxS60aiTE3fHSpCZ5IP3p045Bd2iQADCCZQ/Z5dF7/RnVc2dR+Q/w4hf6xn+sJKE0pOMI5jIZ5TXuRbk2tR1fYC/rQHjsz1FI49fGaAp6n4oEn6WVtEsY9ZAVcZClL+QdB04t89/1O/w1cDnyilFU=')
handler = WebhookHandler('5e7eebcb1aad1b213470a6e0282868de')


@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text.strip()
    msg = msg.replace("　", " ")        # 將全形空格改為半形
    msg = " ".join(msg.split())        # 去除多餘空格
    print("🪵 處理後的訊息：", repr(msg))

    if msg.startswith("查詢"):
        print("✅ 有進入查詢區塊")
        try:
            parts = msg.split()
            symbol = parts[1]
            date_parts = parts[2].split("/")

            print("📦 symbol:", symbol)
            print("📆 date_parts:", date_parts)

            if len(date_parts) == 2:
                year, month = date_parts
                reply_text = get_stock_info_month(symbol, year, month)
            elif len(date_parts) == 3:
                year, month, day = date_parts
                reply_text = get_stock_info_day(symbol, year, month, day)
            else:
                reply_text = "⚠️ 請輸入正確格式：查詢 股票代碼 年/月 或 年/月/日"
        except Exception as e:
            print("❗錯誤訊息：", e)
            reply_text = "❗請輸入格式：查詢 股票代碼 年/月 或 年/月/日（例如：查詢 2330 2023/07 或 查詢 2330 2023/07/20）"
    else:
        print("⚠️ 沒進入查詢區塊，直接回傳原始訊息")
        reply_text = f"你說的是：{msg}"

    # 回傳訊息給 LINE 使用者
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )



if __name__ == "__main__":
    app.run()