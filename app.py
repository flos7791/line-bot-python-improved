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

def get_ai_response(prompt: str, use_search: bool = True) -> str:
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

    kb_instruction = f"\n【專屬背景資料（可能未更新；涉及可搜尋的事實時，請用可靠網路來源重新查證，不可盲目視為最新）】：\n{kb_content}\n" if kb_content else ""

    search_enabled = use_search and os.getenv("GEMINI_GOOGLE_SEARCH", "true").strip().lower() in {"1", "true", "yes", "on"}

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())] if search_enabled else None,
                    system_instruction=(
                        f"你是一個友善、聰明且樂於助人的 LINE 繁體中文 AI 智慧助理。今天的日期是 {today_str}。\n"
                        f"{kb_instruction}\n"
                        "【核心守則】：\n"
                        "1. 嚴格防範幻覺（No Hallucination）：面對特定個人（如特定學校的某位老師/教授、公司主管）、生僻專有名詞或歷史細節，如果你的資料庫沒有百分之百確切把握，絕不可自行拼湊、嫁接同名人物或虛構其職稱、系所與經歷！\n"
                        "2. 專屬知識庫是背景參考，不保證最新；可搜尋的事實要查證。若資料庫與可信的官方或近期來源衝突，指出資料庫可能過時並以查證結果回答。\n"
                        "3. 誠實求真：如果搜尋後仍無法確認人物、職稱或經歷，明確說明不確定，不可拼湊同名人物資訊。\n"
                        "4. 網路查證：需要可搜尋的事實、冷門資訊、人物資料或最新資訊時，使用 Google Search 查證；優先採用官方或原始來源，來源互相矛盾時要說明，不要把推測寫成事實。\n"
                        "5. 即時資訊：需要即時資料時，必須以搜尋結果為準；若搜尋沒有找到可靠來源，明確說無法確認。"
                    )
                )
            )
            if response.text and response.text.strip():
                actual_version = getattr(response, 'model_version', model_name)
                print(f"[AI 模型呼叫成功] 模型名稱: {model_name}, 實際版本: {actual_version}")
                answer = response.text.strip()
                sources = []
                for candidate in getattr(response, "candidates", None) or []:
                    metadata = getattr(candidate, "grounding_metadata", None)
                    for chunk in getattr(metadata, "grounding_chunks", None) or []:
                        web_source = getattr(chunk, "web", None)
                        url = getattr(web_source, "uri", None)
                        title = getattr(web_source, "title", None) or url
                        if url and all(existing_url != url for _, existing_url in sources):
                            sources.append((title, url))
                if sources:
                    answer += "\n\n📚 參考來源\n" + "\n".join(
                        f"• {title}: {url}" for title, url in sources[:5]
                    )
                return answer
        except Exception as e:
            # Avoid logging provider exception details: they can include request data.
            app.logger.warning("Gemini model %s failed (%s); trying fallback.", model_name, type(e).__name__)
            last_error = type(e).__name__

    app.logger.error(f"所有 Gemini 模型呼叫均失敗: {last_error}")
    return "AI 服務目前暫時無法回覆，請稍後再試。"


COMMAND_HELP = (
    "💡 快速指令\n"
    "翻 <文字>：翻譯成繁體中文；也可用「翻英文 <文字>」指定目標語言\n"
    "改 <文字>：修正文法並讓表達更自然\n"
    "解 <主題>：用白話說明並舉一個例子\n"
    "考 <主題>：出一題小測驗，先不要公布答案\n"
    "/help：顯示這份指令清單\n\n"
    "直接傳送其他訊息，仍可和我一般聊天。"
)


def prepare_message(user_text: str) -> tuple[str, str | None, bool]:
    """Return the Gemini prompt, optional direct reply, and search preference."""
    text = user_text.strip()
    normalized_text = text.strip("\"'`“”‘’ ").lower()
    help_phrases = {
        "/help", "help", "指令", "幫助", "功能", "可用指令", "有哪些指令",
        "我可以用哪些指令", "你有哪些功能", "你能做什麼", "功能列表",
        "commands", "command list", "what can you do", "what commands can i use",
    }
    if normalized_text in help_phrases:
        return "", COMMAND_HELP, False

    parts = text.split(maxsplit=1)
    command = parts[0].lower() if parts else ""
    argument = parts[1].strip() if len(parts) > 1 else ""
    commands = {
        "翻": "translate", "翻譯": "translate",
        "改": "polish", "潤飾": "polish", "修改": "polish",
        "解": "explain", "解釋": "explain",
        "考": "quiz", "出題": "quiz", "小測驗": "quiz",
    }
    action = commands.get(command)
    target_languages = {"翻英文": "英文", "翻日文": "日文", "翻韓文": "韓文"}
    if command in target_languages:
        action = "translate"
        argument = f"{target_languages[command]} {argument}".strip()
    if not action:
        return user_text, None, True
    if not argument:
        usage = {
            "translate": "用法：翻 <文字>（例如：翻 Good morning）",
            "polish": "用法：改 <文字>（例如：改 我昨天有去看電影了）",
            "explain": "用法：解 <主題>（例如：解 什麼是黑洞）",
            "quiz": "用法：考 <主題>（例如：考 台灣地理）",
        }
        return "", usage[action], False

    instructions = {
        "translate": "請翻譯以下文字。若文字以「英文」「日文」「韓文」等語言名稱開頭，翻譯成該語言；否則翻譯成自然的繁體中文。只給翻譯結果。\n\n",
        "polish": "請修正文法、錯字並讓以下文字更自然清楚，保留原意與語氣。只輸出修改後文字。\n\n",
        "explain": "請用繁體中文白話解釋以下主題，控制在容易閱讀的長度，並附上一個具體例子。\n\n",
        "quiz": "請針對以下主題出一道簡短小測驗。先只給題目，不要公布答案，等使用者回答後再判斷並解釋。\n\n",
    }
    return instructions[action] + argument, None, action in {"explain", "quiz"}

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
        app.logger.info("Received valid LINE webhook.")
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

    prompt, direct_reply, use_search = prepare_message(user_text)
    ai_reply = direct_reply if direct_reply is not None else get_ai_response(prompt, use_search=use_search)
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=ai_reply[:5000])]
                )
            )
        app.logger.info("LINE reply sent successfully.")
    except Exception as e:
        app.logger.error("Failed to send LINE reply (%s).", type(e).__name__)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"本地伺服器啟動於 http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")

