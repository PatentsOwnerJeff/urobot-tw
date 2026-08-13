"""UROBOT TW — 檢索引擎（BM25，可日後升級向量檢索）"""
import os, pickle
import jieba

BASE = os.path.dirname(os.path.abspath(__file__))
_cache = None

def _load():
    global _cache
    if _cache is None:
        with open(os.path.join(BASE, "index.pkl"), "rb") as f:
            _cache = pickle.load(f)
    return _cache

def tokenize(text: str):
    return [t for t in jieba.cut_for_search(text) if t.strip()]

def search(query: str, k: int = 4):
    idx = _load()
    scores = idx["bm25"].get_scores(tokenize(query))
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    return [{**idx["docs"][i], "score": round(float(scores[i]), 3)}
            for i in ranked if scores[i] > 0]

if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "輸尿管結石多大需要手術"
    for r in search(q):
        print(f"[{r['score']}] {r['section']} ({r['id']})\n  {r['text'][:80]}…\n")
