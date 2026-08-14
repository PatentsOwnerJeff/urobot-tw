"""build_nhi_corpus 的解析與篩選測試（用合成資料，不連網）。

真實資料的欄位對應請用 `python build_nhi_corpus.py --inspect` 驗證；
這裡驗的是「欄位對得上時，篩選與輸出格式是否正確」。
"""
import csv
import datetime
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

# 以下每一筆都是實際跑真實健保資料時撈到的誤判，逐一釘住避免回歸。
FALSE_POSITIVE_PROCS = [
    # 「腎上腺」含「腎」、adrenal 含 renal → 屬內分泌外科
    ["81001B", "40000", "1140501", "", "Adrenalectomy", "腎上腺切除術", ""],
    # 「...Testing」曾被 "testi" 子字串誤判為睪丸相關
    ["12345C", "300", "1140501", "", "Glucose Tolerance Testing", "葡萄糖耐量試驗", ""],
    # 透析屬腎臟科，且項目數量龐大會稀釋語料
    ["58001C", "3800", "1140501", "", "Hemodialysis", "血液透析", ""],
    # gall bladder 含 bladder → 實測撈進腹部超音波
    ["19009C", "800", "1140501", "",
     "Abdominal echography (liver, gall bladder, pancreas, spleen)", "腹部超音波", ""],
    # 前列腺「素」是 prostaglandin，與前列腺無關
    ["99999C", "100", "1140501", "", "Dinoprostone administration", "前列腺素給藥", ""],
    # TURPENTINE 松節油 曾被 "TURP" 子字串命中
    ["88888C", "50", "1140501", "", "Turpentine liniment application", "松節油塗敷", ""],
    # Serenal（鎮靜劑商品名）含 renal
    ["77777C", "60", "1140501", "", "Serenal capsule administration", "心益膠囊給藥", ""],
    # taurine 含 urine
    ["66666C", "70", "1140501", "", "Taurine level measurement", "牛磺酸測定", ""],
]


@pytest.mark.parametrize("row", FALSE_POSITIVE_PROCS, ids=[r[5] for r in FALSE_POSITIVE_PROCS])
def test_known_false_positives_are_excluded(row):
    docs = B.to_docs(B.parse(_ods_bytes(PROC_HEADER, [row])), "procedures", "測試")
    assert docs == [], f"不應被判定為泌尿科：{row[5]}（{row[4]}）"


TRUE_POSITIVE_PROCS = [
    ["79001B", "28500", "1140501", "", "Transurethral resection of prostate", "經尿道攝護腺切除術", ""],
    ["79411B", "31000", "1140501", "", "Extracorporeal shock wave lithotripsy", "體外震波碎石術", ""],
    ["79028B", "9000", "1140501", "", "TURBT", "經尿道膀胱腫瘤切除術", ""],
    ["00000C", "500", "1140501", "", "Renal ultrasonography", "", ""],
]


@pytest.mark.parametrize("row", TRUE_POSITIVE_PROCS, ids=[r[5] or r[4] for r in TRUE_POSITIVE_PROCS])
def test_true_positives_still_kept(row):
    """修掉誤判之後，真正該收的項目不能跟著被排除。"""
    docs = B.to_docs(B.parse(_ods_bytes(PROC_HEADER, [row])), "procedures", "測試")
    assert len(docs) == 1, f"應被判定為泌尿科：{row[5] or row[4]}"


# ---------- 藥品：只認 ATC，不比對品名 ----------

def _drug(code, zh, en, ingredient, atc):
    return {"藥品代號": code, "藥品英文名稱": en, "藥品中文名稱": zh, "成分": ingredient,
            "支付價": "10", "有效起日": "1130101", "有效迄日": "", "劑型": "錠劑",
            "ATC代碼": atc, "給付規定章節": ""}


DRUG_CASES = [
    # (應否收錄, 藥品)
    (True, _drug("D1", "坦索羅辛", "Tamsulosin", "TAMSULOSIN", "G04CA02")),        # 泌尿科用藥
    (True, _drug("D2", "柳菩林", "Leuprorelin", "LEUPRORELIN", "L02AE02")),        # 攝護腺癌 ADT
    (True, _drug("D3", "比卡魯胺", "Bicalutamide", "BICALUTAMIDE", "L02BB03")),     # 抗雄性素
    (True, _drug("D4", "康腎膠囊", "Pipemidic", "PIPEMIDIC ACID", "J01MB04")),      # 尿路抗菌劑
    (True, _drug("D5", "睪固酮", "Testosterone", "TESTOSTERONE", "G03BA03")),       # 男性性腺功能低下
    (False, _drug("D6", "泰莫西芬", "Tamoxifen", "TAMOXIFEN", "L02BA01")),          # 乳癌，非泌尿
    (False, _drug("D7", "腎上腺素注射液", "Adrenaline", "ADRENALINE", "C01CA24")),   # 急救用藥
    # 以下三筆品名/成分含泌尿相關字串，但 ATC 不是泌尿科 → 必須排除
    (False, _drug("D8", "心益膠囊", "Serenal Capsules", "OXAZOLAM", "N05BA91")),     # Se-renal
    (False, _drug("D9", "腎寧錠", "Nephrolan", "CHONDROITIN SULFATE", "V06DX")),     # 商品名含 Nephro
    (False, _drug("D10", "可氣爽注射液", "Kisan", "TURPENTINE DER.", "R03DA51")),     # TURP-entine
    (False, _drug("D11", "保樂胎蒙戊錠(前列腺素)", "Dinoprostone", "DINOPROSTONE", "G02AD02")),
]


