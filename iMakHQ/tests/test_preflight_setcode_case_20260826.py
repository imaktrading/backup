# -*- coding: utf-8 -*-
"""catalog に在るカードを「未収録」と言わない (2026-08-26).

cert139291730 は `[GAP=catalog未収録]` で毎日落ちていたが、catalog には
`pokemon_tcg / SM9a-067` が画像つきで実在する。原因は2つで、どちらも引き方 (②) 側:

  - `_zero_o_variants` が **元の綴りを捨てて**いた (`SM9a` が候補に入らない)
  - SQLite の `=` は大小を区別するので `sm9a-067` / `SM9A-067` では引けない

判定 (1丁目1番地): ①カタログは正しい → ②を直す。**自動採用はしない** —
実在したら GAP ではなく INDEX-FAILURE に落として目視へ回す (fail-closed 維持)。

依頼書: hq/requests/2026-08-26_act_code_proposals_tcg.md 提案3
回答書: hq/requests/2026-08-26_act_code_proposals_tcg_response.md (5)
"""
import importlib.util
import sqlite3
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "tools"


def _load():
    spec = importlib.util.spec_from_file_location("psa_preflight", str(_TOOLS / "psa_preflight.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_original_spelling_is_kept():
    P = _load()
    assert "SM9a" in P._zero_o_variants("SM9a"), \
        "元の綴りを候補から外している (resolver は product_id 直引きではない)"


def _fake_db():
    """catalog を模した最小 DB (小文字混じりの product_id)。"""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE products (category TEXT, product_id TEXT, name_en TEXT, name TEXT)")
    con.execute("INSERT INTO products VALUES ('pokemon_tcg','SM9a-067','Gardevoir & Sylveon GX','')")
    con.commit()
    return con


def _classify(P, con, brand, num, subject="GARDEVOIR & SYLVEON GX"):
    return P.classify("139291730",
                      {"Brand": brand, "CardNumber": num, "Subject": subject}, con)


def test_mixed_case_setcode_is_index_failure_not_gap(monkeypatch):
    P = _load()
    monkeypatch.setattr(P, "_ensure_catalog", lambda: None)
    monkeypatch.setattr(P, "_FRANCHISE",
                        {"pokemon_tcg": (lambda *a, **k: None, lambda b: "SM9a")},
                        raising=False)
    monkeypatch.setattr(P, "_confirmed_pid", lambda cert: None)
    monkeypatch.setattr(P, "_out_of_scope", lambda: {})
    res = _classify(P, _fake_db(), "POKEMON JAPANESE SUN & MOON NIGHT UNISON", "067")
    assert res["status"] == "INDEX-FAILURE", f"GAP のまま落ちている: {res}"
    assert res["recovered"] == "SM9a-067"


def test_still_gap_when_really_absent(monkeypatch):
    """本当に無い時まで拾わない (fail-closed の向きを変えていない)。"""
    P = _load()
    monkeypatch.setattr(P, "_ensure_catalog", lambda: None)
    monkeypatch.setattr(P, "_FRANCHISE",
                        {"pokemon_tcg": (lambda *a, **k: None, lambda b: "SM9a")},
                        raising=False)
    monkeypatch.setattr(P, "_confirmed_pid", lambda cert: None)
    monkeypatch.setattr(P, "_out_of_scope", lambda: {})
    res = _classify(P, _fake_db(), "POKEMON JAPANESE SUN & MOON NIGHT UNISON", "999",
                    subject="NOBODY")
    assert res["status"] == "GAP", res


def test_index_failure_is_not_auto_adopted():
    """INDEX-FAILURE は product_id を返さない = 出品側が勝手に採用できない。"""
    P = _load()
    con = _fake_db()

    class _NoAuto:
        pass

    # classify が INDEX-FAILURE を返す時、res に product_id は入っていないこと
    import inspect
    src = inspect.getsource(P.classify)
    idx = src.index('res["status"] = "INDEX-FAILURE"')
    seg = src[idx:idx + 400]
    assert 'res["product_id"]' not in seg, \
        "INDEX-FAILURE で product_id を埋めると出品側が目視なしで採用してしまう"
    con.close()
