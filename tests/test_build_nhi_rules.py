"""build_nhi_rules 的章節解析測試（合成資料，不連網）。"""
import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import build_nhi_rules as R  # noqa: E402

PDF = "https://info.nhi.gov.tw/api/INAE3000/INAE3000S01/getPDF?DurgFileName={}.pdf"


def _row(atc, ingredient, chapters, links):
    return {"藥品代號": "X", "ATC代碼": atc, "成分": ingredient,
            "藥品中文名稱": "測試", "藥品英文名稱": "Test",
            "給付規定章節": chapters, "給付規定章節連結": links}


def test_chapter_parsed_from_pdf_filename():
    rows = [_row("G04CB01", "FINASTERIDE 5 MG", "5.2.2.1.", PDF.format("5.2.2.1._20191201_000"))]
    out = R.chapter_links(rows)
    assert list(out) == ["5.2.2.1"]
    assert ("FINASTERIDE", "G04CB01") in out["5.2.2.1"]["ingredients"]


def test_multiple_chapters_split_on_comma():
    rows = [_row("J01MB04", "PIPEMIDIC ACID 250 MG", "10.1.,10.8.2.",
                 ",".join([PDF.format("10.1._20250101"), PDF.format("10.8.2._20191201_000")]))]
    assert sorted(R.chapter_links(rows)) == ["10.1", "10.8.2"]


def test_mismatched_chapter_and_link_counts():
    """實測資料有「章節欄 2 個、連結欄只有 1 個」的情況。
    章節編號一律從檔名解析，不依賴兩欄順序對應，故只會產出有連結的那一個。"""
    rows = [_row("L02BB03", "BICALUTAMIDE 50 MG", "5.2.4.,9.40.",
                 PDF.format("9.40._20120701_000"))]
    assert list(R.chapter_links(rows)) == ["9.40"]


def test_rows_without_link_are_skipped():
    assert R.chapter_links([_row("G04CA02", "TAMSULOSIN", "5.2.2.1.", "")]) == {}


def test_ingredients_merged_across_rows():
    rows = [
        _row("G04CB01", "FINASTERIDE 5 MG", "5.2.2.1.", PDF.format("5.2.2.1._20191201_000")),
        _row("G04CB02", "DUTASTERIDE .5 MG", "5.2.2.1.", PDF.format("5.2.2.1._20191201_000")),
    ]
    ings = {i for i, _ in R.chapter_links(rows)["5.2.2.1"]["ingredients"]}
    assert ings == {"FINASTERIDE", "DUTASTERIDE"}


def test_chapters_sorted_numerically():
    """10.1 要排在 9.40 之後，不能用字串排序。"""
    rows = [_row("A", "X", "", PDF.format(f"{c}._20200101"))
            for c in ["10.1", "2.4.1", "9.40", "5.2.2.1"]]
    assert list(R.chapter_links(rows)) == ["2.4.1", "5.2.2.1", "9.40", "10.1"]


@pytest.mark.parametrize("stem,expected", [
    ("5.2.2.1._20191201_000", "2019-12-01"),
    ("10.1._20250101", "2025-01-01"),
    ("9.40.", "未標示"),
])
def test_version_extracted_from_filename(stem, expected):
    assert R.version_of(stem) == expected


# ---------- 法遵 ----------

def test_rule_docs_carry_disclaimer_and_attribution():
    chapters = {"5.2.2.1": {"url": PDF.format("5.2.2.1._20191201_000"),
                            "stem": "5.2.2.1._20191201_000",
                            "ingredients": {("FINASTERIDE", "G04CB01")},
                            "text": "限前列腺增生且有阻塞症狀…"}}
    doc = R.to_docs(chapters, fetched="2026-08-15")[0]
    assert doc["id"] == "nhi-rule-5.2.2.1"
    assert "不等同於臨床適應症或治療建議" in doc["text"]
    assert "中央健康保險署" in doc["source"]
    assert "資料擷取日期 2026-08-15" in doc["source"]
    assert "2019-12-01" in doc["source"], "條文版本必須記錄，給付規定會改版"


def test_summary_only_omits_rule_text():
    """若法務認為條文全文不宜收錄，--summary-only 必須真的不含條文。"""
    chapters = {"5.2.2.1": {"url": PDF.format("5.2.2.1._20191201_000"),
                            "stem": "5.2.2.1._20191201_000",
                            "ingredients": {("FINASTERIDE", "G04CB01")},
                            "text": "限前列腺增生且有阻塞症狀…"}}
    doc = R.to_docs(chapters, summary_only=True)[0]
    assert "限前列腺增生" not in doc["text"]
    assert "條文內容" not in doc["text"]
    assert "FINASTERIDE" in doc["text"]
