# Python LINE Bot 專案

這是一個使用 Python (Flask + `line-bot-sdk` v3 + Google Gemini AI) 打造的智慧 LINE 聊天助理。

---

## 專案結構

```text
hello-python/
├── .env                  # 本機機密設定檔（請勿上傳至 GitHub）
├── .env.example          # 環境變數範本檔
├── .gitignore            # Git 忽略設定
├── app.py                # 主程式（Webhook 與 Gemini AI 處理邏輯）
├── requirements.txt      # Python 相依套件
└── README.md             # 本說明文件
```

---

## 本地快速啟動

### 1. 安裝相依套件
建議使用虛擬環境：
```bash
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 設定環境變數
複製 `.env.example` 為 `.env`，並填入你的 LINE 與 Gemini 金鑰：
```env
LINE_CHANNEL_SECRET=你的_Channel_Secret
LINE_CHANNEL_ACCESS_TOKEN=你的_Channel_Access_Token
GEMINI_API_KEY=你的_Gemini_API_Key
# 可選：指定 Gemini 模型；未設定時使用程式預設值
GEMINI_MODEL=gemini-flash-lite-latest
# 僅本機除錯時設定為 true；正式環境請保持 false
FLASK_DEBUG=false
```
*(可至 [Google AI Studio](https://aistudio.google.com/app/apikey) 免費取得 API 金鑰)*

### 3. 啟動伺服器
```bash
python app.py
```
伺服器將在 `http://127.0.0.1:5000` 運行。正式部署請使用支援 WSGI 的伺服器，並將 `FLASK_DEBUG` 保持為 `false`。


### 4. 透過 ngrok 映射 Webhook
```bash
ngrok http 5000
```
取得提供的 HTTPS 網址（例如 `https://xxxx.ngrok-free.app`），將 Webhook URL 設為：
`https://xxxx.ngrok-free.app/callback`
至 LINE Developers Console 進行 Verify 並開啟 Webhook！
