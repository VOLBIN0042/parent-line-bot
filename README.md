# 家長 FAQ LINE Bot

Python + Flask，LINE Messaging API SDK v3，OpenAI Responses API。

## 本機執行（PowerShell）

建議使用 Python 3.14：

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# 若尚無 .env，才執行下一行；勿覆蓋已填好的金鑰
Copy-Item .env.example .env
.\.venv\Scripts\python.exe app.py
```

若電腦安裝 uv，也可用 `uv pip install --python .venv\Scripts\python.exe -r requirements.txt`。
在 `.env` 填入：

| 變數 | 用途 |
| --- | --- |
| LINE_CHANNEL_ACCESS_TOKEN | Messaging API channel access token |
| LINE_CHANNEL_SECRET | 同一個 channel 的 secret，用來驗證簽章 |
| OPENAI_API_KEY | OpenAI API 金鑰 |
| TEACHER_LINE_ID | 班導 user ID 或班導群組 group ID，並非 LINE 顯示名稱或可搜尋的 LINE ID |
| OPENAI_MODEL | 選填，預設 `gpt-5.5`；可設為 `gpt-5.4-mini` |

現有 `.env` 已保留；`.env` 被 Git 排除，勿把金鑰放進程式或 GitHub。
程式啟動時會檢查四個必要變數；缺漏只顯示欄位名稱。
本機 `/healthz` 可檢查服務；LINE 需要公開 HTTPS 網址，不能直接使用 localhost。

## 訊息流程與客製化

1. `/webhook` 驗證 `X-Line-Signature` 後，讀取文字訊息。
2. 優先比對 `app.py` 的 `SENSITIVE_KEYWORDS`，命中時不呼叫 OpenAI。
3. Push 班導，包含家長 user ID、完整原文與事件時間（Asia/Taipei）。使用事件 ID 產生固定的 LINE retry key，降低重送時重複 Push 的風險。
4. Reply 安撫家長；Push API 成功才寫「已通知班導」，API 成功代表 LINE 接受請求，並不代表老師已讀。Push 失敗仍 Reply 並請家長直接聯絡。
5. 其他訊息比對內嵌 FAQ，直接給標準答案，不花 OpenAI 額度。
6. 無 FAQ 命中時呼叫 Responses API，回覆加上「以下為 AI 回覆」。AI 逾時、出錯或無文字時，改回固定備援訊息。

FAQ 在 `app.py` 的 `FAQ`，AI 使用同一組已知資訊作為內嵌 Skill 的指示。
上線前請將 `[班導手機]`、`[銀行帳號]` 及「你的時程」換成正式資料，並同步更新 `AI_INSTRUCTIONS`。
「緊急聯絡」也含敏感字「緊急」，依優先規則會通知班導，且附上手機欄位。
關鍵字包含比對可能誤判（例如「沒有霸凌」仍通知），也無法辨識所有危機語意。
每則訊息獨立處理，沒有對話記憶；只有非 FAQ、非敏感訊息會傳給 OpenAI，並設 `store=False`，這不等於供應商完全不保留任何資料。

企業客服可改 `SENSITIVE_KEYWORDS` 與 `TEACHER_LINE_ID` 來切換通知觸發詞和接收者；安撫文案、FAQ、AI 指示及校園求助資訊也應一併改成企業內容。

## 部署至 Render 免費 Web Service

1. 將專案推送到你自己的 GitHub repository（不含 `.env`、`.venv`）。
2. 登入 Render，選 **New → Web Service**，連接該 repository。
3. Runtime 選 **Python 3**，Instance Type 選 **Free**。
4. Build Command：`pip install -r requirements.txt`
5. Start Command：`gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 60 'app:create_app()'`
6. Environment 加入四個必要變數及其真實值；另可設 `OPENAI_MODEL=gpt-5.4-mini`。設定 `PYTHON_VERSION=3.14.0`。Health Check Path 設 `/healthz`。
7. 部署完成，確認 `https://你的服務.onrender.com/healthz` 回傳 `{"status":"ok"}`。
8. LINE Developers Console → 同一 Messaging API channel → Webhook settings：填入 `https://你的服務.onrender.com/webhook`，按 **Verify**，再開啟 **Use webhook**。
9. 在 LINE Official Account Manager 關閉會重複回覆的自動回應訊息；加入 Bot 好友後測試「請假」、一般問題、敏感字。

