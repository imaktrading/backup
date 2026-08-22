"""tcg_new_gen_override.apply_new_gen_override の回帰テスト (2026-06-13・strangler 切替 seam).

固定する不変条件:
  - 値があるときだけ上書き / 新コアが空なら旧値温存 (既定 blank_missing=False = 回帰防止)
  - blank_missing=True で空欄化 (厳格 fail-closed モード)
  - build_listing_fields が err なら行を一切変えない (fail-safe)
  - headers が dict / list どちらでも動く
build_listing_fields/build_title_from_fields を monkeypatch して DB/網羅に依存せずテスト。
"""
import os
import sys

import pytest

_TCG = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "iMakTCG"))
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)

import tcg_listing_fields as TLF          # noqa: E402
import tcg_new_gen_override as OV          # noqa: E402

HEADERS = ["*Title", "C:Game", "C:Set", "C:Card Name", "C:Character", "C:Rarity",
           "C:Features", "C:Manufacturer"]
#          0          1        2        3              4             5           6             7


def _row():
    return ["OLD TITLE", "Pokémon TCG", "Old Set", "Old Name", "Old Char",
            "Common", "", "The Pokémon Company"]


def _patch(monkeypatch, fields, err=None, title="NEW TITLE"):
    monkeypatch.setattr(TLF, "build_listing_fields",
                        lambda cert, hint="", forced_card_id="": (fields, err))
    monkeypatch.setattr(TLF, "build_title_from_fields", lambda f, grade="10": title)


def test_value_only_override_keeps_old_when_new_blank(monkeypatch):
    # 新コア: Set/Name は値あり、Rarity は空、Manufacturer は対象外
    fields = {"C:Set": "VMAX Climax", "C:Card Name": "Zamazenta V", "C:Character": "Zamazenta V",
              "C:Rarity": "", "C:Features": "", "_card_id": "S8b-118"}
    _patch(monkeypatch, fields)
    out = OV.apply_new_gen_override(_row(), HEADERS, "123", override_title=False)
    assert out[2] == "VMAX Climax"      # 上書き
    assert out[3] == "Zamazenta V"      # 汚染除去
    assert out[5] == ""                 # rarity は _ALWAYS_OVERWRITE: 新コア空→旧推測'Common'を空欄化 (#1)
    assert out[7] == "The Pokémon Company"  # 対象外列は不変 (value-only 温存)


def test_rarity_always_synced_blanks_old_guess(monkeypatch):
    # (B) Gemini DISPUTE 修正: 既定モードでも rarity は新コア判定 (空欄含む) を権威として常に反映。
    #     value-only 温存だと旧コアの推測 'Common' が残り #1 が直らないのを防ぐ。
    fields = {"C:Set": "VMAX Climax", "C:Rarity": "", "C:Features": "", "_card_id": "x"}
    _patch(monkeypatch, fields)
    out = OV.apply_new_gen_override(_row(), HEADERS, "123", override_title=False)
    assert out[5] == ""                 # 旧 'Common' (推測) を空欄化
    # 新コアが rarity を持つ場合はその値で上書き
    fields["C:Rarity"] = "Double Rare"
    _patch(monkeypatch, fields)
    out2 = OV.apply_new_gen_override(_row(), HEADERS, "123", override_title=False)
    assert out2[5] == "Double Rare"


def test_strict_mode_blanks_missing(monkeypatch):
    fields = {"C:Set": "VMAX Climax", "C:Rarity": "", "_card_id": "S8b-118"}
    _patch(monkeypatch, fields)
    out = OV.apply_new_gen_override(_row(), HEADERS, "123", blank_missing=True, override_title=False)
    assert out[5] == ""                 # 厳格モード: rarity 推測を空欄化 (#1)


def test_failsafe_on_resolve_error(monkeypatch):
    _patch(monkeypatch, {}, err="解決不能")
    row = _row()
    out = OV.apply_new_gen_override(row, HEADERS, "123")
    assert out == row                   # 解決不能 → 一切変更しない


def test_failsafe_logs_on_resolve_error(monkeypatch, capsys):
    # (4) Gemini DISPUTE 修正: 解決失敗時に silent no-op せず stderr にログ (検知可能に)。
    _patch(monkeypatch, {}, err="catalog 解決不能 (xyz)")
    OV.apply_new_gen_override(_row(), HEADERS, "999")
    err = capsys.readouterr().err
    assert "[new_gen]" in err
    assert "999" in err                 # cert
    assert "SKIP" in err


def test_title_overridden_when_enabled(monkeypatch):
    _patch(monkeypatch, {"C:Set": "VMAX Climax", "_card_id": "x"}, title="PSA 10 ...")
    out = OV.apply_new_gen_override(_row(), HEADERS, "123", override_title=True)
    assert out[0] == "PSA 10 ..."
    out2 = OV.apply_new_gen_override(_row(), HEADERS, "123", override_title=False)
    assert out2[0] == "OLD TITLE"


