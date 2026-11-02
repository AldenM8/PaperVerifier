# PaperVerifier 雲端部署

目標：Streamlit Community Cloud 免費方案。此套件尚未發布到外網。

## 上傳 GitHub

建立新的 GitHub 儲存庫（個人測試可先使用私人儲存庫），將本套件解壓後的內容放在儲存庫根目錄。`app.py`、`requirements.txt`、`.streamlit/` 和 `swipe_component/` 必須一併上傳。不要上傳本機環境、API 金鑰或個人化申請檔。

## 部署設定

1. 前往 https://share.streamlit.io ，使用 GitHub 帳號登入並授權存取該儲存庫。
2. 按 Create app，選取儲存庫與分支（通常為 main）。
3. Main file path 填 `app.py`。
4. Advanced settings 選 Python **3.12**。
5. 在 Secrets 填入以下設定；請自行以真實金鑰替換空字串：

```toml
OPENALEX_API_KEY = ""
CROSSREF_MAILTO = ""
```

金鑰只填在 Streamlit 的私密設定，不放在 GitHub 或聊天訊息。OpenAlex 金鑰必須已在信箱點擊啟用。未設定金鑰時仍會嘗試匿名查詢，可能遇到 429。

6. 部署後，在手機開啟平台實際產生的 `https://名稱.streamlit.app` 網址。

## 手機測試

- 先測試 API 連線。
- 填入一篇文獻，新增作者，再加入清單。
- 向右滑動卡片後點「刪除」；重新加入再驗證。
- 查看結果、切換候選、開啟原文。
- 個別瀏覽器的清單存在各自工作階段，重新整理或服務重啟可能清空。

網頁使用 HTTPS。免費雲端主機可能有啟動等待與資源限制；API 額度與主機免費額度是分開計算。若只供自己測試，可在平台分享／存取設定限制使用者。

## 驗證命令

```text
python -m pip install -r requirements-dev.txt
python -m pytest -q
node tests/swipe_interaction.test.cjs
```

Node 僅供選用的前端事件測試，部署本身不需要。部署固定使用已在本機測試的 Streamlit 與 requests 版本。

官方步驟：https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
私密設定：https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
