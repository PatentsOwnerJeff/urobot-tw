"""UROBOT TW — 語料建置工具（從指引 PDF 產生 jsonl）

為什麼需要這支程式：
  EAU / AUA / TUA 等學會指引的著作權屬原機構，我們**不能**把原文放進公開 repo。
  但我們可以散布「把 PDF 轉成語料的工具」，讓每位使用者自行從官網下載、
  在自己機器上建置語料。散布的是工具，不是內容。

用法：
  # 1. 自行從 https://uroweb.org/guidelines 下載 PDF
  # 2. 轉成語料
  python build_corpus.py ~/Downloads/EAU-Urolithiasis-2025.pdf \\
      --prefix eau-stone \\
      --source "EAU Guidelines on Urolithiasis 2025" \\
      --out corpus/eau_urolithiasis.jsonl

  # 3.（選用）補繁中摘要，中文提問才容易命中英文段落
  python build_corpus.py --translate corpus/eau_urolithiasis.jsonl

  # 先看看會切成什麼樣子，不寫檔
  python build_corpus.py xxx.pdf --prefix eau-stone --source "..." --dry-run

需要：pip install pypdf   （只有這支程式需要，不是核心相依）

⚠️ 使用者責任：你必須確認自己有權使用該份文件。本工具不會、也無法替你
   取得授權。產出的 jsonl 預設已被 .gitignore 排除，請勿提交到公開 repo。
"""
import argparse
import json
import os
import pathlib
import re
import sys

MIN_CHARS = 200
MAX_CHARS = 1600

# 頁首頁尾雜訊：EAU PDF 常見樣式，可依實際文件增補
NOISE_PATTERNS = [
    re.compile(r"^\s*\d+\s*$"),                                  # 純頁碼
    re.compile(r"EAU\s+GUIDELINES\s+ON", re.I),
    re.compile(r"^\s*(UROLITHIASIS|PROSTATE CANCER|NON-MUSCLE)", re.I),
    re.compile(r"^\s*ISBN", re.I),
    re.compile(r"^\s*©", re.I),
]

# 章節標題：「3.4.2 Diagnostic evaluation」這類編號標題
HEADING = re.compile(r"^\s*(\d+(?:\.\d+){0,3})\s+([A-Z][^\n]{2,90})\s*$")


def extract_pages(pdf_path):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise SystemExit(
            "需要 pypdf 才能讀 PDF。請執行：\n  pip install pypdf\n"
            "（或先自行把 PDF 轉成 .txt，本工具也接受 .txt 輸入）"
        )
    reader = PdfReader(pdf_path)
    return [(i + 1, (page.extract_text() or "")) for i, page in enumerate(reader.pages)]


def clean_lines(text):
    out = []
    for line in text.splitlines():
        if any(p.search(line) for p in NOISE_PATTERNS):
            continue
        out.append(line.rstrip())
    return out


def split_sections(pages):
    """依編號標題切章節，回傳 [(章節標題, 內文, 起始頁)]。"""
    sections, current = [], {"title": "Preamble", "lines": [], "page": 1}
    for pageno, text in pages:
        for line in clean_lines(text):
            m = HEADING.match(line)
            if m:
                if current["lines"]:
                    sections.append(current)
                current = {"title": f"{m.group(1)} {m.group(2).strip()}",
                           "lines": [], "page": pageno}
            else:
                current["lines"].append(line)
    if current["lines"]:
        sections.append(current)
    return sections


def to_paragraphs(lines):
    """把行合併成段落：空行分段，並修掉 PDF 的斷字換行。"""
    text = "\n".join(lines)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)      # hyphen-\nation → hyphenation
    text = re.sub(r"(?<![.:;])\n(?!\n)", " ", text)   # 句中換行 → 空格
    return [re.sub(r"\s+", " ", p).strip()
            for p in re.split(r"\n\s*\n", text) if p.strip()]


