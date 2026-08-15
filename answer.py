"""UROBOT TW — 問答層（可插拔模型）
優先序：
  1. ANTHROPIC_API_KEY 存在 → Claude API（預設推薦）
  2. UROBOT_OLLAMA_MODEL 存在 → 本地 Ollama（免費、資料不出門）
     例：export UROBOT_OLLAMA_MODEL=llama3.1  （需先安裝 ollama.com 並 pull 模型）
  3. 都沒有 → 純檢索模式（回傳指引段落＋出處）
"""
import json
import os
import urllib.error
import urllib.request

from retrieve import IndexNotBuilt, scope_of, search

SYSTEM = (
    "你是 UROBOT TW，開源的台灣泌尿科臨床決策輔助 AI。"
    "只根據提供的指引段落回答，以繁體中文作答，逐點標註出處編號如 [eau-stone-12]。"
    "段落中找不到答案就明說，不得編造。"
    "結尾固定加註：本回答僅供臨床參考，最終決策由醫師負責。"
)

DISCLAIMER = "本內容僅供臨床參考，最終決策由醫師負責。"

DEFAULT_CLAUDE_MODEL = "claude-sonnet-5"


class LLMError(RuntimeError):
    """呼叫模型失敗，訊息應告訴使用者下一步怎麼做。"""


def backend() -> str:
    """目前會走哪一條路徑：'claude' / 'ollama' / 'retrieval'。"""
    if os.getenv("ANTHROPIC_API_KEY"):
        return "claude"
    if os.getenv("UROBOT_OLLAMA_MODEL"):
        return "ollama"
    return "retrieval"


def backend_label() -> str:
    """給評測報表用的可讀標籤，含模型名稱。"""
    b = backend()
    if b == "claude":
        return f"claude:{os.getenv('UROBOT_CLAUDE_MODEL', DEFAULT_CLAUDE_MODEL)}"
    if b == "ollama":
        return f"ollama:{os.environ['UROBOT_OLLAMA_MODEL']}"
    return "retrieval-only"


def _context(hits):
    parts = []
    for h in hits:
        summary = f"\n中文摘要：{h['summary_zh']}" if h.get("summary_zh") else ""
        parts.append(f"[{h['id']}] {h['section']}（{h['source']}）{summary}\n原文：{h['text']}")
    return "\n\n".join(parts)


