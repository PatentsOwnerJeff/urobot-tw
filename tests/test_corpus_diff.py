"""語料變動摘要與健全性檢查測試。

這組測試守的是自動更新排程的安全線。核心風險不是「漏掉一次更新」——那只是資料舊了；
真正的風險是健保署改欄位名稱時，build 腳本不拋例外、安靜地產出殘缺語料，被自動
commit 進去。屆時檢索照跑、測試照過（現行 CI 的檢索測試只跑示範語料），
但給付資訊已經是錯的。

所以 sanity_problems() 必須擋下：段數暴跌、id 大量對不上、text 大量空白。
下面每一條 must-fail 測試都對應一種真實會發生的失效模式。
"""

import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import corpus_diff  # noqa: E402


def rec(rid, text, section="健保給付／診療項目／測試項目"):
    return {
        "id": rid,
        "source": "測試來源（政府資料開放授權條款第1版）",
        "section": section,
        "text": text,
    }


def write_jsonl(path, records):
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )


def make_corpus(n, prefix="nhi-proc-", points=600):
    return {
        f"{prefix}{i:05d}": rec(
            f"{prefix}{i:05d}",
            f"診療項目代碼 {i:05d}：測試項目 健保支付點數 {points} 點。 生效期間 2024/01/01 至 2910/12/31。",
        )
        for i in range(n)
    }


def check(old, new, **kw):
    d = corpus_diff.diff_file("t.jsonl", old, new)
    return d, corpus_diff.sanity_problems(d, old, new, **kw)


# ---------- diff 正確性 ----------


def test_no_change_is_reported_as_unchanged():
    old = make_corpus(10)
    d, problems = check(old, dict(old))
    assert not d.changed
    assert problems == []
    assert "無變動" in corpus_diff.render_markdown([d])


def test_detects_added_and_removed():
    old = make_corpus(10)
    new = make_corpus(10)
    new.pop("nhi-proc-00000")
    new["nhi-proc-99999"] = rec("nhi-proc-99999", "診療項目代碼 99999：新項目 健保支付點數 100 點。")
    d, _ = check(old, new)
    assert d.added == ["nhi-proc-99999"]
    assert d.removed == ["nhi-proc-00000"]


def test_payment_point_change_is_surfaced_explicitly():
    """支付點數變動是最有審查價值的資訊，必須單獨列出而不是埋在文字 diff 裡。"""
    old = make_corpus(5, points=600)
    new = make_corpus(5, points=750)
    d, _ = check(old, new)
    assert len(d.fact_changes) == 5
    rid, section, label, before, after = d.fact_changes[0]
    assert label == "支付點數"
    assert (before, after) == ("600", "750")

    md = corpus_diff.render_markdown([d])
    assert "600 → **750**" in md
    assert "給付內容變動" in md


def test_pure_text_edit_is_separated_from_number_change():
    old = make_corpus(1)
    new = {
        k: rec(k, v["text"] + " 備註：文字微調。")
        for k, v in old.items()
    }
    d, _ = check(old, new)
    assert d.fact_changes == []
    assert len(d.text_changes) == 1


def test_markdown_caps_long_listings():
    old = {}
    new = make_corpus(corpus_diff.MAX_LISTED + 15)
    d, _ = check(old, new)
    md = corpus_diff.render_markdown([d])
    assert "另有 15 筆" in md


# ---------- 健全性檢查：以下每一條都是真實會發生的失效模式 ----------


def test_flags_count_collapse():
    """健保署改欄位名稱 → 過濾條件比對不到 → 語料大幅縮水。"""
    old = make_corpus(400)
    new = make_corpus(50)
    _, problems = check(old, new)
    assert any("段數從 400 掉到 50" in p for p in problems)


def test_flags_empty_rebuild():
    old = make_corpus(400)
    _, problems = check(old, {})
    assert any("重建後是空的" in p for p in problems)


