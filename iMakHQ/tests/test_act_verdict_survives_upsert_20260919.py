"""Act が確かめた結論は、翌日の再検出で消えないこと (2026-09-19・提案1)。

実害: 結論を evidence に書いても、翌日 generator が同じ dkey を再検出した瞬間に
上書きされ、翌日の Act が同じ調査を最初からやり直していた (queue 646 で実測)。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import pdca_store as P


def _con(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DB_PATH", str(tmp_path / "pdca.db"), raising=False)
    return P.connect(str(tmp_path / "pdca.db"))


def test_再検出しても結論は残る(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    qid = P.upsert_improvement(con, "pokemon_tcg", "cert1", "catalog_add",
                               evidence="1日目", finding_type="catalog_gap", ts="2026-09-18")
    P.set_act_verdict(con, qid, "誤検出: catalog に在る", ts="2026-09-18")
    P.upsert_improvement(con, "pokemon_tcg", "cert1", "catalog_add",
                         evidence="2日目 (上書きされる)", finding_type="catalog_gap",
                         ts="2026-09-19")
    assert P.get_act_verdict(con, qid) == "誤検出: catalog に在る"
    row = con.execute("SELECT evidence FROM improvement_queue WHERE queue_id=?", (qid,)).fetchone()
    assert row[0] == "2日目 (上書きされる)"      # evidence は従来どおり最新で上書き


def test_結論を書いていなければ空(tmp_path, monkeypatch):
    con = _con(tmp_path, monkeypatch)
    qid = P.upsert_improvement(con, "pokemon_tcg", "cert2", "catalog_add",
                               finding_type="catalog_gap", ts="2026-09-19")
    assert P.get_act_verdict(con, qid) == ""
