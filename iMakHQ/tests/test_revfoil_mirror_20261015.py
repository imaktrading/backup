# -*- coding: utf-8 -*-
"""2026-10-15 B-20261015-024: PSA の略記 REV.FOIL もミラー (Reverse Holo)。読み方は psa_label_finish の1か所。

実害: cert 202397994 JOLTEON-REV.FOIL TAG TEAM GX ALL STARS が通常版の KEY SM12a-042 で CSV に載った。
"""
import inspect
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (os.path.join(_ROOT, "iMakHQ", "tools"), os.path.join(_ROOT, "iMakTCG")):
    if p not in sys.path:
        sys.path.insert(0, p)


def test_revfoil_reads_as_reverse_holo():
    import psa_variant_gate as G
    assert G.mirror_text("JOLTEON-REV.FOIL TAG TEAM GX ALL STARS") == "REVERSE HOLO"
    assert G.mirror_text("HO-OH-REV. FOIL 25TH ANNIVERSARY COLL.") == "REVERSE HOLO"
    assert G.mirror_text("PIKACHU MASTER BALL REVERSE HOLO") == "MASTER BALL REVERSE HOLO"
    assert G.mirror_text("PIKACHU") == ""


def test_one_place_owns_the_pattern():
    """正規表現を2か所に書かない: gate は psa_label_finish を呼ぶだけ"""
    import psa_label_finish as F
    import psa_variant_gate as G
    assert "FOIL" not in "".join(l for l in inspect.getsource(G).splitlines() if "re.compile" in l or "re.sub" in l)
    assert "normalize_reverse_holo" in inspect.getsource(G._normalize_rh)
    assert F.finish_from_psa_label("HO-OH-REV.FOIL 25TH") == F.REVERSE_HOLO


def test_build_fail_watch_counts_revfoil_line(tmp_path):
    import build_fail_watch as B
    out = []
    log = ("    🪞 REV.FOIL をミラー (REVERSE HOLO) と読んだ: JOLTEON-REV.FOIL TAG TEAM GX\n"
           "    🪞 REV.FOIL をミラー (REVERSE HOLO) と読んだ: JOLTEON-REV.FOIL TAG TEAM GX\n")
    B.run(log, out.append, ledger_path=str(tmp_path / "l.json"), verified_path=str(tmp_path / "v.json"),
          add_backlog=lambda c, r: "x", mirror_path=str(tmp_path / "m.json"))
    assert any("REV.FOIL をミラーとして読んだラベル: 1種" in x for x in out)