@pytest.mark.parametrize("expected,row", DRUG_CASES,
                         ids=[f"{'收' if e else '排'}-{r['藥品中文名稱']}" for e, r in DRUG_CASES])
def test_drug_selection_is_atc_only(expected, row):
    docs = B.to_docs(B.parse(_csv_bytes([row])), "drugs", "測試")
    assert bool(docs) is expected, (
        f"{row['藥品中文名稱']}（ATC={row['ATC代碼']}）"
        f"{'應' if expected else '不應'}被收錄"
    )


def test_drugs_filtered_by_atc_code():
    docs = B.to_docs(B.parse(_csv_bytes(DRUG_ROWS)), "drugs", "測試")
    ids = [d["id"] for d in docs]
    assert ids == ["nhi-drug-G04CA02-TAMSULOSIN", "nhi-drug-L02AE02-LEUPRORELIN"], \
        "應收錄 G04（泌尿科用藥）與 L02AE（攝護腺癌 ADT），排除 A10（糖尿病）"


def test_procedures_filtered_by_keyword():
    docs = B.to_docs(B.parse(_ods_bytes(PROC_HEADER, PROC_ROWS)), "procedures", "測試")
    ids = [d["id"] for d in docs]
    assert "nhi-proc-79001B" in ids and "nhi-proc-79411B" in ids
    assert "nhi-proc-47029B" not in ids, "全膝關節置換術不屬於泌尿科"


# ---------- 有效期間（法遵重點） ----------

@pytest.mark.parametrize("raw,expected", [
    ("1130101", datetime.date(2024, 1, 1)),    # 民國 7 碼
    ("980930", datetime.date(2009, 9, 30)),    # 民國 6 碼
    ("2024/03/01", datetime.date(2024, 3, 1)),  # 西元帶斜線
    ("2910/12/31", datetime.date(2910, 12, 31)),  # 「無迄日」哨兵值
    ("", None),
    ("abc", None),
    ("1139999", None),                          # 不合法月日
])
def test_parse_nhi_date(raw, expected):
    assert B.parse_nhi_date(raw) == expected


TODAY = datetime.date(2026, 8, 15)


def test_expired_drugs_excluded_by_default():
    """實測 92% 藥品品項的給付期間已過期，最舊失效於民國 98 年。
    把失效價格當現行資訊提供給臨床端是真實風險，必須預設排除。"""
    rows = [
        _drug("EXP1", "舊品項A", "Old A", "TAMSULOSIN", "G04CA02"),
        _drug("CUR1", "現行品項", "Current", "TAMSULOSIN", "G04CA02"),
    ]
    rows[0]["有效迄日"] = "980930"    # 2009 年就失效
    rows[1]["有效迄日"] = ""          # 無迄日 = 現行

    assert B.is_current(rows[0], "drugs", TODAY) is False
    assert B.is_current(rows[1], "drugs", TODAY) is True

    docs = B.to_docs(B.parse(_csv_bytes(rows)), "drugs", "測試")
    assert len(docs) == 1
    assert "1 個品項" in docs[0]["text"], "失效品項不應被計入品項數"


def test_include_expired_flag_restores_them():
    rows = [_drug("EXP1", "舊品項", "Old", "TAMSULOSIN", "G04CA02"),
            _drug("CUR1", "現行品項", "Cur", "TAMSULOSIN", "G04CA02")]
    rows[0]["有效迄日"] = "980930"
    rows[1]["有效迄日"] = ""
    docs = B.to_docs(B.parse(_csv_bytes(rows)), "drugs", "測試", include_expired=True)
    assert "2 個品項" in docs[0]["text"]


def test_expired_procedures_excluded():
    row = ["79001B", "28500", "2010/01/01", "2015/12/31", "TURP", "經尿道攝護腺切除術", ""]
    assert B.to_docs(B.parse(_ods_bytes(PROC_HEADER, [row])), "procedures", "測試") == []


