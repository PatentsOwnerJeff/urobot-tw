"""UROBOT TW — 問答層（可插拔模型）
優先序：
  1. ANTHROPIC_API_KEY 存在 → Claude API（預設推薦）
  2. UROBOT_OLLAMA_MODEL 存在 → 本地 Ollama（免費、資料不出門）
     例：export UROBOT_OLLAMA_MODEL=llama3.1  （需先安裝 ollama.com 並 pull 模型）
  3. 都沒有 → 純檢索模式（回傳指引段落＋出處）
"""
import json, os, urllib.request
from retrieve import search

SYSTEM = (
    "你是 UROBOT TW，開源的台灣泌尿科臨床決策輔助 AI。"
    "只根據提供的指引段落回答，以繁體中文作答，逐點標註出處編號如 [eau-stone-12]。"
    "段落中找不到答案就明說，不得編造。"
    "結尾固定加註：本回答僅供臨床參考，最終決策由醫師負責。"
)

def _context(hits):
    parts = []
    for h in hits:
        summary = f"\n中文摘要：{h['summary_zh']}" if h.get("summary_zh") else ""
        parts.append(f"[{h['id']}] {h['section']}（{h['source']}）{summary}\n原文：{h['text']}")
    return "\n\n".join(parts)

def _ask_claude(prompt):
    import anthropic
    r = anthropic.Anthropic().messages.create(
        model=os.getenv("UROBOT_CLAUDE_MODEL", "claude-sonnet-4-5"), max_tokens=1500,
        system=SYSTEM, messages=[{"role": "user", "content": prompt}])
    return r.content[0].text

def _ask_ollama(prompt):
    model = os.environ["UROBOT_OLLAMA_MODEL"]
    req = urllib.request.Request(
        os.getenv("UROBOT_OLLAMA_URL", "http://localhost:11434") + "/api/chat",
        data=json.dumps({"model": model, "stream": False,
                         "messages": [{"role": "system", "content": SYSTEM},
                                      {"role": "user", "content": prompt}]}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.load(resp)["message"]["content"]

def ask(question: str, k: int = 5) -> str:
    hits = search(question, k)
    if not hits:
        return "語料庫中找不到相關內容。"
    prompt = f"指引段落：\n{_context(hits)}\n\n問題：{question}"

    if os.getenv("ANTHROPIC_API_KEY"):
        return _ask_claude(prompt)
    if os.getenv("UROBOT_OLLAMA_MODEL"):
        return _ask_ollama(prompt)

    lines = ["【純檢索模式 — 設定 ANTHROPIC_API_KEY 或 UROBOT_OLLAMA_MODEL 可獲得整合式回答】\n最相關指引段落："]
    for h in hits:
        body = h.get("summary_zh") or h["text"]
        lines.append(f"\n▪ {h['section']} [{h['id']}]（相關度 {h['score']}）\n  {body}\n  出處：{h['source']}")
    lines.append("\n本內容僅供臨床參考，最終決策由醫師負責。")
    return "\n".join(lines)

if __name__ == "__main__":
    import sys
    print(ask(" ".join(sys.argv[1:]) or "PSA 6.5 的病人需要切片嗎"))
