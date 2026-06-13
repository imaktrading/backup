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
    monkeypatch.setattr(TLF, "build_listing_fields", lambda cert, hint="": (fields, err))
    monkeypatch.setattr(TLF, "build_title_from_fields", lambda f, grade="10": title)


def test_value_only_override_keeps_old_when_new_blank(monkeypatch):
    # 新コア: Set/Name は値あり、Rarity は空、Manufacturer は対象外
    fields = {"C:Set": "VMAX Climax", "C:Card Name": "Zamazenta V", "C:Character": "Zamazenta V",
              "C:Rarity": "", "C:Features": "", "_card_id": "S8b-118"}
    _patch(monkeypatch, fields)
    out = OV.apply_new_gen_override(_row(), HEADERS, "123", override_title=False)
    assert out[2] == "VMAX Climax"      # 上書き
    assert out[3] == "Zamazenta V"      # 汚染除去
    assert out[5] == "Common"           # 新コア空 → 旧値温存 (回帰防止)
    assert out[7] == "The Pokémon Company"  # 対象外列は不変


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


def test_title_overridden_when_enabled(monkeypatch):
    _patch(monkeypatch, {"C:Set": "VMAX Climax", "_card_id": "x"}, title="PSA 10 ...")
    out = OV.apply_new_gen_override(_row(), HEADERS, "123", override_title=True)
    assert out[0] == "PSA 10 ..."
    out2 = OV.apply_new_gen_override(_row(), HEADERS, "123", override_title=False)
    assert out2[0] == "OLD TITLE"


def test_headers_as_dict(monkeypatch):
    _patch(monkeypatch, {"C:Set": "VMAX Climax", "_card_id": "x"})
    hd = {h: i for i, h in enumerate(HEADERS)}
    out = OV.apply_new_gen_override(_row(), hd, "123", override_title=False)
    assert out[2] == "VMAX Climax"


def test_env_enabled(monkeypatch):
    monkeypatch.delenv("TCG_USE_NEW_GEN", raising=False)
    assert OV.env_enabled() is False
    monkeypatch.setenv("TCG_USE_NEW_GEN", "1")
    assert OV.env_enabled() is True
