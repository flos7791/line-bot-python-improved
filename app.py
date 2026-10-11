import os
import sys
from datetime import datetime

# 確保在 Windows 控制台輸出中文不發生編碼錯誤
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from flask import Flask, request, abort
from dotenv import load_dotenv

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
from google import genai
from google.genai import types

# 載入 .env 環境變數
load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')

if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
    print("錯誤: 請在 .env 檔案中填寫 LINE_CHANNEL_SECRET 與 LINE_CHANNEL_ACCESS_TOKEN！")
    sys.exit(1)

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

def get_ai_response(prompt: str) -> str:
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key or gemini_key.strip() == "" or gemini_key == "your_gemini_api_key_here":
        return "⚠️ 尚未在 .env 中填寫 GEMINI_API_KEY！\n請前往 https://aistudio.google.com/app/apikey 免費申請金鑰。"

    # 優先使用自訂模型；失敗時退回預設的 Flash Lite 模型。
    configured_model = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest").strip()
    candidate_models = [configured_model, "gemini-flash-lite-latest"]
    models_to_try = list(dict.fromkeys(model for model in candidate_models if model))

    # 快捷指令：使用者輸入 /model 或問正在使用的模型
    clean_prompt = prompt.strip().lower()
    if clean_prompt in ["/model", "model", "模型", "目前模型", "目前使用的模型", "你是什麼模型"]:
        current_cfg = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
        return (
            f"🤖 【目前 AI 模型資訊】\n"
            f"• 預設模型：{current_cfg}\n"
            f"• 備援模型：{', '.join(models_to_try[1:]) or '無（目前使用預設模型）'}\n"
            f"• 支援自動切換備援模型"
        )

    client = genai.Client(api_key=gemini_key)
    last_error = None

    today_str = datetime.now().strftime('%Y年%m月%d日')

    # 讀取本地專屬知識庫 (若存在)
    kb_content = ""
    kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base.txt")
    if os.path.exists(kb_path):
        try:
            with open(kb_path, "r", encoding="utf-8") as f:
                kb_content = f.read().strip()
        except Exception as e:
            app.logger.warning(f"讀取 knowledge_base.txt 失敗: {e}")

    kb_instruction = f"\n【精確事實知識庫（請優先以此內容為準，具最高優先級）】：\n{kb_content}\n" if kb_content else ""

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=(
                        f"你是一個友善、聰明且樂於助人的 LINE 繁體中文 AI 智慧助理。今天的日期是 {today_str}。\n"
                        f"{kb_instruction}\n"
                        "【核心守則】：\n"
                        "1. 嚴格防範幻覺（No Hallucination）：面對特定個人（如特定學校的某位老師/教授、公司主管）、生僻專有名詞或歷史細節，如果你的資料庫沒有百分之百確切把握，絕不可自行拼湊、嫁接同名人物或虛構其職稱、系所與經歷！\n"
                        "2. 優先參照知識庫：若使用者詢問上述知識庫中已記載的人事物，請務必按照知識庫提供準確資訊。\n"
                        "3. 誠實求真：如果無法確定該人物是否屬於該學校/單位，請誠實說明「資料庫缺乏確切記載」，並引導使用者提供更多線索（例如所屬系所或研究領域），或給出官方查詢管道。\n"
                        "4. 即時資訊：若使用者詢問強烈依賴當天即時資訊的事物（如今日院線電影、今日天氣、股市現價），誠實說明並給出查詢建議。"
                    )
                )
            )
            if response.text and response.text.strip():
                actual_version = getattr(response, 'model_version', model_name)
                print(f"[AI 模型呼叫成功] 模型名稱: {model_name}, 實際版本: {actual_version}")
                return response.text.strip()
        except Exception as e:
            # Avoid logging provider exception details: they can include request data.
            app.logger.warning("Gemini model %s failed (%s); trying fallback.", model_name, type(e).__name__)
            last_error = type(e).__name__

    app.logger.error(f"所有 Gemini 模型呼叫均失敗: {last_error}")
    return "AI 服務目前暫時無法回覆，請稍後再試。"

@app.route("/", methods=['GET'])
def home():
    return "LINE Bot 伺服器運作中！"

@app.route("/callback", methods=['POST'])
def callback():
    # 取得 X-Line-Signature 標頭值以進行簽章驗證
    signature = request.headers.get('X-Line-Signature')
    if not signature:
        app.logger.warning("缺少 X-Line-Signature 標頭")
        abort(400)

    body = request.get_data(as_text=True)

    # Do not log webhook payloads; they contain users' private messages.

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("無效的簽章，請檢查 Channel Secret 是否正確。")
        abort(400)

    return 'OK'

# 處理收到的文字訊息 (使用 Gemini AI 進行智慧回覆)
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text
    app.logger.info("Received text message event.")

    # 取得 AI 智慧回覆
    ai_reply = get_ai_response(user_text)
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=ai_reply[:5000])]
                )
            )
    except Exception as e:
        app.logger.error("Failed to send LINE reply (%s).", type(e).__name__)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"本地伺服器啟動於 http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")

