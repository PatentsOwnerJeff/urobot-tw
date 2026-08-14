"""UROBOT TW — 檢索引擎（BM25 ＋ 中英 query expansion，可日後升級向量檢索）

中文提問要命中英文指引原文，除了語料的 summary_zh 之外，這裡再加一層：
依 glossary_zh_en.json 把查詢中出現的中文醫學詞彙補上英文同義詞，
例如「輸尿管結石怎麼治療」→ 額外加入 ureteral stone / ureterolithiasis / stone…
成本幾乎為零，效果比只靠摘要好很多。設 UROBOT_NO_EXPAND=1 可關閉。
"""
import json
import os
import pickle

import jieba

BASE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE, "index.pkl")
GLOSSARY_PATH = os.path.join(BASE, "glossary_zh_en.json")

_cache = None
_glossary = None


class IndexNotBuilt(FileNotFoundError):
    """index.pkl 不存在時拋出，附帶可操作的指示。"""


def _load():
    global _cache
    if _cache is None:
        if not os.path.exists(INDEX_PATH):
            raise IndexNotBuilt(
                "找不到索引檔 index.pkl。\n"
                "請先執行：  python ingest.py\n"
                "（index.pkl 不進版控，每台機器都要自己建一次。）"
            )
        # 注意：pickle 反序列化可執行任意程式碼，只載入自己用 ingest.py 產生的索引。
        # 詳見 SECURITY.md。
        with open(INDEX_PATH, "rb") as f:
            _cache = pickle.load(f)
    return _cache


def _load_glossary():
    global _glossary
    if _glossary is None:
        try:
            with open(GLOSSARY_PATH, encoding="utf-8") as f:
                raw = json.load(f)
            _glossary = {k: v for k, v in raw.items() if not k.startswith("_")}
        except (OSError, ValueError):
            _glossary = {}
    return _glossary


def expand(query: str):
    """回傳查詢中命中的詞彙所對應的擴展詞（中英皆有，去重、保持穩定順序）。

    詞條前綴 ⚠ 表示該對應屬定義層級的展開、尚待臨床審閱；檢索時照用，
    但標記保留在檔案裡供人工複查（見 glossary 的 _review 說明）。
    """
    if os.getenv("UROBOT_NO_EXPAND"):
        return []
    terms, seen = [], set()
    glossary = _load_glossary()
    # 長詞優先：先比對「輸尿管結石」再比對「結石」，兩者都會加入，長詞的專指性較高
    for zh in sorted(glossary, key=len, reverse=True):
        if zh in query:
            for term in glossary[zh]:
                term = term.lstrip("⚠").strip()
                low = term.lower()
                if term and low not in seen:
                    seen.add(low)
                    terms.append(term)
    return terms


def tokenize(text: str):
    return [t.lower() for t in jieba.cut_for_search(text) if t.strip()]


def search(query: str, k: int = 4):
    idx = _load()
    tokens = tokenize(query)
    for term in expand(query):
        tokens.extend(tokenize(term))

    scores = idx["bm25"].get_scores(tokens)
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    return [{**idx["docs"][i], "score": round(float(scores[i]), 3)}
            for i in ranked if scores[i] > 0]


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "輸尿管結石多大需要手術"
    try:
        hits = search(q)
    except IndexNotBuilt as e:
        raise SystemExit(str(e))

    added = expand(q)
    if added:
        print(f"查詢擴展：{q}  ＋  {', '.join(added[:12])}{'…' if len(added) > 12 else ''}\n")
    if not hits:
        print("語料庫中找不到相關段落。")
    for r in hits:
        print(f"[{r['score']}] {r['section']} ({r['id']})\n  {r['text'][:80]}…\n")
