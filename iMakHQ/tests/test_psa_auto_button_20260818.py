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


def test_締めの3手がこの順で並ぶ():
    s = _src()
    i = s.index("def _run_auto_full_tail")
    body = s[i:s.index("\ndef ", i + 1)]
    order = [m.start() for m in re.finditer(
        r'itemid_writeback_audit\.py|ads_add_new_listings\.py|csv_auditor\.py', body)]
    names = re.findall(r'itemid_writeback_audit\.py|ads_add_new_listings\.py|csv_auditor\.py', body)
    assert names == ["itemid_writeback_audit.py", "ads_add_new_listings.py", "csv_auditor.py"]
    assert order == sorted(order)


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
