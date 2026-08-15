"""build_corpus.py 的雜訊過濾回歸測試。

背景：實測 EAU Male LUTS 2026，未過濾前切出 1081 段，其中 346 段（32%）是
參考文獻，而且因為 REFERENCES 標題不帶編號，整包被錯標成前一節「6.3 Surgical
treatment」。書目含大量作者名、期刊名與年份，進了 BM25 就會被當成指引段落
檢索出來。另有封面與目錄，目錄的字距會被 PDF 抽成斷字（Int roduction）。

這些過濾一旦失效不會報錯，只會讓語料悄悄變髒，所以用測試釘住。
"""
import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

BODY = ("Alpha-1 blockers reduce the tone of prostatic smooth muscle and improve "
        "urinary flow rate in men with lower urinary tract symptoms. The onset of "
        "action is rapid and efficacy is independent of prostate size in most trials. ")

DOC = f"""EAU Guidelines on Something 2026

CONTENTS
1. INTRODUCTION 7
1.1 Aim and objectives 7
5.6.4.a Drugs for urgency urinary incontinence (UUI) 71
5.2.7.b Combination therapy ................ 32

1.1 Aim and objectives
{BODY}{BODY}

5.2 Medical treatment
{BODY}{BODY}

REFERENCES
1. Smith J, et al. Efficacy of tamsulosin. Eur Urol, 2016. 30: 665.
https://www.ncbi.nlm.nih.gov/pubmed/26886719 2. Bach T, et al. Thulium laser.
J Endourol, 2017. 35: 153. https://www.ncbi.nlm.nih.gov/pubmed/27886711
"""


@pytest.fixture
def docs(tmp_path):
    from build_corpus import build

    p = tmp_path / "guideline.txt"
    p.write_text(DOC, encoding="utf-8")
    return build(str(p), "test", "Test Guideline 2026",
                 min_chars=100, max_chars=400)


def test_references_section_is_dropped(docs):
    joined = " ".join(d["text"] for d in docs)
    assert "pubmed" not in joined.lower(), "參考文獻沒被濾掉"
    assert "Eur Urol" not in joined, "期刊書目沒被濾掉"


def test_table_of_contents_is_dropped(docs):
    joined = " ".join(d["text"] for d in docs)
    assert "Drugs for urgency urinary incontinence (UUI) 71" not in joined
    assert "Combination therapy" not in joined, "點狀引導線的目錄行沒被濾掉"


def test_toc_entry_does_not_become_a_section(docs):
    """目錄項長得像章節標題。若先比對 HEADING 就會把目錄當成正文開始，
    後面整段目錄都會跟著留下來——這是實際踩過的 bug。"""
    titles = {d["section"] for d in docs}
    assert not any(t.startswith("5.6.4.a") for t in titles), \
        f"目錄項被當成章節標題：{sorted(titles)}"


def test_body_content_survives(docs):
    assert docs, "過濾把正文也殺光了"
    joined = " ".join(d["text"] for d in docs)
    assert "Alpha-1 blockers" in joined
    titles = {d["section"] for d in docs}
    assert "1.1 Aim and objectives" in titles
    assert "5.2 Medical treatment" in titles


def test_front_matter_dropped_by_default(docs):
    assert all(d["section"] != "Preamble" for d in docs)


def test_keep_front_matter_flag(tmp_path):
    from build_corpus import build

    p = tmp_path / "g.txt"
    p.write_text(DOC, encoding="utf-8")
    kept = build(str(p), "t", "s", min_chars=100, max_chars=400,
                 keep_front_matter=True)
    plain = build(str(p), "t", "s", min_chars=100, max_chars=400)
    assert len(kept) >= len(plain)


def test_citation_heavy_paragraph_is_dropped():
    """REFERENCES 標題抽不出來時的保險：整段都是連結就丟掉。"""
    from build_corpus import looks_like_citations

    assert looks_like_citations(
        "1. Smith J. Eur Urol 2016. https://pubmed.gov/1 "
        "2. Bach T. J Urol 2017. https://pubmed.gov/2")
    assert not looks_like_citations(
        "Alpha blockers improve flow rate; see the EAU website "
        "at https://uroweb.org for the full recommendation table.")
