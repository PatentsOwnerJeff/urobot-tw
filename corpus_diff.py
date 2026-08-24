"""UROBOT TW — 語料變動摘要與健全性檢查

用途：健保署資料會改版，自動更新排程（.github/workflows/nhi-refresh.yml）每月重建
語料後，需要回答兩個問題：

  1. 「這次到底改了什麼？」
     重建後的 jsonl 逐行 diff 有數百行，人不會看，看了也判斷不出臨床意義。
     這裡把它摘要成「新增/刪除/支付點數變動」的條列，PR 才有審查價值。

  2. 「這次的重建可信嗎？」
     這是更重要的一題。健保署偶爾會改欄位名稱（build_nhi_corpus.py 開頭已警告），
     欄位對不上時腳本**不會拋例外**，只會安靜地產出殘缺語料——欄位讀不到就變空字串，
     過濾條件比對不到就整批漏掉。若把這種結果自動 commit 進去，等於把自動更新
     變成自動污染，而且不會有人發現，因為 CI 的檢索測試只跑示範語料。
     所以 --check 會在段數暴跌、id 大量對不上、text 大量空白時直接讓流程失敗。

用法：
  python corpus_diff.py --old before/ --new corpus/              # 印出 markdown 摘要
  python corpus_diff.py --old before/ --new corpus/ --out d.md   # 寫檔（供 PR 內文）
  python corpus_diff.py --old before/ --new corpus/ --check      # 健全性檢查，有問題 exit 1

  --only nhi_procedures_urology.jsonl   只比對特定檔案（可重複）
  --min-ratio 0.8                       段數不得少於舊版的幾成（預設 0.8）
  --max-ratio 1.5                       段數不得多於舊版的幾倍（預設 1.5）
  --min-overlap 0.5                     id 至少要有幾成對得上（預設 0.5）
  --max-empty 0.02                      text 過短的比例上限（預設 2%）

離開碼：0 正常、1 內部錯誤（檔案讀不到、JSON 壞掉）、2 健全性檢查未通過。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import re
import statistics
import sys

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_UNHEALTHY = 2

# 只有這些檔案由自動排程重建；EAU 指引語料不隨 repo 散布，也不該被排程碰。
MANAGED = [
    "nhi_procedures_urology.jsonl",
    "nhi_drugs_urology.jsonl",
    "nhi_drug_rules.jsonl",
]

REQUIRED_FIELDS = ("id", "source", "section", "text")

# text 短於這個長度視為整段抽取失敗。實測現行語料最短 66 字，所以這個門檻只抓
# 「整段壞掉」，抓不到「段落裡少了一個欄位」——後者由 fact_coverage 與中位長度負責。
MIN_TEXT_LEN = 20

# 從 text 抽出有臨床/財務意義的數字，變動時單獨列出。
# 純文字改寫（例如備註調整字句）不列細節，只計入「內容變動」。
NUMERIC_FACTS = [
    ("支付點數", re.compile(r"健保支付點數\s*([\d,]+)\s*點")),
    ("收載品項數", re.compile(r"健保現行收載\s*([\d,]+)\s*個品項")),
]

# PR 內文不能無限長，每個類別最多列這麼多筆
MAX_LISTED = 20


def load(path: pathlib.Path) -> dict[str, dict]:
    """讀 jsonl，以 id 為鍵。檔案不存在回空 dict（視為全新檔案）。"""
    if not path.exists():
        return {}
    records: dict[str, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno} 不是合法 JSON：{exc}") from exc
            rid = rec.get("id")
            if not rid:
                raise ValueError(f"{path}:{lineno} 缺少 id 欄位")
            records[rid] = rec
    return records


def extract_facts(text: str) -> dict[str, str]:
    """抽出 text 裡的關鍵數字，供變動比對。"""
    facts = {}
    for label, pattern in NUMERIC_FACTS:
        m = pattern.search(text or "")
        if m:
            facts[label] = m.group(1).replace(",", "")
    return facts


def fact_coverage(records: dict[str, dict]) -> dict[str, float]:
    """每個關鍵數字在多少比例的段落裡抽得到。

    這是偵測「欄位被改名」最直接的訊號。欄位讀不到時 text 不會變空——
    to_docs() 是用 `if pts:` 這類條件把子句串起來的，少一個欄位只是少一個子句，
    段落照樣有 60+ 字、照樣過得了 MIN_TEXT_LEN。但「健保支付點數」這個子句會整批消失。
    """
    if not records:
        return {}
    total = len(records)
    return {
        label: sum(1 for r in records.values() if pattern.search(r.get("text", "") or "")) / total
        for label, pattern in NUMERIC_FACTS
    }


def median_text_len(records: dict[str, dict]) -> float:
    if not records:
        return 0.0
    return statistics.median(len(str(r.get("text", ""))) for r in records.values())


@dataclasses.dataclass
class FileDiff:
    filename: str
    old_count: int
    new_count: int
    added: list[str] = dataclasses.field(default_factory=list)
    removed: list[str] = dataclasses.field(default_factory=list)
    # (id, section, label, before, after)
    fact_changes: list[tuple[str, str, str, str, str]] = dataclasses.field(default_factory=list)
    # (id, section) — text 有變但抽不出具體數字差異
    text_changes: list[tuple[str, str]] = dataclasses.field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.fact_changes or self.text_changes)


def diff_file(filename: str, old: dict[str, dict], new: dict[str, dict]) -> FileDiff:
    d = FileDiff(filename=filename, old_count=len(old), new_count=len(new))

    d.added = sorted(set(new) - set(old))
    d.removed = sorted(set(old) - set(new))

    for rid in sorted(set(old) & set(new)):
        old_text = old[rid].get("text", "")
        new_text = new[rid].get("text", "")
        if old_text == new_text:
            continue
        old_facts = extract_facts(old_text)
        new_facts = extract_facts(new_text)
        section = new[rid].get("section", "")
        recorded = False
        for label in sorted(set(old_facts) | set(new_facts)):
            before = old_facts.get(label, "—")
            after = new_facts.get(label, "—")
            if before != after:
                d.fact_changes.append((rid, section, label, before, after))
                recorded = True
        if not recorded:
            d.text_changes.append((rid, section))

    return d


def sanity_problems(
    d: FileDiff,
    old: dict[str, dict],
    new: dict[str, dict],
    min_ratio: float = 0.8,
    max_ratio: float = 1.5,
    min_overlap: float = 0.5,
    max_empty: float = 0.02,
) -> list[str]:
    """回傳這次重建的可疑之處。空 list 代表看起來正常。

    每一條檢查都對應一種「健保署改了資料格式、但腳本不會拋例外」的真實失效模式。
    設計上寧可誤擋（維護者可用 workflow_dispatch 調參數放行），也不要放過——
    放過的代價是錯誤的給付資訊被自動合併，而且沒有人會發現。
    """
    problems: list[str] = []

    if d.old_count == 0:
        if d.new_count == 0:
            problems.append(f"{d.filename}：重建後是空的")
        else:
            # 沒有舊檔就沒有比較基準，下面的比例檢查全部失效。這在正常排程裡
            # 不該發生（三個 nhi_*.jsonl 都在 repo 裡），所以當成問題回報。
            problems.append(
                f"{d.filename}：找不到舊版可比對，本次無法做健全性檢查——"
                f"若是新增語料檔請人工確認後再合併"
            )
        return problems

    if d.new_count == 0:
        problems.append(f"{d.filename}：重建後是空的（舊版有 {d.old_count} 段）")
        return problems

    ratio = d.new_count / d.old_count

    if ratio < min_ratio:
        problems.append(
            f"{d.filename}：段數從 {d.old_count} 掉到 {d.new_count}"
            f"（剩 {ratio:.0%}，門檻 {min_ratio:.0%}）"
            f"——健保署可能改了欄位名稱或過濾條件失效"
        )

    # 段數暴增同樣是壞掉的訊號，而且更危險，因為「資料變多」直覺上像好事。
    # 真實案例：健保署改掉「生效迄日」的欄位名稱 → is_current() 讀不到日期 →
    # 依 build_nhi_corpus.py 的設計「無迄日視為現行」→ 數百筆已失效的給付項目
    # 全部被當成現行資料收錄。段數會從 391 暴增到 3910，每一筆舊 id 都還在，
    # 沒有任何一段是空的——只有這道上限擋得住。
    if ratio > max_ratio:
        problems.append(
            f"{d.filename}：段數從 {d.old_count} 暴增到 {d.new_count}"
            f"（{ratio:.1f} 倍，上限 {max_ratio:.1f} 倍）"
            f"——失效項目過濾可能失靈，會把已停用的給付條件當成現行資料"
        )

    # id 幾乎全換 = id 生成規則或來源代碼變了，這種情況下逐筆 diff 沒有意義，
    # 需要人工確認，不能當成「大量新增 + 大量刪除」直接合併。
    overlap = len(set(old) & set(new))
    overlap_ratio = overlap / d.old_count
    if overlap_ratio < min_overlap:
        problems.append(
            f"{d.filename}：只有 {overlap}/{d.old_count} 筆 id 對得上"
            f"（{overlap_ratio:.0%}，門檻 {min_overlap:.0%}）"
            f"——id 規則或來源代碼可能已變更，需人工確認"
        )

    # 整段抽取失敗：空白欄位或極短 text
    bad = [
        rid
        for rid, rec in new.items()
        if any(not str(rec.get(f, "")).strip() for f in REQUIRED_FIELDS)
        or len(str(rec.get("text", ""))) < MIN_TEXT_LEN
    ]
    bad_ratio = len(bad) / len(new)
    if bad_ratio > max_empty:
        sample = "、".join(bad[:3])
        problems.append(
            f"{d.filename}：{len(bad)}/{len(new)} 段欄位空白或內容過短"
            f"（{bad_ratio:.1%}，門檻 {max_empty:.1%}）例如 {sample}"
        )

    # 單一欄位消失：段落還在、長度還夠，但某個子句整批不見了。
    # 例如「健保支付點數」欄位被改名，全部 391 段都還在、都有 60+ 字，
    # 只是再也沒有任何一段講得出點數——上面所有檢查都抓不到。
    old_cov, new_cov = fact_coverage(old), fact_coverage(new)
    for label in old_cov:
        before, after = old_cov[label], new_cov.get(label, 0.0)
        if before >= 0.5 and after < before - 0.1:
            problems.append(
                f"{d.filename}：「{label}」的段落覆蓋率從 {before:.0%} 掉到 {after:.0%}"
                f"——該欄位可能已被改名，段落還在但內容少了這一項"
            )

    # 中位長度大幅縮水：抓得到欄位、但欄位變空字串的情況（例如中文品名讀不到，
    # 段落只剩英文名與代碼）。單一欄位不一定在 NUMERIC_FACTS 裡，用長度兜底。
    old_med, new_med = median_text_len(old), median_text_len(new)
    if old_med and new_med < old_med * 0.7:
        problems.append(
            f"{d.filename}：段落中位長度從 {old_med:.0f} 字掉到 {new_med:.0f} 字"
            f"（剩 {new_med / old_med:.0%}）——可能有欄位讀成了空字串"
        )

    return problems


def _listing(items: list[str], render) -> list[str]:
    lines = [render(x) for x in items[:MAX_LISTED]]
    if len(items) > MAX_LISTED:
        lines.append(f"- …另有 {len(items) - MAX_LISTED} 筆")
    return lines


def render_markdown(diffs: list[FileDiff]) -> str:
    changed = [d for d in diffs if d.changed]
    if not changed:
        return "健保署資料與現行語料一致，無變動。\n"

    out: list[str] = ["## 健保語料變動摘要", ""]

    out.append("| 檔案 | 舊 | 新 | 新增 | 刪除 | 異動 |")
    out.append("|---|---:|---:|---:|---:|---:|")
    for d in diffs:
        out.append(
            f"| `{d.filename}` | {d.old_count} | {d.new_count} | "
            f"{len(d.added)} | {len(d.removed)} | "
            f"{len(d.fact_changes) + len(d.text_changes)} |"
        )
    out.append("")

    for d in changed:
        out.append(f"### `{d.filename}`")
        out.append("")

        if d.fact_changes:
            out.append("**給付內容變動**（需優先確認）")
            out.append("")
            for rid, section, label, before, after in d.fact_changes[:MAX_LISTED]:
                name = section.split("／")[-1] if section else rid
                out.append(f"- {name}（`{rid}`）{label} {before} → **{after}**")
            if len(d.fact_changes) > MAX_LISTED:
                out.append(f"- …另有 {len(d.fact_changes) - MAX_LISTED} 筆")
            out.append("")

        if d.added:
            out.append(f"**新增 {len(d.added)} 段**")
            out.append("")
            out.extend(_listing(d.added, lambda r: f"- `{r}`"))
            out.append("")

        if d.removed:
            out.append(f"**刪除 {len(d.removed)} 段**")
            out.append("")
            out.extend(_listing(d.removed, lambda r: f"- `{r}`"))
            out.append("")

        if d.text_changes:
            out.append(f"**條文文字調整 {len(d.text_changes)} 段**（無數字變動）")
            out.append("")
            out.extend(
                _listing(
                    [f"{s.split('／')[-1] if s else r}（`{r}`）" for r, s in d.text_changes],
                    lambda x: f"- {x}",
                )
            )
            out.append("")

    out.append("---")
    out.append("")
    out.append(
        "⚠️ 給付規定 ≠ 臨床指引。合併前請確認變動內容確實來自健保署公告，"
        "而非抓取或欄位對照失誤。"
    )
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="健保語料變動摘要與健全性檢查")
    ap.add_argument("--old", required=True, type=pathlib.Path, help="舊語料目錄")
    ap.add_argument("--new", required=True, type=pathlib.Path, help="新語料目錄")
    ap.add_argument("--only", action="append", help="只比對指定檔名（可重複）")
    ap.add_argument("--out", type=pathlib.Path, help="摘要輸出檔（預設印到 stdout）")
    ap.add_argument("--check", action="store_true", help="執行健全性檢查，有問題 exit 2")
    ap.add_argument("--min-ratio", type=float, default=0.8, help="段數不得低於舊版的比例")
    ap.add_argument("--max-ratio", type=float, default=1.5, help="段數不得高於舊版的倍數")
    ap.add_argument("--min-overlap", type=float, default=0.5, help="id 至少要對得上的比例")
    ap.add_argument("--max-empty", type=float, default=0.02, help="欄位空白/過短的比例上限")
    ap.add_argument(
        "--github-output",
        type=pathlib.Path,
        help="把 changed=true/false 寫到這個檔（給 GitHub Actions 的 $GITHUB_OUTPUT）",
    )
    args = ap.parse_args(argv)

    filenames = args.only or MANAGED

    diffs: list[FileDiff] = []
    problems: list[str] = []
    for filename in filenames:
        old = load(args.old / filename)
        new = load(args.new / filename)
        d = diff_file(filename, old, new)
        diffs.append(d)
        if args.check:
            problems.extend(
                sanity_problems(
                    d,
                    old,
                    new,
                    min_ratio=args.min_ratio,
                    max_ratio=args.max_ratio,
                    min_overlap=args.min_overlap,
                    max_empty=args.max_empty,
                )
            )

    markdown = render_markdown(diffs)
    if args.out:
        args.out.write_text(markdown, encoding="utf-8")
    else:
        print(markdown)

    if problems:
        print("\n語料健全性檢查未通過：", file=sys.stderr)
        for p in problems:
            print(f"  ✗ {p}", file=sys.stderr)
        print(
            "\n這通常表示健保署改了資料格式，而不是資料真的變了。"
            "\n請先手動跑 `python build_nhi_corpus.py --inspect` 對照欄位名稱。"
            "\n確認變動屬實後，可用 --min-ratio / --max-ratio / --min-overlap 放寬門檻。",
            file=sys.stderr,
        )
        return EXIT_UNHEALTHY

    # 給 workflow 判斷要不要開 PR。走 stdout 的 GITHUB_OUTPUT 檔而不是 stderr grep——
    # stderr 混著人看的訊息，任何一行湊巧含有這個字串都會翻轉判斷。
    changed = any(d.changed for d in diffs)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")
    print(f"CORPUS_CHANGED={'true' if changed else 'false'}", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
