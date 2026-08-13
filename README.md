# UROBOT TW — 開源台灣泌尿科臨床決策輔助 AI

**Open-source Taiwanese urology clinical decision-support AI.** RAG 架構：檢索泌尿科指引 → 大模型作答 → 逐點標註出處。與德國 DKFZ [UroBot](https://github.com/DBO-DKFZ/UroBot)（EAU 指引＋GPT-4o，專科考題 88.4%）同架構，差異化：繁體中文、台灣臨床實務、健保給付規範、**不綁定任何一家模型供應商**。

## 特色

- **可插拔模型層**：Claude API（預設推薦）／ Ollama 本地開源模型（免費、資料不出門）／純檢索模式（免任何 key）
- **中英跨語檢索**：EAU 英文指引每段附繁中摘要一起建索引，中文提問可命中英文指引
- **內建評測系統**：`eval.py` 對標 UroBot 的考題正確率（RoCA）評測法
- **語料即插即用**：新增 jsonl 檔重跑 `ingest.py` 即擴充知識庫

## 快速開始

```bash
pip install -r requirements.txt
python ingest.py     # 建索引
python app.py        # → http://127.0.0.1:5000
```

選擇模型（三選一）：

```bash
# A. Claude API（推薦）
pip install anthropic && export ANTHROPIC_API_KEY=sk-ant-...

# B. 本地 Ollama（完全免費，適合醫院內部署）
#    先安裝 https://ollama.com 並 ollama pull llama3.1
export UROBOT_OLLAMA_MODEL=llama3.1

# C. 什麼都不設 → 純檢索模式（回傳指引段落＋出處）
```

## 評測

```bash
python eval.py                       # 內建 12 題示範考題
python eval.py exams/你的題庫.jsonl   # 泌尿專科甄審考題轉成同格式即可評測
```

題目格式：`{"id","question","options":{"A"..."D"},"answer","evidence":[相關段落id]}`

## 語料庫

| 檔案 | 內容 | 段落數 |
|---|---|---|
| `demo_guidelines.jsonl` | 繁中示範語料 | 10 |
| `eau_urolithiasis.jsonl` | EAU 結石指引（英文＋繁中摘要） | 52 |
| `eau_prostate_cancer.jsonl` | EAU 攝護腺癌指引 | 64 |
| `eau_male_luts.jsonl` | EAU 男性 LUTS/BPH 指引 | 50 |

⚠️ **著作權注意**：指引語料著作權屬原機構（EAU/TUA 等）。公開 repo 預設排除 `eau_*.jsonl`（見 `.gitignore`），使用者需在本機自行建置，或待取得機構授權後散布。程式碼本身為 Apache-2.0。

## 架構

```
corpus/*.jsonl → ingest.py（jieba+BM25）→ retrieve.py（top-k）
→ answer.py（Claude/Ollama 作答＋出處）→ app.py（Web UI）／eval.py（評測）
```

## 路線圖

- [ ] 向量檢索（bge-m3）混合排序
- [ ] TUA 指引授權與收錄
- [ ] 台灣專科甄審題庫完整評測，發表對標論文
- [ ] 健保給付規定自動更新爬蟲
- [ ] TAIDE/Llama 微調之台灣醫療專用模型

## 免責聲明

研發中專案。輸出僅供臨床參考與教育用途，不構成醫療建議，最終決策由醫師負責。UROBOT 商標屬專案所有人，不在 Apache-2.0 授權範圍內。
