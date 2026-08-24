"""建置腳本的離開碼測試。

排程（.github/workflows/nhi-refresh.yml）靠離開碼判斷這次重建能不能用。
互動使用時人看得到畫面上的 ❌，排程看不到——若腳本失敗仍回 0，
抓取全失敗會被當成「資料沒有變動」，於是月復一月安靜地不更新，
而沒有任何人會發現語料早就過期了。這組測試守的就是這件事。
"""

import pathlib
import sys
from unittest import mock

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import build_nhi_corpus  # noqa: E402
import build_nhi_rules  # noqa: E402


@pytest.fixture
def outdir(tmp_path):
    return tmp_path / "corpus"


def test_corpus_build_returns_nonzero_when_download_fails(outdir, capsys):
    with mock.patch.object(
        build_nhi_corpus, "get_rows", side_effect=OSError("Tunnel connection failed")
    ):
        with mock.patch.object(sys, "argv", ["build_nhi_corpus.py", "--outdir", str(outdir)]):
            code = build_nhi_corpus.main()
    assert code == 1
    assert "未能建置" in capsys.readouterr().out


def test_corpus_build_returns_nonzero_when_filter_matches_nothing(outdir, capsys):
    """健保署改欄位名稱時的典型症狀：抓得到檔案，但篩不出任何一筆。"""
    with mock.patch.object(build_nhi_corpus, "get_rows", return_value=[{"亂七八糟欄位": "x"}]):
        with mock.patch.object(sys, "argv", ["build_nhi_corpus.py", "--outdir", str(outdir)]):
            code = build_nhi_corpus.main()
    assert code == 1
    assert "欄位可能對不上" in capsys.readouterr().out


def test_corpus_build_returns_zero_on_success(outdir):
    rows = [
        {
            "診療項目代碼": "01039C",
            "中文項目名稱": "腎臟移植諮詢費",
            "英文項目名稱": "Kidney transplant consultation",
            "健保支付點數": "600",
            "生效起日": "20240301",
            "生效迄日": "29101231",
            "備註": "",
        }
    ]
    with mock.patch.object(build_nhi_corpus, "get_rows", return_value=rows):
        with mock.patch.object(
            sys, "argv", ["build_nhi_corpus.py", "--only", "procedures", "--outdir", str(outdir)]
        ):
            code = build_nhi_corpus.main()
    assert code == 0
    assert (outdir / "nhi_procedures_urology.jsonl").exists()


def test_corpus_build_writes_nothing_when_one_dataset_fails(outdir, capsys):
    """半套結果不落地。

    只少一份資料集時段數不會掉到觸發 corpus_diff 段數門檻的程度（那是另一個檔案的事），
    於是排程會開出一個「安靜少了一整份資料集」的 PR。所以寫檔必須是全有全無。
    """
    rows = [
        {
            "診療項目代碼": "01039C",
            "中文項目名稱": "腎臟移植諮詢費",
            "英文項目名稱": "Kidney transplant consultation",
            "健保支付點數": "600",
            "生效起日": "20240301",
            "生效迄日": "29101231",
            "備註": "",
        }
    ]

    def get_rows(kind, from_file=None):
        if kind == "drugs":
            raise OSError("Tunnel connection failed")
        return rows

    with mock.patch.object(build_nhi_corpus, "get_rows", side_effect=get_rows):
        with mock.patch.object(sys, "argv", ["build_nhi_corpus.py", "--outdir", str(outdir)]):
            code = build_nhi_corpus.main()

    assert code == 1
    assert not (outdir / "nhi_procedures_urology.jsonl").exists(), "成功的那份也不該寫入"
    assert "部分結果不予採用" in capsys.readouterr().out


def test_rules_build_returns_nonzero_when_a_chapter_fails(tmp_path, capsys):
    """少數章節失敗時段數只掉一兩段，過得了 corpus_diff 的段數門檻——
    所以必須由建置腳本自己擋下，否則排程會開出一個安靜少了幾條給付規定的 PR。"""
    rows = [
        {
            "藥品代號": "A000001",
            "藥品英文名稱": "TAMSULOSIN",
            "藥品中文名稱": "坦舒露",
            "成分": "TAMSULOSIN",
            "ATC代碼": "G04CA02",
            "有效起日": "20240101",
            "有效迄日": "29101231",
            "給付規定章節": "1.6.3",
            "給付規定章節連結": (
                "https://info.nhi.gov.tw/api/INAE3000/INAE3000S01/getPDF"
                "?DurgFileName=1.6.3._20150201_000.pdf"
            ),
        }
    ]
    out = tmp_path / "rules.jsonl"
    with mock.patch.object(build_nhi_rules, "get_rows", return_value=rows), mock.patch.object(
        build_nhi_rules, "download", side_effect=OSError("404")
    ), mock.patch.object(build_nhi_rules.time, "sleep"):
        with mock.patch.object(sys, "argv", ["build_nhi_rules.py", "--out", str(out)]):
            code = build_nhi_rules.main()
    assert code == 1
    assert "部分結果不予採用" in capsys.readouterr().out
