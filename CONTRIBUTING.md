# 貢獻指南 Contributing to UROBOT TW

歡迎泌尿科臨床、NLP、資料工程領域的夥伴參與。這份文件說明怎麼開始、以及本專案在**醫療正確性**與**著作權**上的特殊要求。

---

## 開始之前

```bash
git clone https://github.com/PatentsOwnerJeff/urobot-tw.git
cd urobot-tw
pip install -r requirements-dev.txt
python ingest.py            # 建索引
python -m pytest -q         # 跑測試
python app.py               # → http://127.0.0.1:5000
```

不需要任何 API key —— 沒有設定時系統會自動降級成純檢索模式。

## 貢獻類型

### 1. 臨床語料（最需要）

語料是這個專案的核心資產。放進 `corpus/*.jsonl`，每行一個段落：

```json
{"id": "nhi-tur-01", "source": "健保署醫療服務給付項目及支付標準（114/05/01生效）", "section": "泌尿科手術／經尿道攝護腺刮除術", "text": "……", "summary_zh": "（原文為英文時必填）"}
```

| 欄位 | 必填 | 說明 |
|---|---|---|
| `id` | ✅ | 全域唯一，格式 `來源前綴-主題-序號`（如 `eau-stone-12`） |
| `source` | ✅ | 具體到版本或生效日期，不要只寫「EAU 指引」 |
| `section` | ✅ | 章節，會一起進索引，影響檢索品質 |
| `text` | ✅ | 段落原文 |
| `summary_zh` | 原文非中文時必填 | 繁中摘要，中文提問靠它命中英文段落 |

**規則：**

- 一段一個概念。太長會稀釋 BM25 分數，太短會失去上下文
- **建議長度 200–1600 字元**（與 `build_corpus.py` 的預設切段參數一致；中文一字約一字元，英文原文則明顯較長）
- `id` 不可與既有語料衝突，CI 會擋
- **新增主題時必須同時更新 [`scope.json`](scope.json)**：把主題從 `gaps` 移到
  `covered`，`requires` 填語料的 id 前綴。漏掉這步的話語料進去了系統還是會拒答，
  而且 `tests/test_scope.py` 會擋下 PR
- 送出前跑 `python ingest.py && python -m pytest -q`

**關於 `scope.json`：** 這個檔案明示宣告系統涵蓋哪些主題、已知缺哪些。宣告之外的
主題一律拒答，不拿字面沾邊的段落硬湊。範圍是人工維護的——實測過以 BM25 分數與
IDF 加權詞彙覆蓋率自動判斷，兩者在未涵蓋主題上的分數反而比已涵蓋主題高，因為
jieba 會把未收錄的醫學複合詞拆成語料裡都有的字。細節見該檔開頭的說明。

每個 `gaps` 項目都必須有 `fix` 欄位（需要哪本指引、下載網址、id 前綴、輸出路徑），
系統會把它渲染成使用者可直接複製的建置步驟。只說「沒有資料」對使用者是死路。

### 2. 考題（`exams/*.jsonl`）

```json
{"id": "q13", "question": "……", "options": {"A": "…", "B": "…", "C": "…", "D": "…"}, "answer": "A", "evidence": ["stone-01"]}
```

`evidence` 填正解所依據的語料段落 id，這樣沒有 LLM 時也能評測檢索命中率。

### 3. 程式碼

- 保持精簡。這個 repo 刻意維持小巧、無框架、易稽核
- 新增功能請附測試
- 不要在沒有討論的情況下引入重量級相依套件（torch、langchain 等）

---

## ⚠️ 著作權：務必先讀

**不要把你沒有散布權的內容 commit 進來。**

| 來源 | 可否放進 repo |
|---|---|
| 健保署 / 政府開放資料 | ✅ 可以（政府資料開放授權條款第1版，須註明出處） |
| 自行撰寫的繁中摘要、衛教說明 | ✅ 可以 |
| EAU / AUA / TUA 等學會指引原文 | ❌ 不可以，請改用 `build_corpus.py` 讓使用者自行建置 |
| 教科書、期刊論文全文 | ❌ 不可以 |
| 醫院內部規範、病歷 | ❌ 絕對不可以 |

`corpus/eau_*.jsonl` 已列入 `.gitignore`，請不要用 `git add -f` 繞過。

**任何情況下都不要提交含病人資料的內容**，即使你認為已經去識別化。

---

## 醫療正確性

這是臨床決策輔助工具，錯誤的語料可能造成真實傷害。

- 語料 PR 需經**具泌尿科臨床背景的維護者**審閱後才會合併
- 不確定的內容請在 PR 中明確標示，不要猜
- 涉及劑量、適應症、禁忌症的內容，請附上來源的頁碼或章節編號
- 發現既有語料有誤，請直接開 Issue 標記 `correctness`，這類 Issue 優先處理

## 送 PR

1. Fork → 開新分支（`feat/xxx`、`corpus/xxx`、`fix/xxx`）
2. Commit message 用 [Conventional Commits](https://www.conventionalcommits.org/)：`feat:` `fix:` `docs:` `corpus:` `test:`
3. 確認 `python -m pytest -q` 全綠
4. 開 PR，填完模板

第一次貢獻的話，**commit 用的 email 要是你 GitHub 帳號已驗證的信箱**，否則你不會出現在 Contributors 名單上。

## 授權

送出 PR 即表示你同意你的貢獻以 [Apache-2.0](LICENSE) 授權釋出。

UROBOT® 為英普瑞斯股份有限公司之註冊商標（中華民國註冊第 02509814 號），**不在 Apache-2.0 授權範圍內**。你可以自由使用、修改、散布程式碼，但不得將 UROBOT® 用於自己的產品名稱或商標。

## 行為準則

參與本專案即表示你同意遵守 [行為準則](CODE_OF_CONDUCT.md)。
