"""build_nhi_corpus 的解析與篩選測試（用合成資料，不連網）。

真實資料的欄位對應請用 `python build_nhi_corpus.py --inspect` 驗證；
這裡驗的是「欄位對得上時，篩選與輸出格式是否正確」。
"""
import csv
import io
import pathlib
import sys
import zipfile

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import build_nhi_corpus as B  # noqa: E402

NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
      'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
      'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"')

DRUG_ROWS = [
    # ATC G04 泌尿科用藥 → 應收錄
    {"藥品代號": "AC12345", "藥品英文名稱": "Tamsulosin HCl", "藥品中文名稱": "坦索羅辛",
     "成分": "TAMSULOSIN HYDROCHLORIDE", "支付價": "12.5", "有效起日": "1130101",
     "有效迄日": "", "劑型": "膠囊", "ATC代碼": "G04CA02", "給付規定章節": "第9節"},
    # ATC A10 糖尿病用藥 → 應排除
    {"藥品代號": "BC99999", "藥品英文名稱": "Metformin", "藥品中文名稱": "二甲雙胍",
     "成分": "METFORMIN", "支付價": "1.2", "有效起日": "1130101",
     "有效迄日": "", "劑型": "錠劑", "ATC代碼": "A10BA02", "給付規定章節": "第2節"},
    # ATC L02 攝護腺癌 ADT → 應收錄
    {"藥品代號": "CD55555", "藥品英文名稱": "Leuprorelin", "藥品中文名稱": "柳菩林",
     "成分": "LEUPRORELIN ACETATE", "支付價": "8500", "有效起日": "1130101",
     "有效迄日": "", "劑型": "注射劑", "ATC代碼": "L02AE02", "給付規定章節": "第9節"},
]

PROC_HEADER = ["診療項目代碼", "健保支付點數", "生效起日", "生效迄日",
               "英文項目名稱", "中文項目名稱", "備註"]
PROC_ROWS = [
    ["79001B", "28500", "1140501", "", "Transurethral resection of prostate",
     "經尿道攝護腺切除術", "限攝護腺肥大符合條件者"],
    ["47029B", "12000", "1140501", "", "Total knee replacement", "全膝關節置換術", ""],
    ["79411B", "31000", "1140501", "", "Extracorporeal shock wave lithotripsy",
     "體外震波碎石術", "每次療程限一側"],
]


