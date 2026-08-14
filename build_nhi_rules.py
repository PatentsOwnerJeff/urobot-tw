"""UROBOT TW — 健保藥品給付規定條文語料建置

為什麼需要這支程式：
  健保用藥品項檔只有「章節編號」（如 5.2.2.1），沒有條文內容。
  但條文本身才是臨床決策要的東西 ——

      5.2.2.1 Finasteride（如 Proscar）; dutasteride（如 Avodart）：
      限前列腺增生且有阻塞症狀…前列腺大於 30mL 或最大尿流速（Qmax）
      小於 15 mL/sec 之病人方可使用。

  這段文字同時包含病名、藥名與具體判準，正好補上「中文病名 ↔ 學名藥成分」
  之間缺的那座橋，而且是健保署的官方文字，不是本專案自行下的臨床判斷。

資料來源：
  健保用藥品項查詢項目檔的「給付規定章節連結」欄位，指向健保署的
  給付規定 PDF：
      https://info.nhi.gov.tw/api/INAE3000/INAE3000S01/getPDF?DurgFileName=<章節>_<版本>.pdf

  ⚠️ 授權定性請自行確認：藥品給付規定係依全民健康保險法發布之規定，
     一般認為屬著作權法第 9 條所稱之「命令、公文」，不得為著作權之標的。
     本專案據此收錄全文並註明出處。若貴單位法務有不同見解，
     可改用 --summary-only 只輸出章節編號與適用成分，不含條文全文。

用法：
  python build_nhi_rules.py                 # 下載並產生條文語料
  python build_nhi_rules.py --list          # 只列出會抓哪些章節，不下載
  python build_nhi_rules.py --summary-only  # 不含條文全文
  python build_nhi_rules.py --from-file 手動下載的用藥品項檔.csv

需要：pip install pypdf
"""
import argparse
import collections
import datetime
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_nhi_corpus import (  # noqa: E402
    DATASETS, FIELDS, _norm_ingredient, get_rows, is_current, is_urology, pick,
)

PDF_DIR = pathlib.Path(__file__).parent / ".nhi_rules_pdf"
UA = {"User-Agent": "urobot-tw/0.1 (+https://github.com/PatentsOwnerJeff/urobot-tw)"}

SOURCE_TMPL = ("全民健康保險藥品給付規定第 {chapter} 節"
               "（衛生福利部中央健康保險署公告，版本 {version}；"
               "取自 {url}，資料擷取日期 {fetched}）")

DISCLAIMER = ("以上為健保給付規定條文，規範的是保險給付範圍與申報條件，"
              "不等同於臨床適應症或治療建議；最新條文以健保署公告為準。")


# ---------------------------------------------------------------- 章節清單
def chapter_links(rows):
    """從用藥品項檔抽出泌尿科藥品用到的給付規定章節與 PDF 連結。

    「給付規定章節」與「給付規定章節連結」兩欄都可能是逗號分隔的多筆，
    且兩邊筆數不一定對得起來（實測有章節 2 個、連結只有 1 個的情況）。
    因此章節編號一律從 PDF 檔名解析，不依賴兩欄的順序對應。
    """
    found = collections.defaultdict(lambda: {"ingredients": set(), "url": None})

    for row in rows:
        links = (pick(row, ["給付規定章節連結"]) or "").strip()
        if not links:
            continue
        ing = _norm_ingredient(pick(row, FIELDS["drugs"]["ingredient"]))
        atc = pick(row, FIELDS["drugs"]["atc"]).upper()

        for url in (u.strip() for u in links.split(",") if u.strip()):
            m = re.search(r"DurgFileName=(.+?)\.pdf", url)
            if not m:
                continue
            stem = m.group(1)                      # 例：5.2.2.1._20191201_000
            chapter = stem.split("_")[0].rstrip(".")
            entry = found[chapter]
            entry["url"] = url
            entry["stem"] = stem
            if ing:
                entry["ingredients"].add((ing, atc))
    return dict(sorted(found.items(), key=lambda kv: _chapter_key(kv[0])))


def _chapter_key(ch):
    return tuple(int(x) if x.isdigit() else 0 for x in ch.split("."))


# ---------------------------------------------------------------- PDF
def download(url, stem, retries=3):
    PDF_DIR.mkdir(exist_ok=True)
    path = PDF_DIR / f"{stem}.pdf"
    if path.exists() and path.stat().st_size > 0:
        return path
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if not data.startswith(b"%PDF"):
                raise ValueError(f"回應不是 PDF（開頭：{data[:20]!r}）")
            path.write_bytes(data)
            return path
        except (urllib.error.URLError, ValueError, TimeoutError) as e:
            if attempt == retries:
                raise
            print(f"      第 {attempt} 次失敗（{e}），2 秒後重試…")
            time.sleep(2)


