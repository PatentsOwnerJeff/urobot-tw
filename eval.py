"""UROBOT TW — 評測系統
對標德國 UroBot 的評測方法（考題正確率 RoCA）。
用法：python eval.py [exams/demo_questions.jsonl]

有 LLM（ANTHROPIC_API_KEY 或 UROBOT_OLLAMA_MODEL）→ 實際作答選擇題，算正確率。
沒有 LLM → 檢索命中率模式：檢查正解所在的指引段落是否被檢索到（evidence 欄位）。
之後取得泌尿專科甄審歷屆筆試題，轉成同格式 jsonl 即可直接評測。
"""
import json, os, re, sys
from retrieve import search
from answer import _context, _ask_claude, _ask_ollama

MCQ_SYSTEM_HINT = "\n\n請只根據指引段落作答，最後一行輸出「答案：X」（X 為 A/B/C/D）。"

def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]

def ask_mcq(q):
    hits = search(q["question"] + " " + " ".join(q["options"].values()), 5)
    opts = "\n".join(f"{k}. {v}" for k, v in q["options"].items())
    prompt = f"指引段落：\n{_context(hits)}\n\n選擇題：{q['question']}\n{opts}{MCQ_SYSTEM_HINT}"
    if os.getenv("ANTHROPIC_API_KEY"):
        reply = _ask_claude(prompt)
    else:
        reply = _ask_ollama(prompt)
    m = re.findall(r"答案[:：]\s*([ABCD])", reply)
    return (m[-1] if m else "?"), hits

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "exams/demo_questions.jsonl"
    qs = load(path)
    has_llm = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("UROBOT_OLLAMA_MODEL"))
    correct = hit = 0
    for q in qs:
        if has_llm:
            pred, hits = ask_mcq(q)
            ok = pred == q["answer"]
            correct += ok
            print(f"{q['id']}: 模型答 {pred}／正解 {q['answer']} {'✓' if ok else '✗'}")
        else:
            hits = search(q["question"] + " " + " ".join(q["options"].values()), 5)
            got = {h["id"] for h in hits} & set(q.get("evidence", []))
            hit += bool(got)
            print(f"{q['id']}: 檢索{'命中' if got else '未命中'}正解段落 {q.get('evidence')}")
    n = len(qs)
    if has_llm:
        print(f"\n正確率 RoCA：{correct}/{n} = {correct/n:.1%}（UroBot-4o 對標值：88.4%）")
    else:
        print(f"\n檢索命中率：{hit}/{n} = {hit/n:.1%}（純檢索模式；接上 LLM 可算真正的答題正確率）")

if __name__ == "__main__":
    main()
