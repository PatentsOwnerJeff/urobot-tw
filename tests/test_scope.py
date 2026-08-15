"""涵蓋範圍宣告測試。

這組測試守的是一條安全線：語料庫沒有的主題，系統必須說沒有，
而不是回傳字面上沾邊的段落。實測背景見 scope.json 的說明——
統計式信心指標在這個規模的語料上是失效的（「腎細胞癌標靶治療」的加權詞彙
覆蓋率 0.562，比合法查詢「PSA 篩檢要注意什麼」的 0.267 還高），
所以範圍必須由人明示宣告並用測試守住。
"""
import json
import pathlib
import subprocess
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

SCOPE = json.loads((BASE / "scope.json").read_text(encoding="utf-8"))

# 語料庫確定沒有的主題。問到這些，系統必須拒答。
MUST_REFUSE = [
    "腎細胞癌標靶治療第一線",
    "膀胱癌BCG灌注療程",
    "陰莖癌淋巴結廓清適應症",
    "睪丸癌腫瘤標記怎麼看",
    "男性不孕症精蟲分析標準",
    "女性反覆泌尿道感染要怎麼預防",
    "壓力性尿失禁要不要開刀",
    "神經性膀胱間歇性導尿頻率",
    "小孩膀胱輸尿管逆流怎麼處理",
    "慢性攝護腺炎骨盆疼痛怎麼治療",
]

# 健保語料隨 repo 附上，這些題在任何機器上都必須判為 covered。
MUST_BE_COVERED = [
    "攝護腺肥大用藥健保給付條件",
    "經尿道攝護腺刮除術健保支付點數",
    "攝護腺癌荷爾蒙治療健保給付條件",
    "威而鋼健保有給付嗎",
]

# 這些題依賴 EAU 語料。EAU 不隨 repo 散布，使用者沒自建時主題會降級為 unknown，
# 那是正確行為。共同的安全性質是：不論有沒有自建語料，都不該被誤判為缺口而拒答。
MUST_NOT_BE_REFUSED = MUST_BE_COVERED + [
    "輸尿管結石多大需要手術",
    "PSA 篩檢要注意什麼",
    "OAB第一線用藥",
    "抗膽鹼藥治療膀胱過動症無效下一步",
]


@pytest.fixture(scope="module", autouse=True)
def _index():
    if not (BASE / "index.pkl").exists():
        subprocess.run([sys.executable, "ingest.py"], cwd=BASE, check=True)


@pytest.mark.parametrize("q", MUST_REFUSE)
def test_known_gaps_are_refused(q):
    from retrieve import scope_of

    v = scope_of(q)["verdict"]
    assert v in ("gap", "partial"), \
        f"「{q}」的主題語料庫沒有，卻判為 {v}，會回傳硬湊的段落"


@pytest.mark.parametrize("q", MUST_REFUSE)
def test_gap_reply_contains_no_paragraphs(q):
    """拒答時不得夾帶檢索結果——那正是要避免的誤導。"""
    from answer import ask
    from retrieve import scope_of

    if scope_of(q)["verdict"] != "gap":
        pytest.skip("partial 會照常呈現有涵蓋的部分")
    out = ask(q)
    assert "未涵蓋此主題" in out
    assert "▪ 診斷評估" not in out and "出處：" not in out, \
        f"「{q}」被拒答但仍夾帶了段落內容"


@pytest.mark.parametrize("q", MUST_BE_COVERED)
def test_nhi_topics_covered_on_every_machine(q):
    """健保語料隨 repo 附上，這幾題不論有沒有自建 EAU 語料都要判為已涵蓋。"""
    from retrieve import scope_of

    assert scope_of(q)["verdict"] == "covered", \
        f"「{q}」只依賴隨 repo 附上的健保語料，必須判為 covered"


@pytest.mark.parametrize("q", MUST_NOT_BE_REFUSED)
def test_covered_topics_not_wrongly_refused(q):
    from retrieve import scope_of

    assert scope_of(q)["verdict"] != "gap", \
        f"「{q}」屬於語料庫有能力回答的主題，不該被判為缺口而拒答"


def test_scope_declares_topics_for_every_corpus_prefix():
    """每個 covered 主題所依賴的段落前綴都要真的存在於語料中，
    否則宣告會靜靜地失效（_topic_available 永遠回 False）。"""
    import glob

    prefixes = set()
    for p in glob.glob(str(BASE / "corpus" / "*.jsonl")):
        for line in pathlib.Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                i = json.loads(line)["id"]
                prefixes.update(i[:n] for n in range(1, len(i) + 1))

    for t in SCOPE["covered"]:
        for req in t["requires"]:
            if req.startswith("eau-") and req not in prefixes:
                # EAU 語料不隨 repo 散布，CI 上本來就沒有。這裡不是失敗，
                # 而是 _topic_available 應該把該主題降級——由上面的測試涵蓋。
                continue
            assert req in prefixes, \
                f"主題「{t['topic']}」宣告依賴 {req}-*，但語料中沒有這個前綴"


def test_no_keyword_declared_both_covered_and_gap():
    """同一關鍵字不可同時出現在 covered 與 gaps，否則判定結果取決於宣告順序。"""
    cov = {k.lower() for t in SCOPE["covered"] for k in t["keywords"]}
    gap = {k.lower() for t in SCOPE["gaps"] for k in t["keywords"]}
    assert not (cov & gap), f"關鍵字重複宣告：{sorted(cov & gap)}"


def test_every_gap_has_actionable_note():
    for t in SCOPE["gaps"]:
        assert t.get("note"), f"缺口主題「{t['topic']}」沒有說明缺什麼"


def test_every_gap_tells_user_how_to_fix_it():
    """只說「沒有資料」對使用者沒用。每個缺口都要指出補哪一本指引、去哪拿、
    建成什麼 id 前綴，否則拒答就只是死路一條。"""
    for t in SCOPE["gaps"]:
        fix = t.get("fix")
        assert fix, f"缺口主題「{t['topic']}」沒有 fix 欄位，使用者不知道怎麼補"
        for field in ("guideline", "url", "prefix", "out"):
            assert fix.get(field), f"「{t['topic']}」的 fix 缺少 {field}"
        assert fix["out"].startswith("corpus/"), \
            f"「{t['topic']}」的輸出路徑應在 corpus/ 底下：{fix['out']}"


def test_gap_prefixes_are_gitignored():
    """缺口補完後產生的語料檔多屬第三方著作權，必須已被 .gitignore 排除，
    否則使用者照著指示做完會把受著作權保護的內容提交到公開 repo。"""
    import fnmatch

    ignored = (BASE / ".gitignore").read_text(encoding="utf-8")
    patterns = [l.strip() for l in ignored.splitlines()
                if l.strip() and not l.startswith("#") and "corpus/" in l]
    for t in SCOPE["gaps"]:
        out = t["fix"]["out"]
        assert any(fnmatch.fnmatch(out, p) for p in patterns), \
            f"「{t['topic']}」的產出 {out} 未被 .gitignore 排除（現有規則：{patterns}）"


def test_gap_reply_includes_build_instructions():
    """拒答訊息必須帶著可直接複製的建置指令。"""
    from answer import ask

    out = ask("女性反覆泌尿道感染要怎麼預防")
    assert "build_corpus.py" in out
    assert "uroweb.org" in out
    assert "ingest.py" in out
    assert "scope.json" in out