def test_title_grade_read_from_row_not_hardcoded(monkeypatch):
    # (5b) grade はハードコード "10" でなく行の C:Grade 列から取る (Gemini DISPUTE 2026-06-15)。
    captured = {}

    def fake_title(f, grade="10"):
        captured["grade"] = grade
        return f"PSA {grade} TITLE"
    monkeypatch.setattr(TLF, "build_listing_fields", lambda cert, hint="", forced_card_id="": ({"C:Set": "X", "_card_id": "x"}, None))
    monkeypatch.setattr(TLF, "build_title_from_fields", fake_title)
    hd = HEADERS + ["C:Grade"]
    row = _row() + ["9"]
    out = OV.apply_new_gen_override(row, hd, "123", override_title=True)
    assert captured["grade"] == "9"          # C:Grade 列の値を使用
    assert out[0] == "PSA 9 TITLE"


def test_title_grade_defaults_10_when_no_column(monkeypatch):
    # C:Grade 列が無い/空なら従来通り "10" (PSA10限定運用の既定)
    monkeypatch.setattr(TLF, "build_listing_fields", lambda cert, hint="", forced_card_id="": ({"C:Set": "X", "_card_id": "x"}, None))
    monkeypatch.setattr(TLF, "build_title_from_fields", lambda f, grade="10": f"PSA {grade} T")
    out = OV.apply_new_gen_override(_row(), HEADERS, "123", override_title=True)
    assert out[0] == "PSA 10 T"


def test_headers_as_dict(monkeypatch):
    _patch(monkeypatch, {"C:Set": "VMAX Climax", "_card_id": "x"})
    hd = {h: i for i, h in enumerate(HEADERS)}
    out = OV.apply_new_gen_override(_row(), hd, "123", override_title=False)
    assert out[2] == "VMAX Climax"


def test_hp_stage_columns_populated_when_present(monkeypatch):
    # Phase3: psa_to_csv が C:HP/C:Stage 列を持てば override が catalog 由来値を書く。
    hd = HEADERS + ["C:HP", "C:Stage"]
    row = _row() + ["", ""]
    _patch(monkeypatch, {"C:HP": "320", "C:Stage": "Basic", "_card_id": "x"})
    out = OV.apply_new_gen_override(row, hd, "123", override_title=False)
    assert out[hd.index("C:HP")] == "320"
    assert out[hd.index("C:Stage")] == "Basic"


def test_forced_card_id_passed_through(monkeypatch):
    # verify→build: 人が確定した product_id を build_listing_fields に forced_card_id で渡す。
    captured = {}

    def fake_blf(cert, hint="", forced_card_id=""):
        captured["forced"] = forced_card_id
        return ({"C:Set": "VMAX Climax", "_card_id": forced_card_id or "auto"}, None)
    monkeypatch.setattr(TLF, "build_listing_fields", fake_blf)
    monkeypatch.setattr(TLF, "build_title_from_fields", lambda f, grade="10": "T")
    OV.apply_new_gen_override(_row(), HEADERS, "123", forced_card_id="S8b-241", override_title=False)
    assert captured["forced"] == "S8b-241"      # 確定 pid が新コアに渡る
    # 未指定時は空 (自動解決)
    OV.apply_new_gen_override(_row(), HEADERS, "123", override_title=False)
    assert captured["forced"] == ""


def test_env_enabled(monkeypatch):
    monkeypatch.delenv("TCG_USE_NEW_GEN", raising=False)
    assert OV.env_enabled() is False
    monkeypatch.setenv("TCG_USE_NEW_GEN", "1")
    assert OV.env_enabled() is True


def test_features_overridden_when_new_has_value(monkeypatch):
    # C:Features は新コアが正規化済 facet 値を持てば上書き (2026-06-14 以降)
    fields = {"C:Set": "VMAX Climax", "C:Features": "Alternative Art", "_card_id": "x"}
    _patch(monkeypatch, fields)
    row = _row()
    fi = HEADERS.index("C:Features")
    row[fi] = "OldFeat"
    out = OV.apply_new_gen_override(row, HEADERS, "123", override_title=False)
    assert out[fi] == "Alternative Art"      # 正規化値で上書き


def test_features_blanked_when_catalog_blank(monkeypatch):
    """★2026-08-22 反転: 新コア (catalog features_ebay) が空なら **空欄で出す**。

    旧仕様は value-only で旧コアの値を温存していたが、旧コアは Features を rarity から
    埋めていたため、8/22 の入稿で C:Features='Art Rare' / 'Super Rare' が 4件 eBay に出た。
    契約 (_contract_aspects.yaml): Features の値は catalog だけが持つ。空欄も権威。
    """
    fields = {"C:Set": "VMAX Climax", "C:Features": "", "_card_id": "x"}
    _patch(monkeypatch, fields)
    row = _row()
    fi = HEADERS.index("C:Features")
    row[fi] = "OldFeat"
    out = OV.apply_new_gen_override(row, HEADERS, "123", override_title=False)
    assert out[fi] == ""                     # catalog が空 → 空欄 (旧値で埋め戻さない)