def chunk(paragraphs, min_chars, max_chars):
    """把段落聚合成 min~max 字元的區塊；過長的單一段落再依句號切開。"""
    chunks, buf = [], ""
    for para in paragraphs:
        while len(para) > max_chars:
            cut = para.rfind(". ", 0, max_chars)
            cut = cut + 1 if cut > min_chars else max_chars
            chunks.append(para[:cut].strip())
            para = para[cut:].strip()
        if len(buf) + len(para) + 1 <= max_chars:
            buf = f"{buf} {para}".strip()
        else:
            if buf:
                chunks.append(buf)
            buf = para
        if len(buf) >= min_chars:
            chunks.append(buf)
            buf = ""
    if buf:
        chunks.append(buf)
    return [c for c in chunks if len(c) >= min_chars // 2]


def build(path, prefix, source, min_chars, max_chars):
    path = pathlib.Path(path)
    if path.suffix.lower() == ".pdf":
        pages = extract_pages(path)
    else:
        pages = [(1, path.read_text(encoding="utf-8", errors="replace"))]

    docs, n = [], 0
    for sec in split_sections(pages):
        for body in chunk(to_paragraphs(sec["lines"]), min_chars, max_chars):
            n += 1
            docs.append({
                "id": f"{prefix}-{n:03d}",
                "source": source,
                "section": sec["title"],
                "text": body,
                "_page": sec["page"],
            })
    return docs


# ---------- 繁中摘要 ----------

TRANSLATE_PROMPT = (
    "以下是泌尿科臨床指引的英文段落。請用繁體中文寫一段 60–120 字的摘要，"
    "保留所有具體數值、藥名、術式縮寫與建議等級。只輸出摘要本身，不要加任何前言或標題。\n\n"
)


def translate(jsonl_path, overwrite=False):
    """替既有 jsonl 補上 summary_zh，使用者已設定的 LLM backend。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from answer import LLMError, _ask_claude, _ask_ollama, backend, backend_label

    if backend() == "retrieval":
        raise SystemExit(
            "產生繁中摘要需要 LLM。請先設定：\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...      （或）\n"
            "  export UROBOT_OLLAMA_MODEL=llama3.1"
        )
    ask_fn = _ask_claude if backend() == "claude" else _ask_ollama

    path = pathlib.Path(jsonl_path)
    docs = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    todo = [d for d in docs if overwrite or not d.get("summary_zh")]
    print(f"使用 {backend_label()} 產生摘要：{len(todo)}/{len(docs)} 段")

    for i, d in enumerate(todo, 1):
        try:
            d["summary_zh"] = ask_fn(TRANSLATE_PROMPT + d["text"]).strip()
        except LLMError as e:
            print(f"\n第 {i} 段失敗，已保留進度：{e}")
            break
        print(f"\r  {i}/{len(todo)}", end="", flush=True)
        if i % 20 == 0:  # 邊做邊存，中斷不會全部白做
            _write(path, docs)
    print()
    _write(path, docs)
    print(f"已更新：{path}")


def _write(path, docs):
    path.write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in docs) + "\n",
        encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(
        description="從指引 PDF 建置 UROBOT TW 語料",
        epilog="⚠️ 你必須自行確認擁有該文件的使用權。產出的語料請勿提交到公開 repo。")
    ap.add_argument("input", help="來源 PDF 或 txt；搭配 --translate 時則為既有 jsonl")
    ap.add_argument("--prefix", help="id 前綴，例如 eau-stone")
    ap.add_argument("--source", help="出處字串，務必包含版本或年份")
    ap.add_argument("--out", help="輸出 jsonl 路徑")
    ap.add_argument("--min-chars", type=int, default=MIN_CHARS)
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS)
    ap.add_argument("--dry-run", action="store_true", help="只印出前幾段，不寫檔")
    ap.add_argument("--translate", action="store_true", help="替既有 jsonl 補繁中摘要")
    ap.add_argument("--overwrite-summary", action="store_true", help="連已有摘要也重做")
    args = ap.parse_args()

    if args.translate:
        return translate(args.input, args.overwrite_summary)

    if not (args.prefix and args.source):
        ap.error("建置語料需要 --prefix 與 --source")

    docs = build(args.input, args.prefix, args.source, args.min_chars, args.max_chars)
    if not docs:
        raise SystemExit("沒有切出任何段落。請確認 PDF 可擷取文字（掃描檔需先 OCR），"
                         "或改用 --min-chars 調整門檻。")

    lens = sorted(len(d["text"]) for d in docs)
    print(f"共 {len(docs)} 段；長度中位數 {lens[len(lens)//2]}，"
          f"最短 {lens[0]}，最長 {lens[-1]}")
    print(f"章節數：{len({d['section'] for d in docs})}")

    if args.dry_run or not args.out:
        for d in docs[:3]:
            print(f"\n--- {d['id']} | {d['section']} (p.{d['_page']}) ---\n{d['text'][:300]}…")
        if not args.out:
            print("\n（未指定 --out，未寫檔）")
        return

    for d in docs:
        d.pop("_page", None)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    _write(out, docs)
    print(f"\n已寫入：{out}")
    print("下一步：")
    print(f"  python build_corpus.py --translate {out}   # 補繁中摘要（選用但強烈建議）")
    print("  python ingest.py                            # 重建索引")


if __name__ == "__main__":
    main()
