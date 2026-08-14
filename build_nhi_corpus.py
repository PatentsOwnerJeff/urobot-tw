"""UROBOT TW — 健保給付規範語料建置

這是本專案唯一**可以合法公開散布**的語料來源，也是相對於國外系統
（如 DKFZ UroBot）真正的差異化所在：台灣的健保給付條件。

資料來源（皆為政府資料開放平臺，授權：政府資料開放授權條款－第 1 版，可再散布與衍生，須註明出處）：

  1. 醫療服務給付項目及支付標準  https://data.gov.tw/dataset/9405
     resource id: A21030000I-D20003-004
     欄位：診療項目代碼、健保支付點數、生效起日、生效迄日、英文項目名稱、中文項目名稱、備註

  2. 健保用藥品項查詢項目檔      https://data.gov.tw/dataset/23715
     resource id: A21030000I-E41001-001
     欄位：藥品代號、藥品英文名稱、藥品中文名稱、成分、規格量、規格單位、支付價、
           有效起日、有效迄日、藥商、劑型、藥品分類、ATC代碼、給付規定章節…

用法：
  python build_nhi_corpus.py                       # 抓兩份，輸出泌尿科相關語料
  python build_nhi_corpus.py --only procedures     # 只做支付標準
  python build_nhi_corpus.py --only drugs
  python build_nhi_corpus.py --inspect             # 只印欄位與前幾筆，先看資料長怎樣
  python build_nhi_corpus.py --from-file xxx.csv --only drugs   # 用手動下載的檔案

⚠️ 第一次執行請先跑 --inspect。健保署的欄位名稱與編碼會隨版本調整，
   若欄位對不上，請把 --inspect 的輸出貼到 issue，我們再修對照表。

⚠️ 這裡產出的是「給付規定」不是「臨床指引」。給付條件 ≠ 醫療上的最佳做法，
   兩者在語料中以 source 欄位明確區分，作答時不應混淆。
"""
import argparse
import csv
import io
import json
import pathlib
import re
import sys
import urllib.request
import zipfile

API = "https://info.nhi.gov.tw/api/iode0000s01/Dataset?rId={rid}"

DATASETS = {
    "procedures": {
        "rid": "A21030000I-D20003-004",
        "name": "醫療服務給付項目及支付標準",
        "page": "https://data.gov.tw/dataset/9405",
    },
    "drugs": {
        "rid": "A21030000I-E41001-001",
        "name": "健保用藥品項查詢項目檔",
        "page": "https://data.gov.tw/dataset/23715",
    },
}

# 欄位名稱對照：健保署偶有改名，這裡列出可能的別名
FIELDS = {
    "procedures": {
        "code": ["診療項目代碼", "醫令代碼", "代碼"],
        "name_zh": ["中文項目名稱", "項目名稱", "中文名稱"],
        "name_en": ["英文項目名稱", "英文名稱"],
        "points": ["健保支付點數", "支付點數", "點數"],
        "start": ["生效起日", "有效起日"],
        "end": ["生效迄日", "有效迄日"],
        "note": ["備註", "註記"],
    },
    "drugs": {
        "code": ["藥品代號", "藥品代碼"],
        "name_zh": ["藥品中文名稱", "中文名稱"],
        "name_en": ["藥品英文名稱", "英文名稱"],
        "ingredient": ["成分"],
        "price": ["支付價", "支付價格"],
        "atc": ["ATC代碼", "ATC碼", "ATC"],
        "chapter": ["給付規定章節"],
        "form": ["劑型"],
        "start": ["有效起日", "生效起日"],
        "end": ["有效迄日", "生效迄日"],
    },
}

# 泌尿科相關關鍵字（比對中英文名稱）。寧可寬鬆，之後人工刪比漏掉好。
# 注意：不含「透析」—— 台灣血液／腹膜透析屬腎臟科，且項目數量龐大會稀釋語料。
UROLOGY_KEYWORDS_ZH = [
    "泌尿", "腎", "輸尿管", "膀胱", "尿道", "尿路", "攝護腺", "前列腺",
    "睪丸", "陰囊", "陰莖", "精索", "精囊", "輸精管", "包皮",
    "碎石", "尿失禁", "排尿", "導尿", "血尿", "尿液", "尿動力",
    "腎盂", "腎臟", "膀胱鏡", "腎鏡", "輸尿管鏡",
]
UROLOGY_KEYWORDS_EN = [
    "urolog", "renal", "nephr", "ureter", "bladder", "vesic", "urethr",
    "prostat", "testis", "testicular", "scrot", "penil", "penis",
    "spermat", "vas deferens",
    "lithotrip", "cystoscop", "urodynamic", "urinary", "urine", "TURP", "TURBT",
]

