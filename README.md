# UROBOT® TW — 開源台灣泌尿科臨床指引與健保給付檢索問答工具

[![CI](https://github.com/PatentsOwnerJeff/urobot-tw/actions/workflows/ci.yml/badge.svg)](https://github.com/PatentsOwnerJeff/urobot-tw/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

**繁體中文** ｜ [English](README.en.md)

> UROBOT® 為英普瑞斯股份有限公司之註冊商標（中華民國註冊第 02509814 號，第 10、44 類）。

**Open-source question-answering tool for urology guidelines and NHI reimbursement rules (Taiwan).** RAG 架構：檢索泌尿科指引 → 大模型作答 → 逐點標註出處。差異化：繁體中文、台灣臨床實務、健保給付規範、**不綁定任何一家模型供應商**。

> **先講清楚兩件事，免得你白跑一趟：**
>
> 1. **開箱只答得了健保給付問題。** 學會指引受著作權保護不能隨 repo 散布，臨床指引語料要你自行建置。詳見[你 clone 下來實際會拿到什麼](#你-clone-下來實際會拿到什麼)。
> 2. **本專案目前沒有任何可對外宣稱的準確率。** 下方提到的 88.4% 是德國 DKFZ [UroBot](https://github.com/DBO-DKFZ/UroBot) 在歐洲專科考題的成績，那是**另一個獨立專案**，不是這裡的數字。本專案尚未以泌尿專科甄審題庫做過正式評測。

架構上對標 DKFZ UroBot（EAU 指引＋GPT-4o，專科考題 88.4%），但語料、語言與給付規範完全不同。

## 特色

標示 🔧 的功能需要你自行建置語料或設定模型後才會生效：

- **不知道就說不知道**：涵蓋範圍以 [`scope.json`](scope.json) 明示宣告，宣告之外的主題一律拒答，並告訴你要補哪一本指引、指令怎麼下——不拿字面沾邊的段落硬湊成答案
- **台灣健保給付規範**：478 段隨 repo 附上，取自政府開放資料可合法散布。[`build_nhi_corpus.py`](build_nhi_corpus.py) 可自行重建與更新 —— 這是國外系統沒有的
- **可插拔模型層** 🔧：Claude API（預設推薦）／ Ollama 本地開源模型（免費、資料不出門）／純檢索模式（免任何 key，但只回傳段落不作答）
- **中英跨語檢索** 🔧：英文指引每段附繁中摘要一起建索引，再加上[中英醫學詞對照表](glossary_zh_en.json)做查詢擴展，中文提問可命中英文指引（需先建置英文指引語料）
- **內建評測系統** 🔧：`eval.py` 對標 UroBot 的考題正確率（RoCA）評測法，結果可存檔比較（需接模型）
- **語料即插即用**：新增 jsonl 檔重跑 `ingest.py` 即擴充知識庫（記得同步更新 `scope.json`）

## 快速開始

```bash
pip install -r requirements.txt
python ingest.py     # 建索引（488 段語料已隨 repo 附上）
python app.py        # → http://127.0.0.1:5000
```

> macOS 的 AirPlay Receiver 預設佔用 5000 埠。若啟動後連不上，改用其他埠：
> `UROBOT_PORT=5050 python app.py`

### 你 clone 下來實際會拿到什麼

不需要任何 API key 就能跑起來，但**開箱狀態能回答的範圍很窄**，這點先講清楚：

| | 開箱狀態 |
|---|---|
| 語料 | 488 段：健保診療項目 391、用藥 69、給付規定條文 18、示範指引 10 |
| **能回答的主題** | **只有「台灣健保給付規範」** |
| 其他泌尿科臨床問題 | 一律拒答，並告訴你要補哪一本指引、指令怎麼下 |
| 回答形式 | 純檢索：回傳相關段落＋出處。設了模型才會整合成一段答案 |

```
問：輸尿管結石多大需要手術       → 未對應到已宣告主題（EAU 結石指引未收錄）
問：女性反覆泌尿道感染要怎麼預防   → 拒答，並附上補語料的完整步驟
問：攝護腺肥大用藥健保給付條件     → 正常作答，附條文與健保署出處
```

**這是刻意的，不是沒做完。** 學會指引受著作權保護，不能隨 repo 散布；而系統寧可
說「我沒有這個主題的資料」，也不會拿字面沾邊的段落硬湊——詳見
[涵蓋範圍與拒答](#涵蓋範圍與拒答)。

### 要讓它真正能用，有兩件事要做

**1. 接上模型**（否則只會吐段落，不會整合成答案）

```bash
# A. Claude API（推薦）
pip install anthropic && export ANTHROPIC_API_KEY=sk-ant-...

# B. 本地 Ollama（完全免費，適合醫院內部署，資料不出門）
#    先安裝 https://ollama.com 並 ollama pull llama3.1
export UROBOT_OLLAMA_MODEL=llama3.1

# C. 什麼都不設 → 純檢索模式（回傳指引段落＋出處）
```

**2. 建置臨床指引語料**（否則只答得了健保給付問題）

見下方[建置語料](#建置語料)。健保部分一行指令就能跑；學會指引需要你自行取得 PDF。
建完之後把主題加進 `scope.json` 的 `covered`，系統才會開始回答該主題——
**忘了改 scope.json 的話，語料建好了系統還是會說沒有**。

系統本身會提示：問到缺口主題時，回覆裡就附有該主題需要哪一本指引、下載網址、
可直接複製的建置指令，以及 `scope.json` 要怎麼改。

## 建置語料

開箱的 488 段裡，健保語料（478 段）已隨 repo 附上並可合法散布，但**臨床指引只有
10 段示範語料**。要讓系統能回答健保給付以外的問題，必須自行建置：

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

**建置時會自動剔除三類雜訊**（`tests/test_build_corpus.py` 釘住）：

- **參考文獻**：指引 PDF 的書目佔比極高，實測 EAU Male LUTS 2026 有 32%（1081 段中 346 段）。
  因為 REFERENCES 標題不帶編號，整包會被錯標成前一節，書目裡的作者名與期刊名進了 BM25
  就會被當成指引段落檢索出來。
- **封面與目錄**：目錄項本身長得像章節標題，且目錄的字距會被 PDF 抽成斷字
  （`Int roduction`、`Medi cal history`）。需要保留時加 `--keep-front-matter`。
- **整段都是引用的段落**：REFERENCES 標題抽不出來時的保險。

同一份 PDF 過濾前後：1081 段 → 686 段，書目與目錄殘留皆為 0。

> `--translate` 需要 LLM（`ANTHROPIC_API_KEY` 或 `UROBOT_OLLAMA_MODEL`）。
> 沒有繁中摘要的話，中文提問命中英文指引的能力會明顯下降，別跳過這一步。

### 建完之後必須改 scope.json

**這一步漏掉的話，語料建好了系統還是會拒答。** 在 `scope.json` 把該主題從 `gaps`
移到 `covered`：

```jsonc
// covered 陣列裡新增
{
  "topic": "泌尿道感染",
  "requires": ["eau-uti"],          // 對應你建置時用的 --prefix
  "detail": "單純性與複雜性 UTI、反覆感染預防、無症狀菌尿",
  "keywords": ["泌尿道感染", "膀胱炎", "腎盂腎炎", "反覆感染", "urinary tract infection"]
}
```

`requires` 會在啟動時對照索引中實際有的段落 id 前綴——寫錯或語料沒建成功，
該主題會自動維持未涵蓋，不會出現「宣稱有、實際拿示範語料作答」的情況。

改完重跑 `python ingest.py`，然後用 `python -m pytest tests/test_scope.py` 確認。

## 涵蓋範圍與拒答

系統只回答 [`scope.json`](scope.json) 明示宣告有涵蓋的主題。宣告之外的主題一律拒答，
並說明缺的是什麼——**不以字面相近的段落充數**。

```
問：女性反覆泌尿道感染要怎麼預防
→ 【語料庫未涵蓋此主題，不予作答】
   ▪ 泌尿道感染（完整指引）
     只有 1 段示範語料（單純性膀胱炎）與健保抗生素給付條文，不足以支撐臨床決策。
     EAU Urological Infections 指引尚未收錄。
```

沒有這道關卡時，同一個問題的第一名是「取石前抗生素治療」——結石病人的術前預防，
對這題完全是錯的，但看起來像答案。接上大模型後還會被寫成通順的臨床建議，
比直接吐段落更危險。

**為什麼是人工宣告而不是信心分數。** 兩種統計做法都實測過，都失效：

| 方法 | 「腎細胞癌標靶治療」（語料庫沒有） | 「PSA 篩檢要注意什麼」（語料庫有） |
|---|---|---|
| BM25 原始分數 | 12.99 | 16.11 |
| IDF 加權詞彙覆蓋率 | **0.562** | **0.267** |

未涵蓋的問題分數反而比涵蓋的高。原因是 jieba 會把未收錄的醫學複合詞拆成語料裡
都有的字（腎細胞癌 → 腎／細胞／癌），任何以詞頻為基礎的指標都分不開。
所以範圍由人維護、由 `tests/test_scope.py` 守住。

介面上也**不再顯示相關度分數**：BM25 分數跨查詢不可比較，卻長得像信心值。

宣告會隨機器上實際有的語料自動調整——EAU 語料不隨 repo 散布，沒自建時對應主題
會降級為未涵蓋，而不是宣稱有卻拿示範語料作答。

目前已知缺口（完整清單見 `scope.json` 的 `gaps`）：腎細胞癌、膀胱癌／上泌尿道上皮癌、
睪丸癌、陰莖癌、男性不孕症、女性尿失禁、神經性膀胱、攝護腺炎、兒童泌尿科、
腎移植、泌尿道感染完整指引、血尿之評估。

新增指引語料時，請同時在 `scope.json` 補上主題並從 `gaps` 移除。

## 檢索品質

`benchmarks/retrieval.jsonl` 收錄 10 題真實臨床會問的問題，涵蓋「中文病名 vs 條文用語不同」「商品名 vs 學名」等實際難點。

只評測 `scope.json` 宣稱有涵蓋的題目——系統會拒答的主題，量它的排序品質沒有意義。
（原題庫的 rb06「單純性泌尿道感染要用什麼抗生素」標準答案是取石前抗生素預防，
本身就是錯的；把這種題目留在題庫裡等於把錯誤當基準守住。）

CI 每次都會跑，門檻設在 Top-1 ≥ 7 成 —— 排序退化不會拋例外，只會安靜地把答案變爛，所以必須用測試擋住。

```bash
python -m pytest tests/test_retrieval_quality.py -v
```

調校紀錄（`ingest.py` 頂端有完整說明）：BM25 預設 `b=0.75` 對短文件過於慷慨，健保診療項目條目只有 30–40 個詞，給付規定條文有 300+ 詞，結果問「攝護腺肥大用藥給付條件」第一名會是「前列腺按摩」。改為 `b=0.3`、`k1=1.2` 後 Top-1 由 6/10 升至 8/10，再補上商品名→學名對照後 10 題全中（當時的 10 題題庫；現行評測排除 2 題拒答主題，實測 8/8）。

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

### 自動更新

健保署的支付標準與用藥品項檔會改版，過期的給付資訊會讓下游全部跟著錯。
[`.github/workflows/nhi-refresh.yml`](.github/workflows/nhi-refresh.yml) 每月 1 日重建一次健保語料，
有變動就開 PR——**不自動合併**，給付條件的變動有臨床意義，必須有人看過。

PR 內文是 `corpus_diff.py` 產生的摘要，不是原始 diff：

```
腎臟移植諮詢費（nhi-proc-01039C）支付點數 600 → 655
新增 1 段 / 刪除 2 段 / 條文文字調整 1 段
```

合併前有三道關卡，缺一不可：

| 關卡 | 擋的是什麼 |
|---|---|
| 建置腳本離開碼 | 抓取失敗或章節缺漏。**部分結果一律不落地**——少一份資料集不會觸發段數門檻 |
| `corpus_diff.py --check` | 段數暴跌／暴增、id 大量對不上、欄位整批消失、段落長度縮水 |
| `pytest`（含檢索品質） | 語料換掉後排序退化 |

第二道是整套設計的重點。健保署改欄位名稱時，建置腳本**不會拋例外**——
欄位讀不到就變空字串，過濾條件比對不到就整批漏掉。沒有這道關卡，自動更新會變成
自動污染，而且不會有人發現，因為現行 CI 的檢索測試只跑示範語料。

實際擋得住的幾種失效（`tests/test_corpus_diff.py` 每一種都有對應測試）：

| 症狀 | 為什麼難抓 | 靠哪個門檻 |
|---|---|---|
| 泌尿科過濾條件失效，段數剩零星幾筆 | — | `--min-ratio` |
| **迄日欄位改名 → 失效項目全被當成現行** | 資料「變多」，舊 id 一個不少，沒有空段落 | `--max-ratio` |
| 項目代碼規則變更 | 看起來像大量新增＋大量刪除 | `--min-overlap` |
| **支付點數欄位改名** | 段數不變、id 全對、段落仍有 50+ 字 | 關鍵欄位覆蓋率 |
| 中文品名讀成空字串 | 同上，只是段落短了一截 | 段落中位長度 |

粗體那兩種是這道關卡真正的價值所在——其餘門檻對它們完全無效。

```bash
# 手動比對兩份語料（例如自己重建後想先看變動）
mkdir -p /tmp/before && cp corpus/*.jsonl /tmp/before/
python build_nhi_corpus.py && python build_nhi_rules.py
python corpus_diff.py --old /tmp/before --new corpus --check
```

排程只碰 `nhi_*.jsonl`。EAU 指引語料有著作權、不隨 repo 散布，
`corpus_diff.MANAGED` 明確排除，並由 `tests/test_corpus_diff.py` 守住。

健保署真的大幅改版時門檻會誤擋。到 Actions 頁面用 `workflow_dispatch` 手動觸發並調整
`min_ratio` / `max_ratio` / `min_overlap`。刪減超過一半時要**同時**放寬 `min_ratio`
與 `min_overlap`——只調前者仍會被 id 重疊率擋下。

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
- [x] 排序調校與檢索品質基準（已涵蓋主題 Top-1 8/8，CI 把關）
- [x] 明示涵蓋範圍宣告與拒答（`scope.json`）
- [ ] 向量檢索（bge-m3）混合排序 —— 現行 BM25 對「同義但完全不同字」仍無能為力
- [ ] TUA 指引授權與收錄
- [x] 健保給付語料自動更新排程（每月，附健全性檢查與變動摘要）
- [ ] 台灣專科甄審題庫完整評測，發表對標論文
- [ ] TAIDE/Llama 微調之台灣醫療專用模型

## 團隊

| 成員 | 角色 |
|---|---|
| [@PatentsOwnerJeff](https://github.com/PatentsOwnerJeff) | 專案發起、架構設計、商標與授權 |
| [@wenhuikuo](https://github.com/wenhuikuo) | 臨床內容審閱、語料整理、評測題庫 |
| [@Abigail1984](https://github.com/Abigail1984) | 臨床合作洽談、醫院與泌尿科醫師社群聯繫 |

歡迎泌尿科臨床、NLP、資料工程領域的夥伴參與，請由 Issue 或 PR 開始。

**醫療院所合作洽詢**：歡迎透過 [Issue](https://github.com/PatentsOwnerJeff/urobot-tw/issues) 或 patentowneroffice@gmail.com 與我們聯繫。系統可於院內地端部署，搭配本地模型時提問不離開院內網路。

## 致謝

感謝德國 DKFZ [UroBot](https://github.com/DBO-DKFZ/UroBot) 團隊公開其方法與評測設計，為本專案提供了對標基準。

健保給付語料取自[政府資料開放平臺](https://data.gov.tw/)，資料提供機關為衛生福利部中央健康保險署。

## 免責聲明

研發中專案。輸出僅供臨床參考與教育用途，不構成醫療建議，最終決策由醫師負責。

本系統未經任何主管機關（TFDA、FDA、CE 等）審查或核准，不是醫療器材，不得作為診斷或治療依據。

UROBOT® 為英普瑞斯股份有限公司之註冊商標（中華民國註冊第 02509814 號），不在 Apache-2.0 授權範圍內；「UroBot」（DKFZ）為另一獨立學術專案。