def test_flags_id_scheme_change():
    """來源代碼或 id 規則變更時，逐筆 diff 沒有意義，不能當成大量增刪直接合併。"""
    old = make_corpus(100, prefix="nhi-proc-")
    new = make_corpus(100, prefix="nhi-procedure-")
    _, problems = check(old, new)
    assert any("id 對得上" in p for p in problems)


def test_flags_mass_empty_text():
    """欄位讀不到時會變成空字串，而不是拋例外。"""
    old = make_corpus(100)
    new = make_corpus(100)
    for i in range(20):
        new[f"nhi-proc-{i:05d}"]["text"] = ""
    _, problems = check(old, new)
    assert any("欄位空白或內容過短" in p for p in problems)


def test_flags_missing_required_field():
    old = make_corpus(100)
    new = make_corpus(100)
    for i in range(20):
        new[f"nhi-proc-{i:05d}"]["section"] = ""
    _, problems = check(old, new)
    assert any("欄位空白或內容過短" in p for p in problems)


def test_flags_count_explosion():
    """最危險的一種：資料「變多」。

    健保署改掉「生效迄日」的欄位名稱 → is_current() 讀不到日期 →
    依 build_nhi_corpus.py 的設計「無迄日視為現行」→ 數百筆已失效的給付項目
    全部被當成現行資料收錄。舊 id 一個不少、沒有任何空段落，只有段數上限擋得住。
    """
    old = make_corpus(391)
    new = make_corpus(3910)
    _, problems = check(old, new)
    assert any("暴增" in p for p in problems)


def test_flags_single_field_disappearing():
    """欄位被改名，但段落還在、長度還夠——上面所有檢查都抓不到。

    to_docs() 是用 `if pts:` 這類條件把子句串起來的，少一個欄位只是少一個子句。
    實測現行語料最短 66 字，離 MIN_TEXT_LEN=20 有 46 字的餘裕。
    """
    old = make_corpus(200)
    new = {
        rid: rec(rid, r["text"].replace(f"健保支付點數 600 點。", "").strip())
        for rid, r in make_corpus(200).items()
    }
    # 段數一樣、id 全對得上、沒有任何一段短於門檻
    assert len(new) == len(old)
    assert all(len(r["text"]) >= corpus_diff.MIN_TEXT_LEN for r in new.values())
    _, problems = check(old, new)
    assert any("支付點數" in p and "覆蓋率" in p for p in problems)


def test_flags_median_length_collapse():
    """欄位讀成空字串（例如中文品名），段落只剩代碼與日期。"""
    old = make_corpus(200)
    new = {
        rid: rec(rid, f"診療項目代碼 {rid[-5:]}： 健保支付點數 600 點。")
        for rid in old
    }
    _, problems = check(old, new)
    assert any("中位長度" in p for p in problems)


def test_flags_missing_baseline():
    """舊檔不存在時所有比例檢查都失效，不能默默放行。"""
    _, problems = check({}, make_corpus(5))
    assert any("無法做健全性檢查" in p for p in problems)


def test_legitimate_small_change_passes():
    """正常改版：少數項目增減、部分點數調整——不該被擋。"""
    old = make_corpus(400)
    new = make_corpus(400)
    for i in range(10):
        new.pop(f"nhi-proc-{i:05d}")
    for i in range(100, 110):
        new[f"nhi-proc-{i:05d}"]["text"] = new[f"nhi-proc-{i:05d}"]["text"].replace(
            "600 點", "640 點"
        )
    d, problems = check(old, new)
    assert problems == []
    assert d.changed
    assert len(d.fact_changes) == 10


