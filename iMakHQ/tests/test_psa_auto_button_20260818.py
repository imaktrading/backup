# -*- coding: utf-8 -*-
"""🤖PSA自動 ボタン (2026-08-18 ユーザー指示「1つだけにまとめて。CSV監査くんもセットで」)。

守る性質:
  1. PSA TCG の行にボタンがあり、生成の中身は 新規 と同じ (別コアに分岐させない)
  2. 締めの3手が **この順** で走る (itemID を書いてからでないと広告に登録できない)
  3. CSV監査くんが最後 (①②はシートと広告しか触らないので監査結果に影響しない)
  4. 締めは 🤖PSA自動 のときだけ (通常の 新規 の挙動を変えない)
"""
import io
import os
import re

CP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control_panel.py")


def _src():
    return io.open(CP, encoding="utf-8").read()


def _entry():
    s = _src()
    i = s.index('"label": "🤖自動"')
    return s[s.rindex("    {\n", 0, i):s.index("    },\n", i)]


def test_PSA_TCGの行にある():
    e = _entry()
    assert '"category": "PSA TCG"' in e
    # ★同じ type で足すと後勝ちでカテゴリボタンを乗っ取る (2026-08-18 に実際にやった)
    assert '"type": "auto"' in e


def test_生成の中身は新規と同じ():
    """別コアや別スクリプトに分岐させない (挙動が2本に割れると事故る)。"""
    e = _entry()
    assert '"cmd": ["python", "psa_to_csv.py"]' in e
    assert '"TCG_USE_NEW_GEN": "1"' in e and '"PSA_VERIFY_BEFORE_BUILD": "1"' in e


def test_目視ダブルチェックを外していない():
    assert '"double_check": True' in _entry()


def test_締めはauto_fullのときだけ():
    s = _src()
    assert 'if _entry_now.get("auto_full"):' in s
    assert '"auto_full": True' in _entry()


def test_締めが失敗しても走行を止めない():
    """表示・後始末なので、入稿物 (CSV) の生成結果を巻き添えにしない。"""
    s = _src()
    i = s.index("def _run_auto_full_tail")
    body = s[i:s.index("\ndef ", i + 1)]
    assert "続行" in body and "except Exception" in body


def test_同じカテゴリでtypeが重複していない():
    """categories[cat][type] は後勝ちで上書きされるので、重複すると片方が消える。

    実害 (2026-08-18): 🤖自動 を type="new" で足したら PSA TCG のカテゴリボタンが
    自動の方を指すようになり、新規ボタンが画面から消えた。
    """
    src = _src()
    pairs = re.findall(r'"category":\s*("[^"]+"|None),\s*"type":\s*"([a-z_]+)"', src)
    seen = {}
    for cat, typ in pairs:
        if cat == "None" or typ == "utility":
            continue
        key = (cat, typ)
        assert key not in seen, f"{cat} に type={typ} が2つある = 片方がボタンから消える"
        seen[key] = True


def test_自動ボタンが描画される():
    """カテゴリのセルに 自動 を並べる分岐が消えていないこと。"""
    s = _src()
    assert 'categories[cat_name].get("auto")' in s
    assert 'SCRIPTS[auto_idx]["label"]' in s


# ── 完全自動 (A) の順番とメール (2026-08-18) ──────────────────────────
def test_締めの順番は監査_入稿_書戻し_広告():
    """監査は入稿前の関所なので必ず先。itemID は入稿しないと出ないので書戻しは後。"""
    s = _src()
    i = s.index("def _run_auto_full_tail")
    body = s[i:s.index("\ndef ", i + 1)]
    names = re.findall(
        r'csv_auditor\.py|ebay_upload_csv\.py|itemid_writeback_audit\.py|ads_add_new_listings\.py',
        body)
    assert names == ["csv_auditor.py", "ebay_upload_csv.py",
                     "itemid_writeback_audit.py", "ads_add_new_listings.py"]


def test_出品は本番モードで呼ぶ():
    s = _src()
    i = s.index("def _run_auto_full_tail")
    body = s[i:s.index("\ndef ", i + 1)]
    assert '"--write"' in body and "--result-json" in body


def test_メール送信の失敗を握り潰さない():
    """『飛ばなかったのに成功扱い』が一番まずい失敗 (監視くんの申し送り)。"""
    s = _src()
    i = s.index("def _mail_upload_result")
    body = s[i:s.index("\ndef ", i + 1)]
    assert "returncode == 0" in body and "メール送信に失敗しました" in body


def test_メール本文は件数とURL():
    import importlib.util
    spec = importlib.util.spec_from_file_location("cp", CP)
    # control_panel は tkinter を import するので、純関数だけ切り出して評価する
    src = _src()
    i = src.index("def build_upload_mail")
    ns = {}
    exec(src[i:src.index("\ndef ", i + 1)], ns)
    subject, body = ns["build_upload_mail"](
        {"listed": [{"label": "PSA10-1", "item_id": "820013549916"}], "ng": 0})
    assert "1件" in subject
    assert "https://www.ebay.com/itm/820013549916" in body
    subject_ng, body_ng = ns["build_upload_mail"]({"listed": [], "ng": 2})
    assert "失敗" in subject_ng and "失敗 2件" in body_ng


def test_自動だけ20件_手動は既定のまま():
    """ユーザー指示 (2026-08-18)。上限はコード分岐でなく env で注入する。"""
    e = _entry()
    assert '"PSA_BATCH_LIMIT": "20"' in e
    src = _src()
    i = src.index('"category": "PSA TCG", "type": "new"')
    manual = src[i:src.index("    },\n", i)]
    assert "PSA_BATCH_LIMIT" not in manual, "手動側に上限を足さない (既定15のまま)"


def test_生成側は環境変数で上限を読む():
    gen = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "iMakTCG", "psa_to_csv.py")
    s = io.open(gen, encoding="utf-8").read()
    assert 'os.environ.get("PSA_BATCH_LIMIT") or 15' in s, "既定は 15 のまま"
