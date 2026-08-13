"""UROBOT TW — 語料建索引
讀取 corpus/*.jsonl（每行 {id, source, section, text, [summary_zh]}），
以 jieba 斷詞建立 BM25 索引，存成 index.pkl。
新增語料 = 放入 jsonl 檔重跑本檔，程式不用改。
"""
import json, pickle, glob, os
import jieba
from rank_bm25 import BM25Okapi

BASE = os.path.dirname(os.path.abspath(__file__))

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
    bm25 = BM25Okapi(corpus_tokens)
    with open(os.path.join(BASE, "index.pkl"), "wb") as f:
        pickle.dump({"bm25": bm25, "docs": docs}, f)
    print(f"已建立索引：{len(docs)} 個段落 → index.pkl")

if __name__ == "__main__":
    main()
