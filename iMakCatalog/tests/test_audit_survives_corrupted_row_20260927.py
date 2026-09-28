# -*- coding: utf-8 -*-
"""壊れた行があっても毎日の監査が止まらない (2026-09-27).

PC のブルースクリーンでビット化けした行に当たると `Could not decode to UTF-8` で
**監査が丸ごと死ぬ**作りだった。実害: 2026-09-25 / 09-26 / 09-27 の3日連続で日次監査が
1行も出さずに終わっていた (ログの COMPLETE が無いことで初めて気づいた)。
読めない行は飛ばして続ける。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import set_name_integrity_audit as A  # noqa: E402


def _make_db(path: Path) -> None:
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE products (category TEXT, product_id TEXT, name_en TEXT, "
              "name_jp TEXT, set_name_official TEXT, specs TEXT)")
    c.execute("INSERT INTO products VALUES ('pokemon_tcg','A-001','Pikachu','ピカチュウ',"
              "'拡張パック','{\"rarity\": \"C\"}')")
    c.execute("INSERT INTO products VALUES ('pokemon_tcg','B-002','Eevee','イーブイ',"
              "'拡張パック',?)", (sqlite3.Binary(b'{"rarity": "\xff\xfeC"}'),))
    c.execute("CREATE TABLE ebay_filter_map (category TEXT, field TEXT, "
              "source_value TEXT, ebay_value TEXT)")
    c.execute("INSERT INTO ebay_filter_map VALUES ('pokemon_tcg','set','拡張パック','Expansion')")
    c.commit()
    c.close()


def test_audit_skips_unreadable_rows(tmp_path, monkeypatch, capsys):
    db = tmp_path / "t.sqlite"
    _make_db(db)
    monkeypatch.setattr(A, "DB_PATH", str(db))
    A.audit(["pokemon_tcg"])            # 落ちないこと
    out = capsys.readouterr().out
    assert "読めない行を飛ばした" in out, out[-300:]
