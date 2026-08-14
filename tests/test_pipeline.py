"""UROBOT TW — 基礎測試
不需要任何 API key，全部在純檢索模式下跑，CI 可直接執行。
執行：python -m pytest -q
"""
import json
import pathlib
import subprocess
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

REQUIRED_CORPUS_FIELDS = ("id", "source", "section", "text")
REQUIRED_EXAM_FIELDS = ("id", "question", "options", "answer")


@pytest.fixture(scope="session", autouse=True)
def _index():
    """測試開始前確保 index.pkl 存在。"""
    if not (BASE / "index.pkl").exists():
        subprocess.run([sys.executable, "ingest.py"], cwd=BASE, check=True)


def _read_jsonl(path):
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if line:
            yield lineno, json.loads(line)


# ---------- 語料格式 ----------

def test_corpus_files_are_wellformed():
    """每個 jsonl 都要能解析、欄位齊全、id 全域唯一。"""
    seen = {}
    paths = sorted((BASE / "corpus").glob("*.jsonl"))
    assert paths, "corpus/ 內沒有任何 jsonl 語料"

    for path in paths:
        for lineno, doc in _read_jsonl(path):
            for field in REQUIRED_CORPUS_FIELDS:
                assert field in doc, f"{path.name}:{lineno} 缺少必要欄位 '{field}'"
                assert str(doc[field]).strip(), f"{path.name}:{lineno} 欄位 '{field}' 是空的"
            prev = seen.get(doc["id"])
            assert prev is None, f"id 重複：{doc['id']}（{prev} 與 {path.name}:{lineno}）"
            seen[doc["id"]] = f"{path.name}:{lineno}"


def test_exam_files_are_wellformed():
    for path in sorted((BASE / "exams").glob("*.jsonl")):
        for lineno, q in _read_jsonl(path):
            for field in REQUIRED_EXAM_FIELDS:
                assert field in q, f"{path.name}:{lineno} 缺少必要欄位 '{field}'"
            assert q["answer"] in q["options"], (
                f"{path.name}:{lineno} 正解 {q['answer']} 不在選項 {sorted(q['options'])} 中"
            )
            assert isinstance(q.get("evidence", []), list)


# ---------- 檢索 ----------

def test_search_finds_relevant_paragraph():
    from retrieve import search

    hits = search("尿路結石怎麼治療")
    assert hits, "『尿路結石怎麼治療』應該要在示範語料中找到段落"
    assert any(h["id"].startswith("stone") for h in hits), \
        f"預期命中 stone-* 段落，實際：{[h['id'] for h in hits]}"


def test_search_respects_k():
    from retrieve import search

    assert len(search("攝護腺", k=2)) <= 2


def test_search_returns_empty_for_nonsense():
    from retrieve import search

    assert search("zzzzqqqxxxyyy") == []


def test_search_results_are_sorted_by_score():
    from retrieve import search

    scores = [h["score"] for h in search("攝護腺肥大藥物治療", k=5)]
    assert scores == sorted(scores, reverse=True)


# ---------- 問答（純檢索模式） ----------

def test_ask_retrieval_only_mode(monkeypatch):
    """沒有任何 API key 時，必須降級為純檢索模式而不是丟例外。"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("UROBOT_OLLAMA_MODEL", raising=False)

    import answer

    out = answer.ask("血尿要做哪些檢查")
    assert "純檢索模式" in out
    assert "最終決策由醫師負責" in out, "免責聲明不得在任何路徑下被省略"


def test_ask_handles_no_hits(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("UROBOT_OLLAMA_MODEL", raising=False)

    import answer

    assert "找不到" in answer.ask("zzzzqqqxxxyyy")


# ---------- 免責聲明與商標（法遵） ----------

def test_readme_keeps_disclaimer_and_trademark():
    readme = (BASE / "README.md").read_text(encoding="utf-8")
    assert "最終決策由醫師負責" in readme
    assert "02509814" in readme, "商標註冊號不得從 README 消失"


def test_web_ui_renders_and_keeps_disclaimer(monkeypatch):
    """實際渲染頁面，確認免責聲明與商標聲明出現在使用者看得到的地方。"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("UROBOT_OLLAMA_MODEL", raising=False)

    from app import app

    client = app.test_client()

    html = client.get("/").get_data(as_text=True)
    assert "最終決策由醫師負責" in html
    assert "02509814" in html

    html = client.post("/", data={"q": "尿路結石怎麼治療"}).get_data(as_text=True)
    assert "最終決策由醫師負責" in html
    assert "stone-01" in html, "純檢索模式應在頁面上顯示段落出處編號"


def test_web_ui_shows_friendly_error_instead_of_500(monkeypatch):
    """後端丟例外時，使用者要看到可讀訊息而不是 500 白畫面。"""
    import app as app_module

    monkeypatch.setattr(app_module, "ask", lambda q: (_ for _ in ()).throw(RuntimeError("boom")))

    client = app_module.app.test_client()
    resp = client.post("/", data={"q": "測試"})
    assert resp.status_code == 200
    assert "boom" in resp.get_data(as_text=True)


def test_healthz(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("UROBOT_OLLAMA_MODEL", raising=False)

    from app import app

    body = app.test_client().get("/healthz").get_json()
    assert body["ok"] is True
    assert body["paragraphs"] > 0


# ---------- 中英 query expansion ----------

def test_glossary_expansion():
    from retrieve import expand

    terms = [t.lower() for t in expand("輸尿管結石多大需要手術")]
    assert "ureteral stone" in terms, "長詞『輸尿管結石』應被展開"
    assert "stone" in terms, "短詞『結石』也應一併展開"


def test_expansion_can_be_disabled(monkeypatch):
    from retrieve import expand

    monkeypatch.setenv("UROBOT_NO_EXPAND", "1")
    assert expand("輸尿管結石") == []


def test_glossary_file_is_valid():
    glossary = json.loads((BASE / "glossary_zh_en.json").read_text(encoding="utf-8"))
    for zh, en in glossary.items():
        if zh.startswith("_"):
            continue
        assert isinstance(en, list) and en, f"詞條 '{zh}' 的英文對照必須是非空陣列"
        assert all(isinstance(t, str) and t.strip() for t in en), f"詞條 '{zh}' 含空字串"
