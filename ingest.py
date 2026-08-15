"""UROBOT TW — 語料建索引
讀取 corpus/*.jsonl（每行 {id, source, section, text, [summary_zh]}），
以 jieba 斷詞建立 BM25 索引，存成 index.pkl。
新增語料 = 放入 jsonl 檔重跑本檔，程式不用改。
"""
import json, pickle, glob, os
import jieba
from rank_bm25 import BM25Okapi

BASE = os.path.dirname(os.path.abspath(__file__))

# BM25 參數。b 控制文件長度正規化，預設 0.75 對短文件過於慷慨 ——
# 健保診療項目條目只有 30–40 個詞（「診療項目代碼 50009C：前列腺按摩 230 點」），
# 而給付規定條文有 300+ 詞，結果問「攝護腺肥大用藥給付條件」會被「前列腺按摩」
# 壓過去。以 benchmarks/retrieval.jsonl 掃描後定為 b=0.3、k1=1.2：
#   b=0.75（原預設）  Top-1 6/10   MRR 0.710
#   b=0.30            Top-1 8/10   MRR 0.827
# 再補上商品名→學名對照（威而鋼→sildenafil 等）後為 Top-1 10/10。
# tests/test_retrieval_quality.py 會在 CI 擋住排序退化。
# 可用環境變數覆寫以便重新調校：UROBOT_BM25_B / UROBOT_BM25_K1
BM25_B = float(os.getenv("UROBOT_BM25_B", "0.3"))
BM25_K1 = float(os.getenv("UROBOT_BM25_K1", "1.2"))

def tokenize(text: str):
    return [t.lower() for t in jieba.cut_for_search(text) if t.strip()]

def main():
    docs, seen = [], set()
    for path in sorted(glob.glob(os.path.join(BASE, "corpus", "*.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                if d["id"] in seen:
                    raise SystemExit(f"重複 id：{d['id']}（{path}）")
                seen.add(d["id"])
                docs.append(d)
    if not docs:
        raise SystemExit("corpus/ 內沒有語料")
    # 索引欄位：章節 + 中文摘要（若有）+ 原文 → 中文查詢也能命中英文指引
    corpus_tokens = [
        tokenize(" ".join([d.get("section", ""), d.get("summary_zh", ""), d["text"]]))
        for d in docs
    ]
    bm25 = BM25Okapi(corpus_tokens, k1=BM25_K1, b=BM25_B)
    with open(os.path.join(BASE, "index.pkl"), "wb") as f:
        pickle.dump({"bm25": bm25, "docs": docs,
                     "params": {"k1": BM25_K1, "b": BM25_B}}, f)
    print(f"已建立索引：{len(docs)} 個段落 → index.pkl（BM25 k1={BM25_K1}, b={BM25_B}）")

if __name__ == "__main__":
    main()
