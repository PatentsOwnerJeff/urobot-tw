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
import collections
import csv
import datetime
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
# 英文比對一律加字界（\b），否則子字串會大量誤判。實測踩過的坑：
#   renal   → Se|renal（心益膠囊，鎮靜劑）        118 筆
#   urine   → ta|urine、p|urine                   81 筆
#   nephr   → Nephr|o- 開頭的商品名                16 筆
# 「字首比對」：允許 nephrectomy / nephrolithiasis 這類衍生字
UROLOGY_EN_PREFIXES = [
    "urolog", "renal", "nephr", "ureter", "bladder", "vesic", "urethr",
    "prostat", "testis", "testicular", "scrot", "penil",
    "spermat", "lithotrip", "cystoscop", "urodynamic", "urinary",
]
# 「完整單字比對」：縮寫與短字，字首比對會誤判（TURP → TURPENTINE 松節油）
UROLOGY_EN_WORDS = ["TURP", "TURBT", "penis", "urine", "vas deferens"]

# 排除詞（子字串比對，優先於收錄判斷）：
#   腎上腺 / adrenal      → 屬內分泌外科；adrenal 含 renal，且「腎上腺」含「腎」
#   前列腺素 / prostaglandin → 與「前列腺」是完全不同的東西（dinoprostone 用於引產）
#   gall bladder          → 膽囊；含 bladder，會撈進腹部超音波等項目
EXCLUDE_KEYWORDS = [
    "腎上腺", "adrenal", "epinephrin",
    "前列腺素", "prostaglandin", "dinoprost", "alprostadil",
    "gall bladder", "gallbladder", "膽囊",
]

# 藥品一律只看 ATC 代碼，不比對品名。
# 理由：藥品中文名是行銷名稱（「康腎膠囊」「心益膠囊」），與適應症無必然關係，
#       實測用品名比對會撈進 R03 呼吸道用藥 85 筆、R05 止咳藥 44 筆。
#   G04   Urologicals（α阻斷劑、5ARI、抗蕈毒鹼、PDE5i…）
#   G03B  Androgens（睪固酮補充，男性性腺功能低下）
#   L02AE GnRH 促效劑 ／ L02BB 抗雄性素（攝護腺癌 ADT）
#         刻意不用整個 L02：L02 尚包含乳癌荷爾蒙治療（tamoxifen、letrozole）
#   J01MB 其他喹諾酮類（pipemidic acid 等尿路抗菌劑）
#   J01XE 呋喃類（nitrofurantoin，單純性泌尿道感染第一線）
# 這是精準優先的取捨，會漏掉一些跨科用藥；要放寬請自行增列。
UROLOGY_ATC_PREFIXES = ("G04", "G03B", "L02AE", "L02BB", "J01MB", "J01XE")


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


def _en_matches(text):
    """英文比對一律加字界，避免 Serenal→renal、TURPENTINE→TURP 這類子字串誤判。"""
    low = text.lower()
    return (any(re.search(r"\b" + re.escape(k), low) for k in UROLOGY_EN_PREFIXES)
            or any(re.search(r"\b" + re.escape(k.lower()) + r"\b", low)
                   for k in UROLOGY_EN_WORDS))


def is_urology(row, kind):
    fields = FIELDS[kind]

    # 藥品：只認 ATC 代碼。品名是行銷名稱，比對它只會製造誤判。
    if kind == "drugs":
        return pick(row, fields["atc"]).upper().startswith(UROLOGY_ATC_PREFIXES)

    # 診療項目：比對中英文名稱（英文常為空，中文為主）
    zh = pick(row, fields["name_zh"])
    en = pick(row, fields["name_en"])
    blob = f"{zh} {en}".lower()

    if any(k.lower() in blob for k in EXCLUDE_KEYWORDS):
        return False

    return any(k in zh for k in UROLOGY_KEYWORDS_ZH) or _en_matches(en)


# ---------------- 有效期間 ----------------
# ⚠️ 法遵重點：健保開放資料是「歷史檔」，含大量已失效的品項。
# 實測 719 段泌尿科藥品語料中有 660 段（92%）給付期間已過期，最舊的失效於民國 98 年。
# 把過期價格與給付條件當成現行資訊提供給臨床端，是真實的風險，故預設一律排除。

def parse_nhi_date(s):
    """健保資料的日期有兩種格式，回傳 datetime.date 或 None。
       藥品：民國 7 碼／6 碼，如 1130101、980930
       診療項目：西元帶斜線，如 2024/03/01（2910/12/31 為「無迄日」哨兵值）
    """
    s = (s or "").strip()
    if not s:
        return None
    if "/" in s or "-" in s:
        parts = re.split(r"[/-]", s)
        if len(parts) != 3:
            return None
        try:
            y, m, d = (int(p) for p in parts)
        except ValueError:
            return None
    else:
        if not s.isdigit() or len(s) not in (6, 7):
            return None
        y, m, d = int(s[:-4]) + 1911, int(s[-4:-2]), int(s[-2:])
    try:
        return datetime.date(y, m, d)
    except ValueError:
        return None


