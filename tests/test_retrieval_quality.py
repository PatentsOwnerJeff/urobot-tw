"""檢索品質基準測試。

這組測試的用途不是驗證程式不當機，而是防止「排序退化」——
排序一旦壞掉，使用者問「攝護腺肥大用藥健保給付」會得到「前列腺按摩」，
這種答案會讓臨床端直接失去信任，而且不會有任何例外或紅字提醒你。

基準題庫：exams/retrieval_benchmark.jsonl
每題列出「可接受的答案 id」（通常不只一個，臨床指引與對應的給付條文都算對）。

門檻刻意訂在目前實測值之下留一點餘裕：改動若讓 Top-1 掉到 7/10 以下就算退化。
調校紀錄見 ingest.py 頂端的 BM25 參數註解。
"""
import json
import pathlib
import subprocess
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

BENCHMARK = BASE / "benchmarks" / "retrieval.jsonl"

MIN_TOP1 = 7          # 10 題中至少 7 題的第一名要是可接受答案
MIN_TOP3 = 9          # 至少 9 題的可接受答案要出現在前三名


@pytest.fixture(scope="module")
def cases():
    return [json.loads(l) for l in BENCHMARK.read_text(encoding="utf-8").splitlines() if l.strip()]


@pytest.fixture(scope="module", autouse=True)
def _index():
    if not (BASE / "index.pkl").exists():
        subprocess.run([sys.executable, "ingest.py"], cwd=BASE, check=True)


def _results(cases):
    from retrieve import search

    out = []
    for c in cases:
        ids = [h["id"] for h in search(c["query"], k=5)]
        ok = set(c["acceptable"])
        out.append({
            "id": c["id"], "query": c["query"], "top": ids[:3],
            "top1": bool(ids) and ids[0] in ok,
            "rank": next((i + 1 for i, x in enumerate(ids) if x in ok), None),
        })
    return out


def test_benchmark_file_references_existing_ids(cases):
    """基準題庫裡的 id 必須真的存在於語料中，否則測試會假性失敗。
    註：EAU 語料不隨 repo 散布，故只檢查至少有一個 acceptable id 存在。"""
    import glob

    known = set()
    for p in glob.glob(str(BASE / "corpus" / "*.jsonl")):
        for line in pathlib.Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                known.add(json.loads(line)["id"])

    for c in cases:
        assert set(c["acceptable"]) & known, \
            f"{c['id']}（{c['query']}）的 acceptable id 在語料中一個都找不到：{c['acceptable']}"


def test_top1_accuracy(cases):
    res = _results(cases)
    hits = sum(r["top1"] for r in res)
    misses = [f"{r['query']} → {r['top'][0] if r['top'] else '（無結果）'}"
              for r in res if not r["top1"]]
    assert hits >= MIN_TOP1, (
        f"Top-1 命中 {hits}/{len(res)}，低於門檻 {MIN_TOP1}。未命中：\n  "
        + "\n  ".join(misses)
    )


def test_top3_recall(cases):
    res = _results(cases)
    hits = sum(1 for r in res if r["rank"] and r["rank"] <= 3)
    misses = [f"{r['query']} → 前三名 {r['top']}" for r in res
              if not (r["rank"] and r["rank"] <= 3)]
    assert hits >= MIN_TOP3, (
        f"前三名命中 {hits}/{len(res)}，低於門檻 {MIN_TOP3}。未命中：\n  "
        + "\n  ".join(misses)
    )


def test_short_nhi_entries_do_not_dominate():
    """回歸測試：BM25 的長度正規化曾讓極短的診療項目條目壓過給付規定條文，
    導致問「攝護腺肥大用藥健保給付條件」時第一名是「前列腺按摩」（230 點的處置）。
    調參後前兩名應為 BPH 用藥的給付規定條文。"""
    from retrieve import search

    top2 = [h["id"] for h in search("攝護腺肥大用藥健保給付條件", k=2)]
    assert "nhi-proc-50009C" not in top2, "「前列腺按摩」不該擠進攝護腺肥大用藥查詢的前兩名"
    assert all(i.startswith("nhi-rule-5.2.2") for i in top2), \
        f"前兩名應為 BPH 用藥給付規定（5.2.2.x），實際：{top2}"


def test_index_records_bm25_params():
    """索引要記錄調校過的參數，否則無從得知現有索引是用什麼設定建的。"""
    from retrieve import _load

    params = _load().get("params")
    assert params, "index.pkl 未記錄 BM25 參數，請重跑 python ingest.py"
    assert 0.0 <= params["b"] <= 1.0
    assert params["k1"] > 0
