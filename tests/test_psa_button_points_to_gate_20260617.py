"""Regression: 2026-06-17 — 「PSA再仕入れ照合」ボタンは psa_resource_gate.py を起動する。

旧 mercari_psa_resource.py(Mercari単体・確認ゲート/PDCA無し)に張替わると、せっかくの
①現物=②catalog 目視確認ゲートも不一致PDCAも走らない。ボタンが gate を指すことを固定。
"""
from pathlib import Path

_SRC = (Path(__file__).resolve().parent.parent / "iMakHQ" / "control_panel.py").read_text(encoding="utf-8")


def test_psa_button_runs_gate_not_old_mercari_only():
    # ★2026-10-04: ① のボタンは ①→②→③ を続けて走らせる psa_restock_chain.py を起動する (ユーザー「ボタン分けずに」)。
    #   その最初の手順が gate であることを固定する (旧 Mercari 単体に戻っていないこと)
    i = _SRC.index("🛒 PSA 再仕入れ ①→③ 目視して在庫を戻す")  # 2026-10-06 ラベルを実態に合わせた
    block = _SRC[i:i + 1500]
    assert '"psa_restock_chain.py"' in block, "PSA再仕入れ①ボタンが一連の処理を起動していない"
    assert '"mercari_psa_resource.py"' not in block, "旧Mercari単体スクリプトに戻っている"
    chain = (Path(__file__).resolve().parent.parent / "iMakHQ" / "tools" / "psa_restock_chain.py").read_text(
        encoding="utf-8")
    assert chain.index('"psa_resource_gate.py"') < chain.index('"psa_restock_build.py"')
