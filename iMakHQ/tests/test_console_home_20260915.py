# -*- coding: utf-8 -*-
"""出品くん Console (Web 画面) 段階1: ホーム画面 (2026-09-15)。

ユーザー「もっと有料システムみたいな感じで」→ 見本に「こういうのを求めている」→「うん」。
今の出品くん (control_panel.py) は書き換えず、同じ定義・同じ集計を使う。ずれたらここが赤になる。
"""
import os
import re
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "console"))

import server as S  # noqa: E402

PANEL = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()
COUNTS = open(os.path.join(HQ, "console", "counts.py"), encoding="utf-8").read()
SERVER = open(os.path.join(HQ, "console", "server.py"), encoding="utf-8").read()


def test_counts_cover_the_same_keys_as_the_panel():
    panel_keys = set(re.findall(r"d\['(\w+)'\]=", PANEL)) | {"hoju"}
    console_keys = set(re.findall(r'^\s+"(\w+)": lambda', COUNTS, re.M))
    assert panel_keys == console_keys, (panel_keys ^ console_keys)


def test_runnable_only_without_postprocess_or_inputs():
    assert S.runnable({"skip_postprocess": True, "type": "utility"})
    assert not S.runnable({"type": "utility"})                                   # 後処理あり
    assert not S.runnable({"skip_postprocess": True, "ask_amount": True})
    assert not S.runnable({"skip_postprocess": True, "restock_revise": True})
    assert not S.runnable({"skip_postprocess": True, "type": "new"})
    assert not S.runnable({"skip_postprocess": True, "params": [{"name": "x"}]})


def test_summarize_states():
    d = {"hoju": {"search": {"can": 47, "today_can": 0}, "confirm": {"ready": 5, "unjudged": 15},
                  "swap": {"ready": 0, "unjudged": 0}},
         "restock_build": {"actionable": 0, "blocked": 14},
         "ut": {"error": "APIError: 429"}}
    s = S.summarize(d, nightly_ok=True)
    assert s["hoju_search"]["state"] == "night"            # 夜間が動いている日は夜に任せる
    assert s["hoju_confirm"] == {"n": 20, "state": "todo", "note": s["hoju_confirm"]["note"], "hold": 0}
    assert s["hoju_swap"]["state"] == "done"
    assert s["restock_build"]["state"] == "hold" and s["restock_build"]["hold"] == 14
    assert s["ut_confirm"]["state"] == "error"
    assert S.summarize(d, nightly_ok=False)["hoju_search"]["state"] == "todo"   # 夜が転んだ日は青に戻す


def test_night_kinds_match_panel():
    for k in S.NIGHT_KINDS:
        assert re.search(r'"%s": bool\([^\n]*\) and not _auto' % k, PANEL), k


def test_display_label_and_groups():
    assert S.display_label("🩹 PSA 補URL ③ 補充") == "PSA 補URL ③ 補充"
    assert S.group_of("PSA 補URL ③ 補充") == "hoju"
    assert S.group_of("売れた分を補充") == "restock"
    assert S.group_of("棚② 売れない在庫を落とす") == "shelf"


def test_crew_parse():
    txt = "## カタログ — 自分が返す 2件 / 窓口宛 0件\n## 監視くん — 動きなし (最終 5日前)\n## 🔀 ルーティング待ち — 3件\n"
    c = S.parse_crew(txt)
    assert c["route"] == 3 and c["rows"][0]["flag"] == "act" and c["rows"][1]["flag"] == ""


def test_unread_shelf_is_not_shown_as_zero():
    """統合シートが 429 で空 → 公式在庫の件数だけ残る形を「読めなかった」と判定する (9/15 実測)。"""
    broken = [{"cat": "Tシャツ", "usd": 0.0, "count": 133}, {"cat": "TCG", "usd": 0.0, "count": 0}]
    ok = [{"cat": "Tシャツ", "usd": 64069.0, "count": 133}]
    assert S.shelf_looks_unread(broken)
    assert not S.shelf_looks_unread(ok)
    assert not S.shelf_looks_unread([])
    assert '_CACHED_SHEET_COUNTS["data"] = None' in SERVER      # パネルの1分キャッシュに空の結果を残さない


