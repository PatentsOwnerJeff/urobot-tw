"""UROBOT TW — 評測系統
對標德國 UroBot 的評測方法（考題正確率 RoCA, Rate of Correct Answers）。

用法：
  python eval.py                                   # 內建示範考題
  python eval.py exams/我的題庫.jsonl               # 指定題庫
  python eval.py --out results/claude.json         # 結果存檔，方便跨模型比較
  python eval.py --compare results/*.json          # 比較多次評測結果

有 LLM（ANTHROPIC_API_KEY 或 UROBOT_OLLAMA_MODEL）→ 實際作答選擇題，算正確率。
沒有 LLM → 檢索命中率模式：檢查正解所依據的段落是否被檢索到（evidence 欄位）。

結果一律可存成 JSON：要發表對標論文，評測必須可重現、可比較。
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import sys

from answer import LLMError, _ask_claude, _ask_ollama, _context, backend, backend_label
from retrieve import IndexNotBuilt, search

MCQ_SYSTEM_HINT = "\n\n請只根據指引段落作答，最後一行輸出「答案：X」（X 為 A/B/C/D）。"


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _retrieve_for(q, k=5):
    return search(q["question"] + " " + " ".join(q["options"].values()), k)


def ask_mcq(q, k=5):
    hits = _retrieve_for(q, k)
    opts = "\n".join(f"{key}. {v}" for key, v in q["options"].items())
    prompt = f"指引段落：\n{_context(hits)}\n\n選擇題：{q['question']}\n{opts}{MCQ_SYSTEM_HINT}"
    reply = _ask_claude(prompt) if backend() == "claude" else _ask_ollama(prompt)
    m = re.findall(r"答案[:：]\s*([ABCD])", reply)
    return (m[-1] if m else "?"), hits, reply


def run(path, k=5, verbose=True):
    qs = load(path)
    has_llm = backend() != "retrieval"
    records = []

    for q in qs:
        if has_llm:
            pred, hits, reply = ask_mcq(q, k)
            ok = pred == q["answer"]
            rec = {"id": q["id"], "predicted": pred, "answer": q["answer"], "correct": ok,
                   "retrieved": [h["id"] for h in hits], "raw_reply": reply}
            if verbose:
                print(f"{q['id']}: 模型答 {pred}／正解 {q['answer']} {'✓' if ok else '✗'}")
        else:
            hits = _retrieve_for(q, k)
            retrieved = [h["id"] for h in hits]
            evidence = q.get("evidence", [])
            got = sorted(set(retrieved) & set(evidence))
            rec = {"id": q["id"], "retrieved": retrieved, "evidence": evidence,
                   "evidence_hit": bool(got), "matched": got}
            if verbose:
                print(f"{q['id']}: 檢索{'命中' if got else '未命中'}正解段落 {evidence or '（未標註 evidence）'}")
        records.append(rec)

    n = len(qs)
    summary = {
        "timestamp": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "exam": str(path),
        "n_questions": n,
        "backend": backend_label(),
        "top_k": k,
        "query_expansion": not os.getenv("UROBOT_NO_EXPAND"),
        "mode": "roca" if has_llm else "retrieval_hit_rate",
    }
    if has_llm:
        correct = sum(r["correct"] for r in records)
        summary["correct"] = correct
        summary["roca"] = round(correct / n, 4) if n else 0.0
    else:
        hit = sum(r["evidence_hit"] for r in records)
        scored = sum(1 for r in records if r["evidence"])
        summary["evidence_hit"] = hit
        summary["n_with_evidence"] = scored
        summary["retrieval_hit_rate"] = round(hit / scored, 4) if scored else None

    return {"summary": summary, "records": records}


def print_summary(s):
    print()
    if s["mode"] == "roca":
        print(f"正確率 RoCA：{s['correct']}/{s['n_questions']} = {s['roca']:.1%}"
              f"　（backend={s['backend']}；UroBot-4o 對標值 88.4%）")
    else:
        rate = s["retrieval_hit_rate"]
        rate_txt = f"{rate:.1%}" if rate is not None else "n/a（題庫未標註 evidence）"
        print(f"檢索命中率：{s['evidence_hit']}/{s['n_with_evidence']} = {rate_txt}")
        print("（純檢索模式。設定 ANTHROPIC_API_KEY 或 UROBOT_OLLAMA_MODEL 可算真正的答題正確率）")


def compare(paths):
    rows = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            s = json.load(f)["summary"]
        score = s.get("roca") if s["mode"] == "roca" else s.get("retrieval_hit_rate")
        rows.append((s["backend"], s["mode"], s["n_questions"], s["top_k"],
                     s["query_expansion"], score, s["timestamp"][:16], pathlib.Path(p).name))

    w = max((len(r[0]) for r in rows), default=8)
    print(f"{'backend'.ljust(w)}  {'mode':<20} {'n':>4} {'k':>3} {'expand':>6} {'score':>7}  timestamp")
    print("-" * (w + 60))
    for backend_name, mode, n, k, exp, score, ts, _ in sorted(rows, key=lambda r: -(r[5] or 0)):
        st = f"{score:.1%}" if score is not None else "n/a"
        print(f"{backend_name.ljust(w)}  {mode:<20} {n:>4} {k:>3} {str(exp):>6} {st:>7}  {ts}")


def main():
    ap = argparse.ArgumentParser(description="UROBOT TW 評測")
    ap.add_argument("exam", nargs="?", default="exams/demo_questions.jsonl",
                    help="題庫 jsonl（預設：exams/demo_questions.jsonl）")
    ap.add_argument("--out", metavar="PATH", help="把完整結果寫成 JSON")
    ap.add_argument("-k", "--top-k", type=int, default=5, help="每題檢索幾段（預設 5）")
    ap.add_argument("--quiet", action="store_true", help="只印總結")
    ap.add_argument("--compare", nargs="+", metavar="JSON",
                    help="比較數個先前的結果檔，不執行評測")
    args = ap.parse_args()

    if args.compare:
        return compare(args.compare)

    try:
        result = run(args.exam, k=args.top_k, verbose=not args.quiet)
    except IndexNotBuilt as e:
        raise SystemExit(str(e))
    except LLMError as e:
        raise SystemExit(str(e))

    print_summary(result["summary"])

    if args.out:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n結果已存檔：{out}")
        print(f"比較多次評測：  python eval.py --compare {out.parent}/*.json")


if __name__ == "__main__":
    sys.exit(main())
