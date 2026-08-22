# -*- coding: utf-8 -*-
"""「catalog に別 id で在る」のに追加依頼を出す誤起票を止める (2026-08-22)。

実害 (2026-08-21): 「catalog 未登録」として 5件の追加依頼を出したが、
  3件は当日 catalog に登録済 / 2件は出品くんが組んだ id (`PRB01-004`) で探していただけで
  実体は `ST17-004_p1` として在った。catalog から訂正が2本返り、同日に訂正の訂正まで出した。
  既存の `_filter_catalog_present` は **期待 pid の完全一致**しか見ないので素通りしていた。

守るもの:
  - resolver (psa_preflight.classify) が RESOLVED / INDEX-FAILURE / REVIEW を返す cert は
    依頼書に載せない
  - GAP (本当に無い) は従来どおり載せる
  - 判定不能 (cert が抜けない / cache が無い / 例外) は **載せる** = fail-closed
  - 画像が無い / variant 欠落 の依頼は落とさない (行は在るが中身が足りない依頼なので別物)
"""
import importlib.util
import os
import sys
import types

import pytest

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")


def _load():
    spec = importlib.util.spec_from_file_location(
        "auto_catalog_add_request_t", os.path.join(_TOOLS, "auto_catalog_add_request.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_preflight(monkeypatch, tmp_path, status_by_cert, raise_on=()):
    """psa_preflight を偽物に差し替える (DB も cache も触らない)。"""
    fake = types.ModuleType("psa_preflight")
    fake.CATALOG_DB = ":memory:"
    fake.PSA_CERTS_DIR = tmp_path

    def classify(cert, meta, con):
        if cert in raise_on:
            raise RuntimeError("resolver 落ちた")
        return {"status": status_by_cert.get(cert, "GAP"), "product_id": "ST17-004_p1"}

    fake.classify = classify
    monkeypatch.setitem(sys.modules, "psa_preflight", fake)
    for cert in status_by_cert:
        (tmp_path / f"{cert}.json").write_text("{}", encoding="utf-8")
    for cert in raise_on:
        (tmp_path / f"{cert}.json").write_text("{}", encoding="utf-8")


def _rows(*models):
    return {"one_piece_tcg": [{"model": m} for m in models]}


@pytest.mark.parametrize("status", ["RESOLVED", "INDEX-FAILURE", "REVIEW"])
def test_drops_when_catalog_has_the_card(monkeypatch, tmp_path, status):
    mod = _load()
    _fake_preflight(monkeypatch, tmp_path, {"155040105": status})
    by_cat = _rows("cert155040105 BOA HANCOCK #004 (auto候補無=該当なし 要調査)")
    removed = mod._filter_resolver_resolves(by_cat)
    assert removed == 1
    assert by_cat == {}, f"{status} なのに依頼書に残っている"


def test_keeps_real_gap(monkeypatch, tmp_path):
    mod = _load()
    _fake_preflight(monkeypatch, tmp_path, {"155040105": "GAP"})
    by_cat = _rows("cert155040105 BOA HANCOCK #004 (auto候補無=該当なし 要調査)")
    assert mod._filter_resolver_resolves(by_cat) == 0
    assert len(by_cat["one_piece_tcg"]) == 1


def test_keeps_when_undecidable(monkeypatch, tmp_path):
    """cert が抜けない / cache が無い / 例外 → 落とさない (fail-closed)。"""
    mod = _load()
    _fake_preflight(monkeypatch, tmp_path, {"111111111": "RESOLVED"}, raise_on=("222222222",))
    by_cat = _rows("cert なしのモデル名",                       # cert 抜けない
                   "cert999999999 CACHE が無い (auto候補無=該当なし 要調査)",   # cache 無
                   "cert222222222 resolver が落ちる (auto候補無=該当なし 要調査)")  # 例外
    assert mod._filter_resolver_resolves(by_cat) == 0
    assert len(by_cat["one_piece_tcg"]) == 3


def test_keeps_no_image_and_variant_gap_requests(monkeypatch, tmp_path):
    mod = _load()
    _fake_preflight(monkeypatch, tmp_path, {"155040105": "RESOLVED", "155606219": "RESOLVED"})
    by_cat = _rows(f"cert155040105 X ({mod._NO_IMAGE_NOTE_MARK} 画像を追加してほしい)",
                   f"cert155606219 Y ({mod._VARIANT_GAP_NOTE_MARK} variant欠落の疑い)")
    assert mod._filter_resolver_resolves(by_cat) == 0
    assert len(by_cat["one_piece_tcg"]) == 2


def test_gate_is_wired_into_main():
    src = open(os.path.join(_TOOLS, "auto_catalog_add_request.py"), encoding="utf-8").read()
    assert "_filter_resolver_resolves(new_by_cat, unique)" in src, \
        "main() から呼ばれていないと、関数が在るだけで誤起票は止まらない"
