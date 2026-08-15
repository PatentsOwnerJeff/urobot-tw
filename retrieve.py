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
SCOPE_PATH = os.path.join(BASE, "scope.json")

_cache = None
_glossary = None
_scope = None


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


def _load_scope():
    global _scope
    if _scope is None:
        try:
            with open(SCOPE_PATH, encoding="utf-8") as f:
                _scope = json.load(f)
        except (OSError, ValueError):
            _scope = {"covered": [], "gaps": []}
    return _scope


def _topic_available(topic):
    """該主題所依賴的段落是否真的在索引裡。

    EAU 語料不隨 repo 散布，使用者沒自建時對應主題必須自動降級為未涵蓋，
    否則系統會宣稱涵蓋攝護腺癌，實際上只拿 demo 語料的一段來回答。
    """
    ids = [d["id"] for d in _load()["docs"]]
    return all(any(i.startswith(p + "-") for i in ids)
               for p in topic.get("requires", []))


def _matches(query: str, topic) -> bool:
    q = query.lower()
    return any(kw.lower() in q for kw in topic.get("keywords", []))


def scope_of(query: str):
    """查詢主題是否在語料庫的宣告涵蓋範圍內。

    在檢索之前先問「我們到底有沒有這個主題的資料」。這一層是刻意用人工維護的
    明示宣告，而不是任何以分數為基礎的信心指標——原因見 scope.json 的說明。

    verdict:
      covered  已涵蓋，可正常呈現
      partial  部分涵蓋（例如有健保給付條文但沒有臨床指引），須標明缺哪一塊
      gap      已知未涵蓋，不應呈現硬湊出來的段落
      unknown  未對應到任何已宣告主題，結果須標為不確定
    """
    scope = _load_scope()
    gaps = [t for t in scope.get("gaps", []) if _matches(query, t)]
    covered = [t for t in scope.get("covered", [])
               if _matches(query, t) and _topic_available(t)]

    if gaps and covered:
        verdict = "partial"
    elif gaps:
        verdict = "gap"
    elif covered:
        verdict = "covered"
    else:
        verdict = "unknown"

    return {
        "verdict": verdict,
        "gaps": [{"topic": t["topic"], "note": t.get("note", ""),
                  "fix": t.get("fix")} for t in gaps],
        "covered": [{"topic": t["topic"], "detail": t.get("detail", "")} for t in covered],
        "available": [t["topic"] for t in scope.get("covered", []) if _topic_available(t)],
    }


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
