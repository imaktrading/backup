"""Regression: 2026-06-21 — orphan canonical KEY 掃除(歩留まり激減の恒久対策)。

KEY は「カード認識時」に書かれるが dedup は「出品済」と解釈 → 認識止まり(未出品)の在庫が
誤ブロックされる。未出品(B列空)かつ同一カードが一度も出品されてない行の KEY を消す。
出品済の2枚目(別cert)は残す。snapshot に痕跡ある cert は安全のため除外。
"""
import importlib.util
from pathlib import Path
import sys

_P = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools" / "psa_orphan_key_clean.py"
sys.path.insert(0, str(_P.parent))
_spec = importlib.util.spec_from_file_location("psa_orphan_key_clean_t", _P)
oc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oc)


def _r(sheet, row, cert, key, b):
    return {"sheet": sheet, "row": row, "cert": cert, "key": key, "b": b}


def test_orphan_never_listed_cleared():
    # KEY有 + B列空 + 同KEYに出品済(B埋)行が無い → orphan(消す)
    rows = [_r("HIGH", 2, "c1", "K-A", "")]
    out = oc.find_orphans(rows)
    assert len(out) == 1 and out[0]["row"] == 2 and out[0]["key"] == "K-A"


def test_listed_card_kept():
    # B列埋(出品済) → orphanでない
    rows = [_r("HIGH", 2, "c1", "K-A", "358000000001")]
    assert oc.find_orphans(rows) == []


def test_second_copy_kept():
    # K-B: 1枚出品済(B埋) + 2枚目(別cert・B空)。2枚目は「同KEYに出品済行あり」→ 消さない
    rows = [_r("HIGH", 2, "c1", "K-B", "358000000002"),   # 出品済
            _r("HIGH", 3, "c2", "K-B", "")]               # 2枚目 → 残す
    out = oc.find_orphans(rows)
    assert out == []   # 2枚目は重複除外を維持するため KEY を残す


def test_snapshot_cert_excluded():
    # B列空・未出品だが cert が snapshot にある(出品済の疑い) → 消さない(同cert二重出品防止)
    rows = [_r("HIGH", 2, "999888", "K-C", "")]
    assert oc.find_orphans(rows, snapshot_certs={"999888"}) == []
    # snapshot に無ければ消す
    assert len(oc.find_orphans(rows, snapshot_certs=set())) == 1


def test_cross_sheet_listed_blocks_clear():
    # LOW に出品済(B埋) K-D があれば、HIGH の K-D(B空)は2枚目扱いで残す(両sheet横断)
    rows = [_r("LOW", 5, "c9", "K-D", "358000000009"),
            _r("HIGH", 8, "c10", "K-D", "")]
    assert oc.find_orphans(rows) == []


def test_control_panel_wires_orphan_clean_before_psa_new():
    """PSA新規ボタンの生成前に orphan掃除が自動で走る配線を固定(恒久対策の回帰ガード)。"""
    cp = (Path(__file__).resolve().parent.parent / "iMakHQ" / "control_panel.py").read_text(encoding="utf-8")
    assert "def _run_psa_orphan_clean" in cp                       # 掃除ヘルパ存在
    assert "psa_orphan_key_clean.py" in cp                         # ツールを呼ぶ
    # run_script 内で PSA TCG new の時に呼ぶ(cmd 構築の前)
    i = cp.index("self._run_psa_orphan_clean()")
    assert 'category") == "PSA TCG"' in cp[i - 200:i]              # PSA新規限定
    assert cp.index("self._run_psa_orphan_clean()") < cp.index('cmd = list(script["cmd"])')