# 排除詞：避免子字串誤判。
#   「腎上腺 / adrenal」屬內分泌外科，但會被「腎」「renal」命中（adrenal 含 renal）
#   「腎上腺素 / adrenaline」是急救用藥，會從藥品「成分」欄被撈進來
EXCLUDE_KEYWORDS = ["腎上腺", "adrenal", "epinephrin"]

# ATC 代碼：
#   G04   = Urologicals（泌尿科用藥：α阻斷劑、5ARI、抗蕈毒鹼、PDE5i…）
#   L02AE = GnRH 促效劑（攝護腺癌 ADT）
#   L02BB = 抗雄性素（攝護腺癌）
# 刻意不用整個 L02：L02 還包含乳癌荷爾蒙治療（tamoxifen、letrozole 等）。
UROLOGY_ATC_PREFIXES = ("G04", "L02AE", "L02BB")


# ---------------- 下載與解析 ----------------

def fetch(rid, timeout=180):
    url = API.format(rid=rid)
    print(f"下載中：{url}")
    req = urllib.request.Request(url, headers={"User-Agent": "urobot-tw/0.1 (+https://github.com/PatentsOwnerJeff/urobot-tw)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse(raw: bytes):
    """回傳 list[dict]。自動判斷 ODS（zip）或 CSV，並嘗試多種中文編碼。"""
    if raw[:2] == b"PK":
        return _parse_ods(raw)
    return _parse_csv(raw)


def _parse_csv(raw: bytes):
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp950", "big5hkscs"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise SystemExit("無法判斷檔案編碼。請用 --from-file 手動轉檔後再試。")
    return list(csv.DictReader(io.StringIO(text)))


def _parse_ods(raw: bytes):
    """ODS 就是含 content.xml 的 zip，用標準庫解析，不必額外裝 odfpy。"""
    import xml.etree.ElementTree as ET

    ns = {
        "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    }
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        root = ET.fromstring(z.read("content.xml"))

    rows = []
    table = root.find(".//table:table", ns)
    if table is None:
        raise SystemExit("ODS 中找不到工作表。")

    for tr in table.findall("table:table-row", ns):
        cells = []
        for tc in tr.findall("table:table-cell", ns):
            repeat = int(tc.get(f"{{{ns['table']}}}number-columns-repeated", 1))
            value = " ".join(
                "".join(p.itertext()) for p in tc.findall("text:p", ns)
            ).strip()
            cells.extend([value] * min(repeat, 64))  # 防禦：末尾常有超大 repeat
        while cells and not cells[-1]:
            cells.pop()
        if cells:
            rows.append(cells)

    if not rows:
        return []
    header, *body = rows
    return [dict(zip(header, r)) for r in body]


# ---------------- 欄位對應與篩選 ----------------

def pick(row, aliases):
    for a in aliases:
        if a in row and str(row[a]).strip():
            return str(row[a]).strip()
    return ""


def is_urology(row, kind):
    fields = FIELDS[kind]
    zh = pick(row, fields["name_zh"])
    en = pick(row, fields["name_en"]).lower()

    if kind == "drugs":
        atc = pick(row, fields["atc"]).upper()
        if atc.startswith(UROLOGY_ATC_PREFIXES):
            return True          # ATC 命中最可靠，直接收，不受排除詞影響
        en += " " + pick(row, fields["ingredient"]).lower()

    blob = f"{zh} {en}"
    if any(k.lower() in blob.lower() for k in EXCLUDE_KEYWORDS):
        return False

    return (any(k in zh for k in UROLOGY_KEYWORDS_ZH)
            or any(k.lower() in en for k in UROLOGY_KEYWORDS_EN))


def to_docs(rows, kind, source_note):
    fields = FIELDS[kind]
    docs = []
    for i, row in enumerate(r for r in rows if is_urology(r, kind)):
        code = pick(row, fields["code"])
        zh = pick(row, fields["name_zh"])
        en = pick(row, fields["name_en"])
        if not (code and (zh or en)):
            continue

        if kind == "procedures":
            parts = [f"診療項目代碼 {code}：{zh}"]
            if en:
                parts.append(f"（英文名稱：{en}）")
            pts = pick(row, fields["points"])
            if pts:
                parts.append(f"健保支付點數 {pts} 點。")
            period = " 至 ".join(x for x in (pick(row, fields["start"]), pick(row, fields["end"])) if x)
            if period:
                parts.append(f"生效期間 {period}。")
            note = pick(row, fields["note"])
            if note:
                parts.append(f"備註：{note}")
            section = f"健保給付／診療項目／{zh or en}"
        else:
            parts = [f"藥品代號 {code}：{zh or en}"]
            if zh and en:
                parts.append(f"（{en}）")
            ing = pick(row, fields["ingredient"])
            if ing:
                parts.append(f"成分 {ing}。")
            form = pick(row, fields["form"])
            if form:
                parts.append(f"劑型 {form}。")
            atc = pick(row, fields["atc"])
            if atc:
                parts.append(f"ATC 代碼 {atc}。")
            price = pick(row, fields["price"])
            if price:
                parts.append(f"健保支付價 {price} 元。")
            chapter = pick(row, fields["chapter"])
            if chapter:
                parts.append(f"適用給付規定章節：{chapter}。")
            period = " 至 ".join(x for x in (pick(row, fields["start"]), pick(row, fields["end"])) if x)
            if period:
                parts.append(f"給付期間 {period}。")
            section = f"健保給付／藥品／{zh or en}"

        docs.append({
            "id": f"nhi-{'proc' if kind == 'procedures' else 'drug'}-{re.sub(r'[^A-Za-z0-9]', '', code) or i:0>6}",
            "source": source_note,
            "section": section,
            "text": " ".join(parts),
        })

    # id 去重（同代碼多筆時保留第一筆）
    seen, unique = set(), []
    for d in docs:
        if d["id"] not in seen:
            seen.add(d["id"])
            unique.append(d)
    return unique


# ---------------- 主流程 ----------------

def get_rows(kind, from_file):
    if from_file:
        return parse(pathlib.Path(from_file).read_bytes())
    return parse(fetch(DATASETS[kind]["rid"]))


def inspect(rows, kind):
    print(f"\n總筆數：{len(rows)}")
    if not rows:
        return
    print(f"欄位（{len(rows[0])}）：{list(rows[0])}\n")
    for row in rows[:3]:
        print(json.dumps(row, ensure_ascii=False, indent=2)[:900])
        print("-" * 40)

    missing = {k: v for k, v in FIELDS[kind].items() if not pick(rows[0], v)}
    if missing:
        print(f"\n⚠️ 下列欄位對應不到，請開 issue 附上上面的欄位清單：\n   {missing}")
    else:
        print("\n✅ 所有預期欄位都對應成功。")


def main():
    ap = argparse.ArgumentParser(description="建置健保給付規範語料（政府開放資料）")
    ap.add_argument("--only", choices=sorted(DATASETS), help="只處理其中一份資料集")
    ap.add_argument("--from-file", help="用手動下載的檔案，不連網")
    ap.add_argument("--inspect", action="store_true", help="只檢視欄位與樣本，不產語料")
    ap.add_argument("--outdir", default="corpus", help="輸出目錄（預設 corpus/）")
    args = ap.parse_args()

    kinds = [args.only] if args.only else list(DATASETS)
    if args.from_file and not args.only:
        ap.error("--from-file 必須搭配 --only 指定是哪一份資料集")

    for kind in kinds:
        meta = DATASETS[kind]
        print(f"\n{'=' * 60}\n{meta['name']}（{meta['page']}）\n{'=' * 60}")
        try:
            rows = get_rows(kind, args.from_file)
        except Exception as e:
            print(f"❌ 取得失敗：{type(e).__name__}: {e}")
            print(f"   可改為手動下載後執行：\n"
                  f"   python build_nhi_corpus.py --only {kind} --from-file 下載的檔案")
            continue

        if args.inspect:
            inspect(rows, kind)
            continue

        source = (f"{meta['name']}（衛生福利部中央健康保險署，"
                  f"政府資料開放授權條款第1版；取自 {meta['page']}）")
        docs = to_docs(rows, kind, source)
        print(f"總筆數 {len(rows)} → 判定為泌尿科相關 {len(docs)} 筆")

        if not docs:
            print("⚠️ 沒有篩出任何資料，欄位可能對不上。請執行 --inspect 檢查。")
            continue

        out = pathlib.Path(args.outdir) / f"nhi_{kind}_urology.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in docs) + "\n",
                       encoding="utf-8")
        print(f"已寫入：{out}")
        print(f"樣本：{docs[0]['text'][:160]}…")

    if not args.inspect:
        print("\n下一步：python ingest.py   # 重建索引")


if __name__ == "__main__":
    sys.exit(main())