也可使用附帶的 `render.yaml`，在 Render 以 **New → Blueprint** 匯入 repository，依提示填入環境變數。

### 班導 ID 設定

班導個人必須先加入 Bot 好友；目標為群組時，必須允許 Bot 加入群組，並把 Bot 加進班導群組。
接收事件的 `source.userId` 是使用者 ID，`source.groupId` 是群組 ID；從受信任的開發測試或除錯環境取得後填入 `TEACHER_LINE_ID`。請勿新增公開端點洩漏這些 ID。
本程式不會把家長原文或 user ID 寫進應用程式日誌，只會傳送到設定的班導目的地。
確認目的地正確，並確認 LINE 帳號的 Push 權限與額度。

### 免費方案與可靠性限制

Render Free 閒置 15 分鐘會休眠，喚醒可能需約一分鐘，可能造成 LINE webhook 逾時或 reply token 過期。免費方案適合驗證，不適合承擔校園即時危機通知。
OpenAI API 與 LINE Push 額度分別計費／受其方案限制，Render 免費不代表整套服務免費。
目前以同步方式處理，OpenAI 設 15 秒逾時、LINE 請求設逾時；沒有持久化佇列或失敗通知補送機制。
Push 失敗會記錄錯誤類型並告知家長直接聯絡；不自動重送已失敗的通知。
LINE 若重送事件，固定 retry key 可降低重複 Push，但 FAQ／AI 回覆沒有完整的持久化事件去重；AI 可能重複計費。
正式運作建議使用不休眠方案、持久化工作佇列、事件去重與通知重試／監控。

## 測試

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

測試使用真實 SDK 的事件解析與簽章驗證，LINE/OpenAI 網路呼叫以 mock 取代，不會傳送訊息或消耗 API 額度。
實際整合仍需填入有效金鑰，在 LINE 與 Render 環境驗證。

## 設備手冊知識庫

在 LINE 輸入 `GA700 單位設定`、`GA700 o1-03` 或 `查手冊 GA700 自訂單位`。
Bot 先依型號、參數編號與繁簡中文關鍵字查找段落，再交給 AI 整理並附 PDF 頁碼。
缺少相關資料時會請你補充問題。AI 服務暫時無法使用時，會回傳手冊原文節錄與頁碼。
家長 FAQ 仍可照原本方式使用。

要一次加入多份 PDF，將全部可公開的手冊放進同一個資料夾，或將多個檔案路徑一起傳給腳本。
檔名建議包含型號，例如 `GA700技術手冊.pdf`。沒有型號的手冊可以用 `查手冊` 加關鍵字搜尋。

```powershell
uv pip install --python .venv\Scripts\python.exe pymupdf
.\.venv\Scripts\python.exe build_manual_index.py 'D:\手冊資料夾'
```

腳本會從所有輸入重新產生 `manuals.json.gz`，因此保留舊手冊時也要一併傳入。
整份掃描型 PDF 請先做 OCR。含表格或圖片的章節請抽查索引內容是否保留必要條件。
部署時只需提供索引檔。索引內含手冊文字，因此公開儲存庫只適合存放可公開的資料。
更新索引後，推送到 GitHub，再從 Render 的 **Manual Deploy → Deploy latest commit** 部署。

## 官方參考

- [LINE Python SDK v3](https://github.com/line/line-bot-sdk-python)
- [LINE Webhook 與簽章驗證](https://developers.line.biz/en/docs/messaging-api/receiving-messages/)
- [OpenAI Python API 文件](https://developers.openai.com/api/reference/python)
- [Render 免費方案限制](https://render.com/docs/free)