def test_thresholds_are_tunable_for_real_bulk_removal():
    """健保署真的大幅刪減項目時，維護者可以放寬門檻放行。

    刻意用 400 → 150（刪掉 62%）而不是剛好 50%：id 重疊率門檻也必須跟著可調，
    否則 README 寫的「調低 min_ratio 就能放行」在超過一半的刪減時是假的。
    """
    old = make_corpus(400)
    new = {k: v for k, v in make_corpus(400).items() if int(k[-5:]) < 150}
    assert len(new) == 150

    _, strict = check(old, new)
    assert strict

    _, half_loose = check(old, new, min_ratio=0.3)
    assert half_loose, "只放寬段數門檻仍會被 id 重疊率擋住"

    _, loose = check(old, new, min_ratio=0.3, min_overlap=0.3)
    assert loose == []


def test_max_ratio_is_tunable_for_real_bulk_addition():
    old = make_corpus(100)
    new = make_corpus(400)
    _, strict = check(old, new)
    assert strict
    _, loose = check(old, new, max_ratio=5.0)
    assert loose == []


# ---------- 檔案讀取 ----------


def test_load_rejects_record_without_id(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"text": "沒有 id"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="缺少 id"):
        corpus_diff.load(p)


def test_load_rejects_malformed_json(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不是合法 JSON"):
        corpus_diff.load(p)


def test_missing_file_is_treated_as_empty(tmp_path):
    assert corpus_diff.load(tmp_path / "nope.jsonl") == {}


def test_cli_check_exits_2_on_unhealthy_corpus(tmp_path):
    """2 = 語料有問題，1 = 腳本自己壞了。workflow 要分得出這兩種，錯誤訊息才不會亂指。"""
    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    write_jsonl(old_dir / "t.jsonl", list(make_corpus(400).values()))
    write_jsonl(new_dir / "t.jsonl", list(make_corpus(10).values()))
    code = corpus_diff.main(
        ["--old", str(old_dir), "--new", str(new_dir), "--only", "t.jsonl", "--check"]
    )
    assert code == corpus_diff.EXIT_UNHEALTHY == 2


def test_cli_writes_github_output(tmp_path):
    """changed 旗標走檔案，不走 stderr grep——stderr 混著人看的訊息，
    任何一行湊巧含有那個字串都會翻轉判斷。"""
    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    write_jsonl(old_dir / "t.jsonl", list(make_corpus(10, points=600).values()))
    write_jsonl(new_dir / "t.jsonl", list(make_corpus(10, points=700).values()))
    gh_out = tmp_path / "gh_output"
    corpus_diff.main(
        [
            "--old", str(old_dir), "--new", str(new_dir), "--only", "t.jsonl",
            "--github-output", str(gh_out),
        ]
    )
    assert "changed=true" in gh_out.read_text(encoding="utf-8")

    write_jsonl(new_dir / "t.jsonl", list(make_corpus(10, points=600).values()))
    gh_out2 = tmp_path / "gh_output2"
    corpus_diff.main(
        [
            "--old", str(old_dir), "--new", str(new_dir), "--only", "t.jsonl",
            "--github-output", str(gh_out2),
        ]
    )
    assert "changed=false" in gh_out2.read_text(encoding="utf-8")


def test_cli_writes_summary_file(tmp_path):
    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    write_jsonl(old_dir / "t.jsonl", list(make_corpus(10, points=600).values()))
    write_jsonl(new_dir / "t.jsonl", list(make_corpus(10, points=700).values()))
    out = tmp_path / "diff.md"
    code = corpus_diff.main(
        ["--old", str(old_dir), "--new", str(new_dir), "--only", "t.jsonl", "--out", str(out)]
    )
    assert code == 0
    assert "600 → **700**" in out.read_text(encoding="utf-8")


def test_managed_list_excludes_copyrighted_guideline_corpora():
    """學會指引有著作權、不隨 repo 散布，排程絕不能碰。

    TUA 指引收錄在路線圖上，AUA 亦同——現在就把前綴一起守住，
    免得將來新增語料時漏掉這件事。
    """
    for prefix in ("eau", "aua", "tua"):
        assert all(not f.startswith(prefix) for f in corpus_diff.MANAGED), prefix
    assert all(f.startswith("nhi_") for f in corpus_diff.MANAGED)
