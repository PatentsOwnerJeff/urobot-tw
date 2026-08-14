# 安全政策 Security Policy

## 通報方式

發現安全問題請**不要**開公開 Issue。請寄至 **patentowneroffice@gmail.com**，或使用 GitHub 的 [Private vulnerability reporting](https://github.com/PatentsOwnerJeff/urobot-tw/security/advisories/new)。

我們會在 7 個工作天內回覆。

**若發現 repo 中不慎混入病人資料，請以最高優先級通報。**

## 使用者必讀的已知風險

這是研發階段的原型，部署前請務必了解以下限制：

### 1. `index.pkl` 使用 Python pickle

`ingest.py` 產生的索引以 pickle 序列化。**反序列化來路不明的 pickle 檔可以執行任意程式碼。**

- ✅ 只使用你自己用 `python ingest.py` 產生的 `index.pkl`
- ❌ 不要下載或接受別人給你的 `index.pkl`
- `index.pkl` 已列入 `.gitignore`，不會、也不應該進版控

### 2. Web 介面沒有任何身分驗證或速率限制

`app.py` 是本機開發用的最小介面：

- 預設綁 `127.0.0.1`，**請不要直接暴露到公開網路**
- 沒有帳號、沒有 rate limit、沒有稽核日誌
- 若要在機構內部署，請自行加上反向代理、驗證機制與存取紀錄

### 3. 資料外流面

| 模式 | 使用者問題會送到哪 |
|---|---|
| 純檢索模式 | 不出本機 |
| 本地 Ollama | 不出本機 |
| Claude API | 送到 Anthropic 的伺服器 |

**在含有病人資訊的情境下使用時，請選擇本地 Ollama 或純檢索模式。** 醫療機構部署前應完成資安與個資評估。

### 4. 這不是醫療器材

本系統未經任何主管機關（TFDA、FDA、CE 等）審查或核准，不得作為診斷或治療依據。輸出僅供臨床參考與教育用途，最終決策由醫師負責。

## 支援版本

專案尚在 0.x 階段，僅維護 `main` 分支的最新狀態。