def test_counts_retry_quota_errors_once():
    """9/15 実測: UT / 売れた分の補充 / くじ再仕入れ が 429 で「数えられない」になった。待って数え直す。"""
    sys.path.insert(0, os.path.join(HQ, "console"))
    import counts as C
    assert C.hits_quota({"error": "APIError: [429]: Quota exceeded"})
    assert C.hits_quota({"search": {"can": 29}, "supply": {"can": None, "error": "APIError: [429]"}})
    assert not C.hits_quota({"error": ""})
    assert not C.hits_quota({"error": "KeyError: x"})
    assert "time.sleep(65)" in COUNTS


def test_launcher_vbs_is_ascii_only():
    """9/15 実害: 1行目の日本語コメントを VBScript が ANSI で読み、次の行を飲み込んで起動しなかった。"""
    raw = open(os.path.join(HQ, "console", "start_console.vbs"), "rb").read()
    assert all(b < 0x80 for b in raw)


def test_server_is_local_only_and_posts_need_the_header():
    assert 'HOST = "127.0.0.1"' in SERVER
    assert 'self.headers.get("X-Console") != "1"' in SERVER


def test_panel_itself_is_untouched_by_the_console():
    """Console は control_panel を import するだけ。control_panel 側から console を参照しない。"""
    assert "console" not in re.findall(r"^import (\w+)|^from (\w+)", PANEL)


def test_every_button_has_a_place_on_the_screen():
    """9/16 段階2: 商材 × 段階の格子・一覧に **全ての badge** を置く。

    見本 https://claude.ai/artifact/17znRRHtq61RzUeroRxU41 の形に組み直した時、
    どこにも出していないボタンが黙って消えないようにする (出していない物は画面の
    「ここに置き場が無いボタン」に出るが、既知のものはここで気付けるようにする)。
    """
    app = open(os.path.join(HQ, "console", "static", "app.js"), encoding="utf-8").read()
    placed = set(re.findall(r'"(\w+)"', app))
    sys.path.insert(0, HQ)
    import control_panel as cp
    for s_ in cp.SCRIPTS:
        b = s_.get("badge")
        if b and b != "hoju_status":                     # 件数感は見るだけのボタン
            assert b in placed, b


def test_screen_has_no_crew_or_permanent_log_panel():
    """ユーザー「担当・実行ログの欄は要らない」(2026-09-15)。ログは実行中・直後だけ下から出す。"""
    html = open(os.path.join(HQ, "console", "static", "index.html"), encoding="utf-8").read()
    assert "担当" not in html
    assert 'id="drawer" hidden' in html                  # 既定は出さない


def test_version_and_migration_status():
    """ユーザー「ver管理も」(2026-09-16)。版は 0.x = 旧パネル併用、1.0 = 全ボタンが新画面で押せる。"""
    sys.path.insert(0, os.path.join(HQ, "console"))
    import version as V
    sys.path.insert(0, HQ)
    import control_panel as cp
    assert re.match(r"^\d+\.\d+\.\d+$", V.VERSION)
    ready = [s_ for s_ in cp.SCRIPTS if S.runnable(s_)]
    blocked = [s_ for s_ in cp.SCRIPTS if not S.runnable(s_)]
    assert all(not V.why_not_runnable(s_) for s_ in ready)       # 押せる物に「理由」は出さない
    assert all(V.why_not_runnable(s_) for s_ in blocked)         # 押せない物は必ず理由が出る
    # 1.0 を名乗れるのは全部押せる時だけ
    assert V.VERSION.startswith("0.") or not blocked
    log = open(os.path.join(HQ, "console", "CHANGELOG.md"), encoding="utf-8").read()
    assert V.VERSION in log                                      # 版を上げたら CHANGELOG に1行足す
