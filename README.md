# PaperVerifier

深色介面的學術文獻比對工具，使用 Streamlit、Crossref 與 OpenAlex。支援最多 30 篇、作者完整順序比對、候選來源、原文與 Google Scholar 輔助連結。向右滑動清單卡片可露出刪除。

## 啟動

Python 3.12：

```text
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## 免費雲端部署

將此資料夾的內容放在 GitHub 儲存庫根目錄。在 Streamlit Community Cloud 選擇入口 `app.py`、Python 3.12，並在 Advanced settings → Secrets 設定 OpenAlex 金鑰。步驟見 [DEPLOY.md](DEPLOY.md)。

此套件不包含個人憑證或個人化申請檔。`.streamlit/secrets.example.toml` 僅是空白格式示範，不是真實金鑰。

## 驗證

```text
python -m pip install -r requirements-dev.txt
python -m pytest -q
node tests/swipe_interaction.test.cjs
```

Node 是選用的前端事件測試工具，部署不需要它。合成資料只供離線測試。比對一致不等於同儕審查認證，查無結果不代表文獻不存在。

部署前準備：57 項 Python 測試及前端滑動事件檢查通過。尚未完成雲端部署、Linux 安裝或實際手機瀏覽器測試。