def _ask_claude(prompt):
    try:
        import anthropic
    except ImportError:
        raise LLMError(
            "已設定 ANTHROPIC_API_KEY，但沒安裝 anthropic 套件。\n"
            "請執行：  pip install anthropic"
        )
    model = os.getenv("UROBOT_CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL)
    try:
        r = anthropic.Anthropic().messages.create(
            model=model, max_tokens=1500, system=SYSTEM,
            messages=[{"role": "user", "content": prompt}])
    except Exception as e:  # SDK 的例外型別會隨版本變動，統一轉成可讀訊息
        raise LLMError(
            f"呼叫 Claude API 失敗（model={model}）：{e}\n"
            "請確認 ANTHROPIC_API_KEY 有效、模型名稱正確、且網路可連線。\n"
            "想改用其他模型：export UROBOT_CLAUDE_MODEL=claude-opus-5"
        )
    return r.content[0].text


def _ask_ollama(prompt):
    model = os.environ["UROBOT_OLLAMA_MODEL"]
    url = os.getenv("UROBOT_OLLAMA_URL", "http://localhost:11434")
    req = urllib.request.Request(
        url + "/api/chat",
        data=json.dumps({"model": model, "stream": False,
                         "messages": [{"role": "system", "content": SYSTEM},
                                      {"role": "user", "content": prompt}]}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.load(resp)["message"]["content"]
    except urllib.error.HTTPError as e:
        raise LLMError(
            f"Ollama 回傳錯誤 {e.code}（model={model}）。\n"
            f"請確認模型已下載：  ollama pull {model}"
        )
    except urllib.error.URLError as e:
        raise LLMError(
            f"連不上 Ollama（{url}）：{e.reason}\n"
            "請確認 Ollama 已啟動（ollama serve），或改設 UROBOT_OLLAMA_URL。"
        )
    except (KeyError, ValueError) as e:
        raise LLMError(f"Ollama 回應格式非預期：{e}")


def _retrieval_only(hits):
    lines = ["【純檢索模式 — 設定 ANTHROPIC_API_KEY 或 UROBOT_OLLAMA_MODEL 可獲得整合式回答】\n最相關指引段落："]
    for h in hits:
        body = h.get("summary_zh") or h["text"]
        # 刻意不顯示 BM25 分數：它跨查詢不可比較，卻長得像信心值。
        # 答非所問的段落分數常比正確答案高，顯示它只會誤導使用者。見 scope.json。
        lines.append(f"\n▪ {h['section']} [{h['id']}]\n  {body}\n  出處：{h['source']}")
    lines.append(f"\n{DISCLAIMER}")
    return "\n".join(lines)


def _gap_reply(s) -> str:
    """已知未涵蓋的主題：說明缺什麼，不呈現硬湊出來的段落。

    這裡刻意不回傳檢索結果。BM25 一定找得到字面上沾邊的東西——問「女性反覆
    泌尿道感染怎麼預防」會回傳結石病人的取石前抗生素——那看起來像答案，
    接上大模型後還會被寫成通順的臨床建議。對臨床工具而言，這比不回答更危險。
    """
    lines = ["【語料庫未涵蓋此主題，不予作答】"]
    for g in s["gaps"]:
        lines.append(f"\n▪ {g['topic']}\n  {g['note']}")

    # 只講「沒有資料」對使用者沒用——要讓他知道補哪一本、去哪拿、怎麼建。
    fixes = [g for g in s["gaps"] if g.get("fix")]
    if fixes:
        lines.append("\n─── 要讓系統能回答這個主題 ───")
    for g in fixes:
        f = g["fix"]
        lines.append(
            f"\n【{g['topic']}】需要：{f['guideline']}\n"
            f"1. 自行從 {f['url']} 下載 PDF（請自行確認擁有使用權）\n"
            f"2. python build_corpus.py <下載的PDF> \\\n"
            f"       --prefix {f['prefix']} \\\n"
            f"       --source \"{f['guideline']} <年份>\" \\\n"
            f"       --out {f['out']}\n"
            f"3. python build_corpus.py --translate {f['out']}   # 補繁中摘要\n"
            f"4. python ingest.py                                 # 重建索引\n"
            f"5. 編輯 scope.json：把「{g['topic']}」從 gaps 移到 covered，\n"
            f"   requires 填 [\"{f['prefix']}\"]，並補上該主題的 keywords"
        )
        lines.append(f"   注意：{f['out']} 屬 .gitignore 排除範圍，請勿提交到公開 repo。")

    if s["available"]:
        lines.append("\n目前語料庫實際涵蓋的主題：")
        lines += [f"  ・{t}" for t in s["available"]]
    lines.append(f"\n{DISCLAIMER}")
    return "\n".join(lines)


def _caution(s) -> str:
    """部分涵蓋或未對應到已宣告主題時的前置警語。"""
    if s["verdict"] == "partial":
        missing = "、".join(g["topic"] for g in s["gaps"])
        return (f"【部分涵蓋】此問題觸及語料庫沒有的主題：{missing}。"
                f"以下段落只涵蓋得到的部分，缺少的部分不會出現在答案裡。\n")
    if s["verdict"] == "unknown":
        return ("【未對應到已宣告主題】此查詢不屬於 scope.json 列出的任何涵蓋範圍，"
                "以下段落可能只是字面相近，請自行判斷是否相關。\n")
    return ""


def ask(question: str, k: int = 5) -> str:
    s = scope_of(question)
    if s["verdict"] == "gap":
        return _gap_reply(s)

    hits = search(question, k)
    if not hits:
        return "語料庫中找不到相關內容。"

    caution = _caution(s)
    b = backend()
    if b == "retrieval":
        return caution + _retrieval_only(hits)

    prompt = f"指引段落：\n{_context(hits)}\n\n問題：{question}"
    if caution:
        # 讓模型也知道範圍限制，否則它會用手上有的段落把缺口補成通順的答案
        prompt = (f"注意：{caution.strip()}\n"
                  f"回答時必須明講哪一部分語料庫沒有涵蓋，不得以現有段落推論補足。\n\n"
                  + prompt)
    return _ask_claude(prompt) if b == "claude" else _ask_ollama(prompt)


if __name__ == "__main__":
    import sys

    try:
        print(ask(" ".join(sys.argv[1:]) or "PSA 6.5 的病人需要切片嗎"))
    except (IndexNotBuilt, LLMError) as e:
        raise SystemExit(str(e))
