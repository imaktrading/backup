"""カード番号は **KEY (catalog SSOT) が最優先** — build_card_query 本体で担保する (2026-08-03)。

## 何を直したか

`build_card_query` は `_extract_card_no(title, set_no)` で **set_no → title** の順に番号を
決めており、**KEY を持っていても番号だけ自由文から取っていた**。
この title は商品管理シートの列で、**仕入元(メルカリ)の出品タイトルをそのまま**持つ
= 他人が書いた自由文。番号を書き間違えていることがある。

実測 (2026-08-01 / live PSA 257件中2件):
  itemID 358761687924  title `OP10-012`(ドラゴン十三號) / KEY `ST12-012`(シャーロット・プリン)
  itemID 358761687925  title `OP01-008`(キャベンディッシュ) / KEY `EB01-056`(フランペ)
→ 別カードの番号で探すので0件 → **「市場に無い」と誤診**。

## なぜ本体を直したか (呼び出し側のパッチではなく)

従来は `psa_hoju_fill.build_search_query` が **後から card_no / name_jp / multi_variant を
上書きする**パッチを持っていた。これだと:

- `psa_resource_gate` など**別の呼び出し側は直らない**
- 「KEY からの番号の作り方」が2箇所に散り、片方だけ直して食い違う
  (実際に `_card_no_from_key` が psa_hoju_fill と gate に二重定義されていた)

→ 本体を **KEY → set_no → title** の順にし、呼び出し側のパッチを削除した。
   `card_no_from_key` も本体に置き、psa_hoju_fill 側は薄い別名だけ残す。

## 守る性質

1. KEY があれば **title/set_no が何であっても** KEY の番号を使う
2. KEY が無い / 数字を含まない / url-key (`item:` / `shops:`) は従来どおり fallback
3. 変種 suffix (`_p1` / `_ST18`) とカテゴリ接頭辞 (`pokemon_tcg:`) は落とす
"""
import os
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import mercari_psa_resource as mp  # noqa: E402


def _no_db(monkeypatch):
    """catalog DB を触らせない (純粋な番号決定ロジックだけを見る)."""
    monkeypatch.setattr(mp, "card_meta_for_key", lambda k: None)
    monkeypatch.setattr(mp, "name_jp_for_card", lambda n: None)
    monkeypatch.setattr(mp, "_is_multi_variant", lambda n, c="": False)


def test_key_wins_over_supplier_title(monkeypatch):
    """★本丸。仕入元タイトルが別カードの番号でも KEY を採る."""
    _no_db(monkeypatch)
    q = mp.build_card_query("PSA10 シャーロット・プリン OP10-012", "",
                            key="one_piece_tcg:ST12-012")
    assert q["card_no"] == "ST12-012", f"title の誤番号を採ってしまった: {q['card_no']}"


def test_key_wins_over_set_no(monkeypatch):
    """set_no (呼び出し側の構造化値) より KEY が優先されること."""
    _no_db(monkeypatch)
    q = mp.build_card_query("", "OP01-008", key="one_piece_tcg:EB01-056")
    assert q["card_no"] == "EB01-056"


def test_variant_suffix_and_category_prefix_are_stripped(monkeypatch):
    """`pokemon_tcg:SV5a-083_p1` → `SV5A-083` (接頭辞と変種suffixを落とす)."""
    _no_db(monkeypatch)
    q = mp.build_card_query("", "", key="pokemon_tcg:SV5a-083_p1")
    assert q["card_no"] == "SV5A-083"


def test_falls_back_to_title_when_no_key(monkeypatch):
    """KEY が無ければ従来どおり set_no → title (後方互換)."""
    _no_db(monkeypatch)
    assert mp.build_card_query("PSA10 Nami OP08-106", "")["card_no"] == "OP08-106"
    assert mp.build_card_query("", "OP08-106")["card_no"] == "OP08-106"


def test_url_key_and_non_numeric_key_are_ignored(monkeypatch):
    """url-key / 数字を含まない KEY は使わない (fail-closed)。title に落ちる."""
    _no_db(monkeypatch)
    for bad in ("item:m123", "shops:abc", "pokemon_tcg:PROMO"):
        q = mp.build_card_query("PSA10 Nami OP08-106", "", key=bad)
        assert q["card_no"] == "OP08-106", f"{bad} を番号として使ってしまった"


def test_card_no_from_key_is_defined_once():
    """★二重定義を作らない。psa_hoju_fill 側は本体へ委譲するだけであること.

    以前は psa_hoju_fill と gate に別実装があり、**片方だけ直して食い違っていた**。
    """
    import io
    src = io.open(os.path.join(TOOLS, "psa_hoju_fill.py"), encoding="utf-8").read()
    body = src.split("def _card_no_from_key")[1].split("def ")[0]
    assert "card_no_from_key(key)" in body and "mercari_psa_resource" in body, \
        "psa_hoju_fill が独自実装を持っている (本体へ委譲すること)"
    assert "split(\"_\")[0]" not in body, "番号の作り方が二重定義されている"
