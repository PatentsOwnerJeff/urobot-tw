"""UROBOT TW — Web 介面（Flask）
執行：python app.py → 瀏覽器開 http://127.0.0.1:5000
"""
from flask import Flask, request, render_template_string
from answer import ask

app = Flask(__name__)

PAGE = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>UROBOT TW</title>
<style>
 body{font-family:"Microsoft JhengHei",sans-serif;max-width:760px;margin:40px auto;padding:0 16px;color:#1a2733}
 h1{color:#1F4E79} .sub{color:#667}
 form{display:flex;gap:8px;margin:24px 0}
 input{flex:1;padding:12px;font-size:16px;border:1px solid #bcd;border-radius:8px}
 button{padding:12px 24px;font-size:16px;background:#1F4E79;color:#fff;border:0;border-radius:8px;cursor:pointer}
 .ans{white-space:pre-wrap;background:#f4f8fc;border-left:4px solid #2E74B5;padding:16px;border-radius:0 8px 8px 0}
 .warn{font-size:13px;color:#a55;margin-top:24px}
</style></head><body>
<h1>UROBOT TW</h1>
<div class="sub">台灣泌尿科臨床決策輔助 AI — 回答附指引出處</div>
<form method="post">
 <input name="q" placeholder="例：輸尿管結石 7mm 該怎麼處理？" value="{{q}}" autofocus>
 <button>詢問</button>
</form>
{% if a %}<div class="ans">{{a}}</div>{% endif %}
<div class="warn">研發原型・示範語料。輸出僅供臨床參考，不構成醫療建議，最終決策由醫師負責。</div>
</body></html>"""

@app.route("/", methods=["GET", "POST"])
def home():
    q = request.form.get("q", "").strip() if request.method == "POST" else ""
    a = ask(q) if q else None
    return render_template_string(PAGE, q=q, a=a)

if __name__ == "__main__":
    app.run(debug=False)