def is_current(row, kind, today=None):
    """迄日已過 → 視為失效。無迄日或無法判讀 → 視為現行。"""
    today = today or datetime.date.today()
    end = parse_nhi_date(pick(row, FIELDS[kind]["end"]))
    return end is None or end >= today


def to_docs(rows, kind, source_note, include_expired=False):
    fields = FIELDS[kind]

    rows = [r for r in rows if is_urology(r, kind)]
    if not include_expired:
        rows = [r for r in rows if is_current(r, kind)]

    if kind == "drugs":
        return _aggregate_drugs(rows, fields, source_note)

    docs = []
    for i, row in enumerate(rows):
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

        docs.append({
            "id": f"nhi-proc-{re.sub(r'[^A-Za-z0-9]', '', code) or i:0>6}",
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


# ---------------- 藥品：按成分聚合 ----------------
# 為什麼要聚合：實測 719 段藥品語料只對應 55 種成分，92% 是「同成分不同廠牌」。
# 逐品項建語料有兩個壞處：
#   1. 幾十段幾乎一樣的內容會灌爆 BM25 分數，把真正的臨床指引擠掉
#   2. 單一品項的敘述（「替你坦舒持續釋放膠囊0.2毫克」）與臨床提問對不上
# 聚合後每個成分一段，資訊密度高、也不會重複。
#
# ⚠️ 法遵重點：以下所有欄位都直接來自健保署資料集，本專案不添加任何
#    自行撰寫的適應症、療效或用法敘述。給付資料 ≠ 臨床適應症建議。

DRUG_DISCLAIMER = ("以上為健保給付行政資料，非臨床適應症或療效建議；"
                   "實際給付範圍與價格以健保署最新公告為準。")


def _norm_ingredient(text):
    """成分欄形如 'TAMSULOSIN HCL .2 MG'，取到第一個數字或劑量單位前為止。"""
    s = (text or "").strip().upper()
    s = re.split(r"[0-9(]", s)[0]
    s = re.sub(r"\b(HCL|HYDROCHLORIDE|SODIUM|ACETATE|CITRATE|SUCCINATE|TARTRATE|"
               r"MALEATE|SULFATE|SULPHATE|MESYLATE|FUMARATE|TRIHYDRATE|MONOHYDRATE|"
               r"ANHYDROUS|BASE|MG|ML|MCG|G)\b", " ", s)
    return re.sub(r"[\s,.\-]+", " ", s).strip()


def _aggregate_drugs(rows, fields, source_note):
    groups = collections.OrderedDict()
    for row in rows:
        atc = pick(row, fields["atc"]).upper()
        ing = _norm_ingredient(pick(row, fields["ingredient"])) or pick(row, fields["name_en"]).upper()
        if not (atc and ing):
            continue
        groups.setdefault((atc, ing), []).append(row)

    docs = []
    for (atc, ing), items in groups.items():
        # 支付價為 0 代表未定價／已取消，不是「免費」，列出來會誤導臨床端
        prices = sorted(
            {v for v in (float(p) for p in (pick(r, fields["price"]) for r in items)
                         if re.fullmatch(r"\d+(\.\d+)?", p or ""))
             if v > 0})
        forms = sorted({pick(r, fields["form"]) for r in items if pick(r, fields["form"])})
        chapters = sorted({pick(r, fields["chapter"]) for r in items if pick(r, fields["chapter"])})
        names = [pick(r, fields["name_zh"]) or pick(r, fields["name_en"]) for r in items]
        names = [n for n in dict.fromkeys(names) if n]

        parts = [f"成分 {ing}（ATC 代碼 {atc}）。",
                 f"健保現行收載 {len(items)} 個品項。"]
        if names:
            shown = "、".join(names[:5])
            parts.append(f"品項例如：{shown}{'等。' if len(names) > 5 else '。'}")
        if forms:
            parts.append(f"劑型：{'、'.join(forms[:6])}。")
        if prices:
            parts.append(f"健保支付價 {prices[0]:g} 元。" if len(prices) == 1
                         else f"健保支付價區間 {prices[0]:g}–{prices[-1]:g} 元。")
        if chapters:
            parts.append(f"適用給付規定章節：{'、'.join(chapters[:4])}。")
        parts.append(DRUG_DISCLAIMER)

        slug = re.sub(r"[^A-Z0-9]+", "-", ing).strip("-")[:28]
        docs.append({
            "id": f"nhi-drug-{atc}-{slug}",
            "source": source_note,
            "section": f"健保給付／藥品／{ing}",
            "text": " ".join(parts),
        })

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

    # 判斷「欄位存在」而非「第一筆有值」—— 例如支付標準的第一筆沒有英文名稱，
    # 但欄位本身是存在的。
    columns = set(rows[0])
    missing, empty = {}, {}
    for key, aliases in FIELDS[kind].items():
        matched = [a for a in aliases if a in columns]
        if not matched:
            missing[key] = aliases
        elif not any(pick(r, aliases) for r in rows[:200]):
            empty[key] = matched

    if missing:
        print(f"\n❌ 下列欄位對應不到，請開 issue 附上上面的欄位清單：\n   {missing}")
    if empty:
        print(f"\n⚠️ 下列欄位存在但前 200 筆都是空的，請確認是否正常：\n   {empty}")
    if not missing and not empty:
        print("\n✅ 所有預期欄位都對應成功且有資料。")


def main():
    ap = argparse.ArgumentParser(description="建置健保給付規範語料（政府開放資料）")
    ap.add_argument("--only", choices=sorted(DATASETS), help="只處理其中一份資料集")
    ap.add_argument("--from-file", help="用手動下載的檔案，不連網")
    ap.add_argument("--inspect", action="store_true", help="只檢視欄位與樣本，不產語料")
    ap.add_argument("--outdir", default="corpus", help="輸出目錄（預設 corpus/）")
    ap.add_argument("--include-expired", action="store_true",
                    help="連給付期間已過期的項目也收錄（僅供研究用，"
                         "產出的語料不得用於臨床參考）")
    args = ap.parse_args()

    if args.include_expired:
        print("⚠️  已啟用 --include-expired：產出的語料含失效的給付價格與條件，"
              "不得作為現行健保給付依據。\n")

    kinds = [args.only] if args.only else list(DATASETS)
    if args.from_file and not args.only:
        ap.error("--from-file 必須搭配 --only 指定是哪一份資料集")

    # 失敗必須反映在離開碼上。互動使用時看得到 ❌，但排程（nhi-refresh.yml）看不到——
    # 若這裡回 0，抓取全失敗會被當成「資料沒變動」，於是月復一月安靜地不更新，
    # 而沒有任何人會發現語料早就過期了。
    failed = []
    pending = []          # [(輸出路徑, docs)]，全部成功才落地

    for kind in kinds:
        meta = DATASETS[kind]
        print(f"\n{'=' * 60}\n{meta['name']}（{meta['page']}）\n{'=' * 60}")
        try:
            rows = get_rows(kind, args.from_file)
        except Exception as e:
            print(f"❌ 取得失敗：{type(e).__name__}: {e}")
            print(f"   可改為手動下載後執行：\n"
                  f"   python build_nhi_corpus.py --only {kind} --from-file 下載的檔案")
            failed.append(kind)
            continue

        if args.inspect:
            inspect(rows, kind)
            continue

        fetched = datetime.date.today().isoformat()
        source = (f"{meta['name']}（衛生福利部中央健康保險署，"
                  f"政府資料開放授權條款第1版；取自 {meta['page']}，"
                  f"資料擷取日期 {fetched}"
                  f"{'；含已失效項目' if args.include_expired else ''}）")

        urology = [r for r in rows if is_urology(r, kind)]
        current = [r for r in urology if is_current(r, kind)]
        docs = to_docs(rows, kind, source, include_expired=args.include_expired)

        print(f"總筆數 {len(rows)} → 泌尿科相關 {len(urology)} 筆"
              f" → 現行有效 {len(current)} 筆"
              f"（排除失效 {len(urology) - len(current)} 筆）")
        if kind == "drugs":
            print(f"  按成分聚合後：{len(docs)} 段語料")
        else:
            print(f"  產出語料：{len(docs)} 段")

        if not docs:
            print("⚠️ 沒有篩出任何資料，欄位可能對不上。請執行 --inspect 檢查。")
            failed.append(kind)
            continue

        # 先擱著不寫。有任何一份失敗就整批不落地——半套結果只會少掉幾段，
        # 過得了 corpus_diff.py 的段數門檻，於是排程開出一個「安靜少了一整份資料集」的 PR。
        out = pathlib.Path(args.outdir) / f"nhi_{kind}_urology.jsonl"
        pending.append((out, docs))
        print(f"樣本：{docs[0]['text'][:160]}…")

    if failed:
        print(f"\n❌ 下列資料集未能建置：{'、'.join(failed)}")
        if pending:
            print(f"   部分結果不予採用，{len(pending)} 份成功的資料集也不會寫入。")
            print(f"   要單獨重建成功的那份，請用 --only 指定。")
        return 1

    for out, docs in pending:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in docs) + "\n",
                       encoding="utf-8")
        print(f"已寫入：{out}（{len(docs)} 段）")

    if not args.inspect:
        print("\n下一步：python ingest.py   # 重建索引")
    return 0


if __name__ == "__main__":
    sys.exit(main())