def extract_text(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise SystemExit("需要 pypdf 才能讀給付規定 PDF。請執行：\n  pip install pypdf")
    text = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    # PDF 常見的斷字換行與多餘空白
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"\n+", "\n", text)
    text = re.sub(r"[ \t　]+", " ", text)
    return text.strip()


def version_of(stem):
    m = re.search(r"_(\d{8})", stem)
    if not m:
        return "未標示"
    v = m.group(1)
    return f"{v[:4]}-{v[4:6]}-{v[6:]}"


# ---------------------------------------------------------------- 語料
def to_docs(chapters, summary_only=False, fetched=None):
    fetched = fetched or datetime.date.today().isoformat()
    docs = []
    for chapter, info in chapters.items():
        ings = sorted({i for i, _ in info["ingredients"]})
        atcs = sorted({a for _, a in info["ingredients"] if a})

        head = [f"健保藥品給付規定第 {chapter} 節。"]
        if ings:
            head.append(f"適用成分：{'、'.join(ings[:12])}"
                        f"{f'等 {len(ings)} 種' if len(ings) > 12 else ''}。")
        if atcs:
            head.append(f"ATC 代碼：{'、'.join(atcs[:8])}。")

        body = "" if summary_only else info.get("text", "")
        parts = head + ([f"條文內容：{body}"] if body else []) + [DISCLAIMER]

        docs.append({
            "id": f"nhi-rule-{chapter}",
            "source": SOURCE_TMPL.format(chapter=chapter,
                                         version=version_of(info.get("stem", "")),
                                         url=info["url"], fetched=fetched),
            "section": f"健保給付／藥品給付規定／第 {chapter} 節",
            "text": " ".join(parts),
        })
    return docs


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="建置健保藥品給付規定條文語料")
    ap.add_argument("--from-file", help="用手動下載的用藥品項檔，不重新下載")
    ap.add_argument("--list", action="store_true", help="只列出章節清單，不下載 PDF")
    ap.add_argument("--summary-only", action="store_true",
                    help="不收錄條文全文，只輸出章節編號與適用成分")
    ap.add_argument("--include-expired", action="store_true",
                    help="連已失效品項用到的章節也一併收錄")
    ap.add_argument("--out", default="corpus/nhi_drug_rules.jsonl")
    args = ap.parse_args()

    print("取得健保用藥品項檔…")
    rows = get_rows("drugs", args.from_file)
    uro = [r for r in rows if is_urology(r, "drugs")]
    if not args.include_expired:
        uro = [r for r in uro if is_current(r, "drugs")]
    print(f"  總筆數 {len(rows)} → 泌尿科現行品項 {len(uro)} 筆")

    chapters = chapter_links(uro)
    print(f"  用到的給付規定章節：{len(chapters)} 個\n")

    for ch, info in chapters.items():
        ings = sorted({i for i, _ in info["ingredients"]})
        print(f"  第 {ch:<12} 節  適用 {len(ings):>2} 種成分："
              f"{'、'.join(ings[:4])}{'…' if len(ings) > 4 else ''}")

    if args.list:
        print(f"\n（--list 模式，未下載 PDF）")
        return

    if not args.summary_only:
        print(f"\n下載給付規定 PDF（共 {len(chapters)} 份）…")
        failed = []
        for i, (ch, info) in enumerate(chapters.items(), 1):
            print(f"  [{i}/{len(chapters)}] 第 {ch} 節", end=" ", flush=True)
            try:
                path = download(info["url"], info["stem"])
                info["text"] = extract_text(path)
                print(f"→ {len(info['text'])} 字")
            except Exception as e:
                print(f"→ ❌ {type(e).__name__}: {e}")
                failed.append(ch)
            time.sleep(0.5)          # 對政府網站客氣一點
        if failed:
            print(f"\n⚠️ 下列章節取得失敗，本次未收錄條文：{'、'.join(failed)}")

    docs = to_docs(chapters, summary_only=args.summary_only)
    docs = [d for d in docs if args.summary_only or "條文內容：" in d["text"]]
    if not docs:
        raise SystemExit("沒有產出任何語料。")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in docs) + "\n",
                   encoding="utf-8")
    print(f"\n已寫入：{out}（{len(docs)} 段）")
    print(f"樣本：{docs[0]['text'][:200]}…")
    print("\n下一步：python ingest.py   # 重建索引")


if __name__ == "__main__":
    sys.exit(main())
