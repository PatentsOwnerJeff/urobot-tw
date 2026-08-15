# UROBOT® TW — 開源台灣泌尿科臨床決策輔助 AI

[![CI](https://github.com/PatentsOwnerJeff/urobot-tw/actions/workflows/ci.yml/badge.svg)](https://github.com/PatentsOwnerJeff/urobot-tw/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

> UROBOT® 為英普瑞斯股份有限公司之註冊商標（中華民國註冊第 02509814 號，第 10、44 類）。

**Open-source Taiwanese urology clinical decision-support AI.** RAG 架構：檢索泌尿科指引 → 大模型作答 → 逐點標註出處。與德國 DKFZ [UroBot](https://github.com/DBO-DKFZ/UroBot)（EAU 指引＋GPT-4o，專科考題 88.4%）同架構，差異化：繁體中文、台灣臨床實務、健保給付規範、**不綁定任何一家模型供應商**。

## 特色

- **可插拔模型層**：Claude API（預設推薦）／ Ollama 本地開源模型（免費、資料不出門）／純檢索模式（免任何 key）
- **中英跨語檢索**：英文指引每段附繁中摘要一起建索引，再加上[中英醫學詞對照表](glossary_zh_en.json)做查詢擴展，中文提問可命中英文指引
- **台灣健保給付規範**：[`build_nhi_corpus.py`](build_nhi_corpus.py) 直接從政府開放資料建置給付條件語料 —— 這是國外系統沒有的
- **內建評測系統**：`eval.py` 對標 UroBot 的考題正確率（RoCA）評測法，結果可存檔比較
- **語料即插即用**：新增 jsonl 檔重跑 `ingest.py` 即擴充知識庫

## 快速開始

```bash
pip install -r requirements.txt
python ingest.py     # 建索引（488 段語料已隨 repo 附上）
python app.py        # → http://127.0.0.1:5000
```

**不需要任何 API key 就能跑。** Clone 下來即附 488 段可合法散布的語料（健保診療項目、藥品、給付規定條文與示範指引），純檢索模式會回傳最相關的段落與出處。設定模型後才會有整合式回答。

選擇模型（三選一）：

```bash
# A. Claude API（推薦）
pip install anthropic && export ANTHROPIC_API_KEY=sk-ant-...

# B. 本地 Ollama（完全免費，適合醫院內部署，資料不出門）
#    先安裝 https://ollama.com 並 ollama pull llama3.1
export UROBOT_OLLAMA_MODEL=llama3.1

# C. 什麼都不設 → 純檢索模式（回傳指引段落＋出處）
```

## 建置語料

Clone 下來預設只有 10 段示範語料。要讓系統真正好用，請自行建置：

### 台灣健保給付規範（可直接執行，資料可合法散布）

```bash
python build_nhi_corpus.py --inspect     # 先看資料長什麼樣、欄位對不對得上
python build_nhi_corpus.py               # 診療項目與藥品品項
pip install pypdf && python build_nhi_rules.py   # 藥品給付規定條文（最有價值）
python ingest.py
```

**`build_nhi_rules.py` 是這批工具裡最值得跑的一支。** 用藥品項檔只有章節編號（如 5.2.2.1），沒有條文；而條文才是臨床決策要的東西：

> 5.2.2.1 Finasteride；dutasteride：**限前列腺增生且有阻塞症狀**…**前列腺大於 30mL 或最大尿流速（Qmax）小於 15 mL/sec** 之病人方可使用。

泌尿科現行品項共用到 18 個章節，涵蓋 OAB（1.6.3）、ED（2.8.2）、BPH（5.2.2.1）、GnRH（5.5.1）、抗雄性素（9.39–9.94）、尿路抗生素（10.1、10.8.2）。

資料來自[政府資料開放平臺](https://data.gov.tw/dataset/9405)，授權為政府資料開放授權條款第 1 版，可再散布與衍生。出處與授權標示見 [NOTICE.md](NOTICE.md)。

**兩個必須知道的行為：**

- **預設只收現行有效的項目。** 健保開放資料是歷史檔，實測泌尿科藥品 4,115 筆中有 3,396 筆（83%）給付期間已過期，最舊的失效於民國 98 年。把失效價格當現行資訊提供給臨床端是真實風險，故一律排除。`--include-expired` 可覆寫，但產出的語料不得作為現行給付依據。
- **藥品按成分聚合。** 同成分不同廠牌會產生大量近乎相同的段落（719 個品項只對應 69 種成分），灌爆 BM25 分數並擠掉臨床指引。聚合後每個成分一段，附品項數、劑型與支付價區間。

篩選方式：藥品**只認 ATC 代碼**（G04、G03B、L02AE、L02BB、J01MB、J01XE）—— 藥品中文名是行銷名稱，比對它只會製造誤判；診療項目則比對中英文名稱關鍵字，英文一律加字界以避免 `Serenal`→`renal`、`TURPENTINE`→`TURP` 這類子字串誤判。

**篩選規則是啟發式的，必然有誤差**，語料產生後請人工抽查，規則在 `build_nhi_corpus.py` 頂端可自行調整。

⚠️ 健保語料的內容**完全來自健保署資料集欄位**，本專案未加入任何自行撰寫的適應症、療效或用法敘述。給付規定反映的是保險給付範圍，不等於醫療上的最佳做法。

### 學會指引（需自行取得，不隨 repo 散布）

EAU / AUA / TUA 指引的著作權屬原機構，本專案**不散布原文**，只提供轉換工具：

```bash
pip install pypdf
# 自行從 https://uroweb.org/guidelines 下載 PDF
python build_corpus.py ~/Downloads/EAU-Urolithiasis-2025.pdf \
    --prefix eau-stone \
    --source "EAU Guidelines on Urolithiasis 2025" \
    --out corpus/eau_urolithiasis.jsonl

python build_corpus.py --translate corpus/eau_urolithiasis.jsonl  # 補繁中摘要
python ingest.py
```

`corpus/eau_*.jsonl` 已列入 `.gitignore`，請勿提交。詳見 [CONTRIBUTING.md](CONTRIBUTING.md) 的著作權章節。

## 檢索品質

`benchmarks/retrieval.jsonl` 收錄 10 題真實臨床會問的問題，涵蓋「中文病名 vs 條文用語不同」「商品名 vs 學名」等實際難點。目前 **Top-1 10/10**。

CI 每次都會跑，門檻設在 Top-1 ≥ 7/10 —— 排序退化不會拋例外，只會安靜地把答案變爛，所以必須用測試擋住。

```bash
python -m pytest tests/test_retrieval_quality.py -v
```

調校紀錄（`ingest.py` 頂端有完整說明）：BM25 預設 `b=0.75` 對短文件過於慷慨，健保診療項目條目只有 30–40 個詞，給付規定條文有 300+ 詞，結果問「攝護腺肥大用藥給付條件」第一名會是「前列腺按摩」。改為 `b=0.3`、`k1=1.2` 後 Top-1 由 6/10 升至 8/10，再補上商品名→學名對照後達 10/10。

## 評測

```bash
python eval.py                                   # 內建 12 題示範考題
python eval.py exams/你的題庫.jsonl               # 泌尿專科甄審考題轉成同格式即可評測
python eval.py --out results/claude.json         # 存檔，供跨模型比較
python eval.py --compare results/*.json          # 比較不同模型／設定的成績
```

題目格式：`{"id","question","options":{"A"..."D"},"answer","evidence":[相關段落id]}`

有 LLM 時算答題正確率（RoCA），沒有 LLM 時算檢索命中率 —— 後者不需任何 API key，CI 在每個 PR 與 main 的 push 都會跑。

## 語料庫

| 檔案 | 內容 | 段數 | 可否公開散布 |
|---|---|---|---|
| `demo_guidelines.jsonl` | 繁中示範語料 | 10 | ✅ 已隨 repo 附上 |
| `nhi_procedures_urology.jsonl` | 健保診療項目給付 | 391 | ✅ 政府開放資料 |
| `nhi_drugs_urology.jsonl` | 健保用藥（按成分聚合） | 69 | ✅ 政府開放資料 |
| `nhi_drug_rules.jsonl` | **藥品給付規定條文** | 18 | ✅ 健保署公告 |
| `eau_*.jsonl` | EAU 指引 | 166 | ❌ 著作權屬 EAU，需自行建置 |

⚠️ **著作權注意**：指引語料著作權屬原機構（EAU/TUA 等）。公開 repo 預設排除 `eau_*.jsonl`，使用者需在本機自行建置，或待取得機構授權後散布。程式碼本身為 Apache-2.0，第三方資料來源與授權標示見 [NOTICE.md](NOTICE.md)。

⚠️ **給付規定 ≠ 臨床指引**：健保給付條件反映的是保險給付範圍，不等於醫療上的最佳做法。兩者在語料中以 `source` 欄位明確區分。

## 架構

```
corpus/*.jsonl ─┬─ build_corpus.py      （學會指引 PDF → jsonl，使用者自行建置）
                ├─ build_nhi_corpus.py  （健保開放資料 → 診療項目與藥品）
                └─ build_nhi_rules.py   （健保署給付規定 PDF → 條文）
      ↓
ingest.py（jieba + BM25）→ index.pkl
      ↓
retrieve.py（top-k ＋ glossary_zh_en.json 中英查詢擴展）
      ↓
answer.py（Claude / Ollama / 純檢索，作答並標註出處）
      ↓
app.py（Web UI）  ／  eval.py（評測，結果可存檔比較）
```

## 開發

```bash
pip install -r requirements-dev.txt
python ingest.py
python -m pytest -q
```

歡迎參與，請先讀 [CONTRIBUTING.md](CONTRIBUTING.md)。臨床內容有誤請開 [correctness issue](https://github.com/PatentsOwnerJeff/urobot-tw/issues/new?template=clinical_correctness.yml)，這類問題最優先處理。

安全性與部署注意事項見 [SECURITY.md](SECURITY.md)。

## 路線圖

- [x] 中英醫學詞對照表查詢擴展
- [x] 健保給付規範語料管線
- [x] 健保藥品給付規定條文收錄
- [x] CI 與基礎測試
- [x] 排序調校與檢索品質基準（Top-1 10/10，CI 把關）
- [ ] 向量檢索（bge-m3）混合排序 —— 現行 BM25 對「同義但完全不同字」仍無能為力
- [ ] TUA 指引授權與收錄
- [ ] 台灣專科甄審題庫完整評測，發表對標論文
- [ ] 健保給付規定自動更新排程
- [ ] TAIDE/Llama 微調之台灣醫療專用模型

## 團隊

| 成員 | 角色 |
|---|---|
| [@PatentsOwnerJeff](https://github.com/PatentsOwnerJeff) | 專案發起、架構設計、商標與授權 |
| [@wenhuikuo](https://github.com/wenhuikuo) | 臨床內容審閱、語料整理、評測題庫 |

歡迎泌尿科臨床、NLP、資料工程領域的夥伴參與，請由 Issue 或 PR 開始。

## 致謝

感謝德國 DKFZ [UroBot](https://github.com/DBO-DKFZ/UroBot) 團隊公開其方法與評測設計，為本專案提供了對標基準。

健保給付語料取自[政府資料開放平臺](https://data.gov.tw/)，資料提供機關為衛生福利部中央健康保險署。

## 免責聲明

研發中專案。輸出僅供臨床參考與教育用途，不構成醫療建議，最終決策由醫師負責。

本系統未經任何主管機關（TFDA、FDA、CE 等）審查或核准，不是醫療器材，不得作為診斷或治療依據。

UROBOT® 為英普瑞斯股份有限公司之註冊商標（中華民國註冊第 02509814 號），不在 Apache-2.0 授權範圍內；「UroBot」（DKFZ）為另一獨立學術專案。