def _csv_bytes(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def _ods_bytes(header, rows):
    def tr(cells):
        tds = "".join(f"<table:table-cell><text:p>{c}</text:p></table:table-cell>" for c in cells)
        return f"<table:table-row>{tds}</table:table-row>"

    body = "".join(tr(r) for r in [header] + rows)
    content = (f'<?xml version="1.0"?><office:document-content {NS}><office:body>'
               f'<office:spreadsheet><table:table table:name="s">{body}</table:table>'
               f'</office:spreadsheet></office:body></office:document-content>')
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("content.xml", content)
    return b.getvalue()


# ---------- 解析 ----------

@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-8", "cp950"])
def test_csv_parsing_handles_common_encodings(encoding):
    raw = _csv_bytes(DRUG_ROWS).decode("utf-8-sig").encode(encoding)
    assert len(B.parse(raw)) == 3


def test_ods_parsing():
    rows = B.parse(_ods_bytes(PROC_HEADER, PROC_ROWS))
    assert len(rows) == 3
    assert rows[0]["中文項目名稱"] == "經尿道攝護腺切除術"


# ---------- 泌尿科篩選 ----------

def test_drugs_filtered_by_atc_code():
    docs = B.to_docs(B.parse(_csv_bytes(DRUG_ROWS)), "drugs", "測試")
    ids = [d["id"] for d in docs]
    assert ids == ["nhi-drug-AC12345", "nhi-drug-CD55555"], \
        "應收錄 G04（泌尿科用藥）與 L02（攝護腺癌 ADT），排除 A10（糖尿病）"


FALSE_POSITIVE_PROCS = [
    # 「腎上腺」含「腎」、adrenal 含 renal → 曾被誤判為泌尿科（屬內分泌外科）
    ["81001B", "40000", "1140501", "", "Adrenalectomy", "腎上腺切除術", ""],
    # 「...Testing」曾被 "testi" 子字串誤判為睪丸相關
    ["12345C", "300", "1140501", "", "Glucose Tolerance Testing", "葡萄糖耐量試驗", ""],
    # 透析屬腎臟科，且項目數量龐大會稀釋語料
    ["58001C", "3800", "1140501", "", "Hemodialysis", "血液透析", ""],
]


@pytest.mark.parametrize("row", FALSE_POSITIVE_PROCS,
                         ids=["腎上腺切除術", "葡萄糖耐量試驗", "血液透析"])
def test_known_false_positives_are_excluded(row):
    docs = B.to_docs(B.parse(_ods_bytes(PROC_HEADER, [row])), "procedures", "測試")
    assert docs == [], f"不應被判定為泌尿科：{row[5]}（{row[4]}）"


def test_adrenaline_drug_excluded_but_urologicals_kept():
    rows = [
        {"藥品代號": "EP00001", "藥品英文名稱": "Adrenaline Inj", "藥品中文名稱": "腎上腺素注射液",
         "成分": "ADRENALINE", "支付價": "20", "有效起日": "1130101", "有效迄日": "",
         "劑型": "注射劑", "ATC代碼": "C01CA24", "給付規定章節": ""},
        {"藥品代號": "TA00001", "藥品英文名稱": "Tamsulosin", "藥品中文名稱": "坦索羅辛",
         "成分": "TAMSULOSIN", "支付價": "12", "有效起日": "1130101", "有效迄日": "",
         "劑型": "膠囊", "ATC代碼": "G04CA02", "給付規定章節": "第9節"},
    ]
    ids = [d["id"] for d in B.to_docs(B.parse(_csv_bytes(rows)), "drugs", "測試")]
    assert ids == ["nhi-drug-TA00001"], "腎上腺素（急救用藥）不該被收進泌尿科語料"


def test_breast_cancer_hormone_therapy_excluded():
    """L02 整群含乳癌荷爾蒙治療，故只收 L02AE / L02BB。"""
    rows = [
        {"藥品代號": "TM00001", "藥品英文名稱": "Tamoxifen", "藥品中文名稱": "泰莫西芬",
         "成分": "TAMOXIFEN", "支付價": "5", "有效起日": "1130101", "有效迄日": "",
         "劑型": "錠劑", "ATC代碼": "L02BA01", "給付規定章節": ""},
        {"藥品代號": "BI00001", "藥品英文名稱": "Bicalutamide", "藥品中文名稱": "比卡魯胺",
         "成分": "BICALUTAMIDE", "支付價": "60", "有效起日": "1130101", "有效迄日": "",
         "劑型": "錠劑", "ATC代碼": "L02BB03", "給付規定章節": "第9節"},
    ]
    ids = [d["id"] for d in B.to_docs(B.parse(_csv_bytes(rows)), "drugs", "測試")]
    assert ids == ["nhi-drug-BI00001"], "L02BA（乳癌用 tamoxifen）不該被收進泌尿科語料"


def test_procedures_filtered_by_keyword():
    docs = B.to_docs(B.parse(_ods_bytes(PROC_HEADER, PROC_ROWS)), "procedures", "測試")
    ids = [d["id"] for d in docs]
    assert "nhi-proc-79001B" in ids and "nhi-proc-79411B" in ids
    assert "nhi-proc-47029B" not in ids, "全膝關節置換術不屬於泌尿科"


# ---------- 輸出格式 ----------

def test_output_matches_corpus_schema():
    docs = (B.to_docs(B.parse(_csv_bytes(DRUG_ROWS)), "drugs", "測試來源")
            + B.to_docs(B.parse(_ods_bytes(PROC_HEADER, PROC_ROWS)), "procedures", "測試來源"))
    for d in docs:
        assert set(d) == {"id", "source", "section", "text"}
        assert all(str(v).strip() for v in d.values())


def test_key_facts_survive_into_text():
    docs = B.to_docs(B.parse(_ods_bytes(PROC_HEADER, PROC_ROWS)), "procedures", "測試")
    turp = next(d for d in docs if d["id"] == "nhi-proc-79001B")
    for fact in ("79001B", "經尿道攝護腺切除術", "28500", "限攝護腺肥大符合條件者"):
        assert fact in turp["text"], f"'{fact}' 不應在轉換過程中遺失"


def test_ids_are_unique():
    dupes = DRUG_ROWS + [DRUG_ROWS[0]]
    docs = B.to_docs(B.parse(_csv_bytes(dupes)), "drugs", "測試")
    assert len({d["id"] for d in docs}) == len(docs)