def test_sentinel_end_date_treated_as_current():
    """健保支付標準用 2910/12/31 表示「無迄日」，不可被當成過期。"""
    row = ["79001B", "28500", "2024/03/01", "2910/12/31", "TURP", "經尿道攝護腺切除術", ""]
    assert len(B.to_docs(B.parse(_ods_bytes(PROC_HEADER, [row])), "procedures", "測試")) == 1


# ---------- 藥品聚合 ----------

@pytest.mark.parametrize("raw,expected", [
    ("TAMSULOSIN HCL .2 MG", "TAMSULOSIN"),
    ("LEUPRORELIN ACETATE 3.75MG", "LEUPRORELIN"),
    ("PIPEMIDIC ACID (TRIHYDRATE) 250 MG", "PIPEMIDIC ACID"),
    ("BICALUTAMIDE 50 MG", "BICALUTAMIDE"),
])
def test_ingredient_normalisation(raw, expected):
    assert B._norm_ingredient(raw) == expected


def test_drugs_aggregated_by_ingredient():
    """同成分不同廠牌應合併成一段，否則幾十段近乎相同的內容會灌爆 BM25。"""
    rows = [_drug(f"T{i}", f"甲廠牌{i}", f"Brand{i}", "TAMSULOSIN HCL .2 MG", "G04CA02")
            for i in range(12)]
    rows.append(_drug("B1", "比卡魯胺", "Bica", "BICALUTAMIDE 50 MG", "L02BB03"))
    docs = B.to_docs(B.parse(_csv_bytes(rows)), "drugs", "測試")

    assert len(docs) == 2, f"13 個品項、2 種成分 → 應產出 2 段，實際 {len(docs)}"
    tam = next(d for d in docs if "TAMSULOSIN" in d["id"])
    assert "12 個品項" in tam["text"]
    assert "G04CA02" in tam["text"]


def test_price_range_reported():
    rows = [_drug("P1", "甲", "A", "TAMSULOSIN", "G04CA02"),
            _drug("P2", "乙", "B", "TAMSULOSIN", "G04CA02")]
    rows[0]["支付價"], rows[1]["支付價"] = "7.4", "15.2"
    text = B.to_docs(B.parse(_csv_bytes(rows)), "drugs", "測試")[0]["text"]
    assert "7.4–15.2" in text


def test_zero_price_not_reported_as_free():
    """支付價 0 代表未定價／已取消，不是免費。列成「0 元起」會誤導臨床端。"""
    rows = [_drug("Z1", "甲", "A", "TAMSULOSIN", "G04CA02"),
            _drug("Z2", "乙", "B", "TAMSULOSIN", "G04CA02")]
    rows[0]["支付價"], rows[1]["支付價"] = "0", "11.8"
    text = B.to_docs(B.parse(_csv_bytes(rows)), "drugs", "測試")[0]["text"]
    assert "0–11.8" not in text
    assert "健保支付價 11.8 元" in text


def test_all_zero_prices_omits_price_entirely():
    rows = [_drug("Z1", "甲", "A", "TAMSULOSIN", "G04CA02")]
    rows[0]["支付價"] = "0"
    text = B.to_docs(B.parse(_csv_bytes(rows)), "drugs", "測試")[0]["text"]
    assert "支付價" not in text


# ---------- 法遵：不得夾帶自撰醫療內容 ----------

def test_drug_entries_carry_disclaimer():
    """給付資料不等於臨床適應症建議，每一段都必須帶這句話。"""
    docs = B.to_docs(B.parse(_csv_bytes(DRUG_ROWS)), "drugs", "測試")
    assert docs
    for d in docs:
        assert "非臨床適應症或療效建議" in d["text"]


FORBIDDEN_CLINICAL_WORDS = ["適應症為", "建議用於", "第一線", "療效", "可治療", "應使用"]


def test_drug_entries_contain_no_authored_clinical_claims():
    """藥品語料只能由健保署欄位組成，不得出現本專案自行撰寫的臨床主張。"""
    docs = B.to_docs(B.parse(_csv_bytes(DRUG_ROWS)), "drugs", "測試")
    for d in docs:
        body = d["text"].replace(B.DRUG_DISCLAIMER, "")
        for word in FORBIDDEN_CLINICAL_WORDS:
            assert word not in body, f"{d['id']} 疑似含自撰臨床主張：「{word}」"


def test_source_attribution_is_preserved():
    """政府資料開放授權條款第 1 版要求註明出處。"""
    docs = B.to_docs(B.parse(_csv_bytes(DRUG_ROWS)), "drugs",
                     "健保用藥品項查詢項目檔（衛生福利部中央健康保險署，"
                     "政府資料開放授權條款第1版；資料擷取日期 2026-08-15）")
    for d in docs:
        assert "中央健康保險署" in d["source"]
        assert "政府資料開放授權條款" in d["source"]
        assert "資料擷取日期" in d["source"]


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
