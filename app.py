"""UROBOT TW — Web 介面（Flask）
執行：python app.py → 瀏覽器開 http://127.0.0.1:5000

注意：這是本機開發用的最小介面，沒有身分驗證與速率限制，
請勿直接暴露到公開網路。詳見 SECURITY.md。
"""
import os

from flask import Flask, render_template_string, request

from answer import DISCLAIMER, LLMError, ask, backend_label
from retrieve import IndexNotBuilt, _load, scope_of

app = Flask(__name__)

PAGE = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>UROBOT TW</title>
<style>
 body{font-family:"Microsoft JhengHei",sans-serif;max-width:760px;margin:40px auto;padding:0 16px;color:#1a2733}
 h1{color:#1F4E79;margin-bottom:4px} .sub{color:#667}
 form{display:flex;gap:8px;margin:24px 0}
 input{flex:1;padding:12px;font-size:16px;border:1px solid #bcd;border-radius:8px}
 button{padding:12px 24px;font-size:16px;background:#1F4E79;color:#fff;border:0;border-radius:8px;cursor:pointer}
 .ans{white-space:pre-wrap;background:#f4f8fc;border-left:4px solid #2E74B5;padding:16px;border-radius:0 8px 8px 0}
 .err{white-space:pre-wrap;background:#fdf3f3;border-left:4px solid #c04a4a;padding:16px;border-radius:0 8px 8px 0;color:#7a2020}
 .mode{font-size:12px;color:#889;margin-top:8px}
 .warn{font-size:13px;color:#a55;margin-top:24px;line-height:1.6}
 .scope{background:#fbfcfd;border:1px solid #dde5ec;border-radius:8px;padding:14px 16px;margin-top:24px;font-size:13px;color:#456}
 .scope h3{margin:0 0 8px;font-size:13px;color:#1F4E79}
 .scope ul{margin:0;padding-left:20px} .scope li{margin:2px 0}
 .badge{display:inline-block;font-size:12px;padding:2px 8px;border-radius:10px;margin-bottom:8px}
 .b-gap{background:#fdf0e6;color:#8a4a12} .b-partial{background:#fdf7e0;color:#7a6012}
 .b-unknown{background:#eef0f2;color:#556}
</style></head><body>
<h1>UROBOT<sup>®</sup> TW</h1>
<div class="sub">台灣泌尿科臨床決策輔助 AI — 回答附指引出處</div>
<form method="post">
 <input name="q" placeholder="例：輸尿管結石 7mm 該怎麼處理？" value="{{q}}" autofocus>
 <button>詢問</button>
</form>
{% if error %}<div class="err">⚠️ {{error}}</div>{% endif %}
{% if verdict == 'gap' %}<div class="badge b-gap">語料庫未涵蓋此主題</div>
{% elif verdict == 'partial' %}<div class="badge b-partial">部分涵蓋</div>
{% elif verdict == 'unknown' %}<div class="badge b-unknown">未對應到已宣告主題</div>{% endif %}
{% if a %}<div class="ans">{{a}}</div>{% endif %}
<div class="mode">運作模式：{{mode}}</div>
{% if topics %}<div class="scope"><h3>語料庫涵蓋範圍（{{paragraphs}} 段）</h3>
<ul>{% for t in topics %}<li>{{t}}</li>{% endfor %}</ul>
<div style="margin-top:8px;color:#778">範圍以 scope.json 明示宣告。宣告之外的主題一律不作答，
不以字面相近的段落充數——完整缺口清單見 scope.json 的 gaps。</div></div>{% endif %}
<div class="warn">研發原型・示範語料。輸出僅供臨床參考，不構成醫療建議，{{disclaimer}}<br>
本系統未經任何主管機關審查或核准，不得作為診斷或治療依據。<br>
UROBOT<sup>®</sup> 為英普瑞斯股份有限公司之註冊商標（中華民國註冊第 02509814 號）。</div>
</body></html>"""


@app.route("/", methods=["GET", "POST"])
def home():
    q = request.form.get("q", "").strip() if request.method == "POST" else ""
    a = error = None
    verdict = None
    if q:
        try:
            verdict = scope_of(q)["verdict"]
            a = ask(q)
        except IndexNotBuilt as e:
            error = str(e)
        except LLMError as e:
            error = str(e)
        except Exception as e:  # 不讓使用者看到 500 白畫面
            app.logger.exception("查詢失敗")
            error = f"查詢時發生未預期的錯誤：{type(e).__name__}: {e}"

    try:
        mode = backend_label()
    except Exception:
        mode = "未知"

    try:
        topics = scope_of("")["available"]
        paragraphs = len(_load()["docs"])
    except Exception:
        topics, paragraphs = [], 0

    return render_template_string(
        PAGE, q=q, a=a, error=error, mode=mode, disclaimer=DISCLAIMER,
        verdict=verdict, topics=topics, paragraphs=paragraphs)


@app.route("/healthz")
def healthz():
    """給容器／反向代理用的健康檢查。"""
    try:
        from retrieve import _load
        n = len(_load()["docs"])
    except Exception as e:
        return {"ok": False, "error": str(e)}, 503
    return {"ok": True, "paragraphs": n, "backend": backend_label()}


if __name__ == "__main__":
    app.run(host=os.getenv("UROBOT_HOST", "127.0.0.1"),
            port=int(os.getenv("UROBOT_PORT", "5000")),
            debug=False)
