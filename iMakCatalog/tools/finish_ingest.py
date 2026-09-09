"""取り込んだ行に「出品に出る値」を付ける — 取り込みの最後の1手 (2026-09-03 新設).

## なぜ要るか

scraper が入れるのは **公式の生値だけ**。出品くんが読む `*_ebay` は付かない。
そのまま置くと「カタログには在るのに出せない」状態になり、テストも落ちる。
2026-09-02 (OP-17 178行) と 2026-09-03 (FB11 125行) で**2回続けて同じことをやった**ので、
カテゴリ非依存の1コマンドにする。

    python tools/finish_ingest.py --cat dragonball_scg          # 何が付くか見る
    python tools/finish_ingest.py --cat dragonball_scg --commit

## 付ける値 (すべて既存の決まりから導出。推測しない)

    game_ebay / manufacturer_ebay      api.derive_game_ebay / derive_manufacturer (category 定数)
    card_size_ebay / language / country_of_origin_ebay   定数
    rarity_ebay                        api.derive_rarity_ebay (変換表)
    card_type_ebay                     既存行が使っている対応をそのまま (新語彙は作らない)
    set_name_ebay                      api.derive_set_name_ebay (変換表)
    name_en (pokemon のみ)             PokeAPI 辞書 → 無ければ カード API 辞書
    hp/stage/color/attack 系           生値 → eBay 語彙 (tcg_ebay_normalized_fields の PLAN)

★変換表に無いものは **空欄のまま** (fail-closed)。何が引けなかったかは最後に一覧で出す。
  そこが「変換表に1行足す」作業の入口になる。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))
sys.path.insert(0, str(ROOT / "tools"))
import api  # noqa: E402
import tcg_ebay_normalized_fields_20260615 as N  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ★生値 → eBay 語彙 (2026-09-06 追加)。
#   これを **取り込みの一部**にしていなかったので、9/04〜9/05 に入れた行に
#   `hp_ebay` / `stage_ebay` / `color_ebay` が付かず、Item Specifics が3つ空で出た
#   (CSV監査くん 依頼 `2026-09-06_ebay_aspect_fields_missing_on_new_ingests.md`)。
#   規則は既存の `tools/tcg_ebay_normalized_fields_20260615.py` の PLAN をそのまま使う。
#   ★ポケモンの `type_en` → `color_ebay` だけ 8/23 の migration にしか無かったので、ここに足す。
#     eBay の Attribute の値表に在るものだけ通す (無ければ空欄 = fail-closed)。
_ATTR_MASTER = Path("C:/dev/iMak_data/catalog/_input/ebay_aspects_183454_latest.json")


def _attr_values() -> set:
    try:
        d = json.loads(_ATTR_MASTER.read_text(encoding="utf-8"))
        a = d.get("aspects", d).get("Attribute/MTG:Color") or {}
        return set(a.get("all") or [])
    except Exception:
        return set()


_ATTR_OK = _attr_values()


def _pokemon_type_to_color(raw):
    v = str(raw or "").strip()
    return v if v in _ATTR_OK else ""


PLAN = {k: list(v) for k, v in N.PLAN.items()}
PLAN["pokemon_tcg"].append(("color_ebay", "type_en", _pokemon_type_to_color))


NOW = datetime.now().isoformat(timespec="seconds")
CONSTANTS = {"card_size_ebay": "Standard", "language": "Japanese",
             "country_of_origin_ebay": "Japan"}


def _card_type_map(db, cat: str) -> dict:
    """そのカテゴリの既存行が使っている card_type → card_type_ebay の対応."""
    m: dict[str, Counter] = {}
    for (specs,) in db.execute(
            "SELECT specs FROM products WHERE category=? "
            "AND IFNULL(json_extract(specs,'$.card_type_ebay'),'')<>''", (cat,)):
        s = json.loads(specs or "{}")
        raw = str(s.get("card_type") or s.get("Card Type") or "").strip()
        val = str(s.get("card_type_ebay") or "").strip()
        if raw and val:
            m.setdefault(raw, Counter())[val] += 1
    return {k: v.most_common(1)[0][0] for k, v in m.items()}


def run(cat: str, commit: bool) -> int:
    # ★変換表は **書き込みを始める前に**まとめて読む (2026-09-04)。
    #   書き込みトランザクション中に api.derive_* が別コネクションで読みに行くと
    #   `database is locked` で落ちる (実際に落ちた)。
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    ctmap = _card_type_map(db, cat)
    setmap = {r[0]: r[1] for r in db.execute(
        "SELECT source_value, ebay_value FROM ebay_filter_map "
        "WHERE category=? AND field='set'", (cat,))}
    codemap = {r[0]: r[1] for r in db.execute(
        "SELECT source_value, ebay_value FROM ebay_filter_map "
        "WHERE category=? AND field='set_code'", (cat,))}
    rarmap = {r[0]: r[1] for r in db.execute(
        "SELECT source_value, ebay_value FROM ebay_filter_map "
        "WHERE category=? AND field='rarity'", (cat,))}

    def _set_of(official, pid):
        if official and official in setmap:
            return setmap[official]
        m = re.search(r"[\[【]([A-Za-z0-9\-]+)[\]】]", official or "")
        if m and m.group(1) in codemap:
            return codemap[m.group(1)]
        head = (pid or "").split("_")[0].rsplit("-", 1)[0]
        return codemap.get(head) or setmap.get(head)
    # ★英語名の辞書も **書き込み前に**読む (pokemon のみ)。
    #   scraper は日本語名しか入れないので、ここで付けないと 出品くんが英語名を出せない
    #   (実測 2026-09-05: 新しく入れた 95行が name_en 空のまま = 出せない行になっていた)。
    en1 = en2 = None
    own_en: dict[str, str] = {}
    own_cn: dict[str, str] = {}
    if cat == "pokemon_tcg":
        import pokemon_name_translation as T  # noqa

        en1, en2 = T.load_pokeapi_dict(), T.load_api_dict()
        # ★catalog が **既に使っている英語名**を最優先にする (2026-09-05)。
        #   辞書は直訳を返すことがある: `ポケモンごっこ` → 'Imitation Pokémon'。
        #   正しくは 'Poké Kid' で、PSA 実物で確かめて 7行に入れてある
        #   (`psa_slab_confirmed_20260823`)。辞書を先に見ると **決着済みの名前を壊す**。
        #   同じ日本語名に英語名が2つ在る行は使わない (どちらが正か決められない)。
        _e: dict[str, set] = {}
        _c: dict[str, set] = {}
        for jp, en, cn in db.execute(
                "SELECT name, name_en, json_extract(specs,'$.character_name') FROM products "
                "WHERE category=? AND IFNULL(name,'')<>'' AND IFNULL(name_en,'')<>''", (cat,)):
            _e.setdefault(jp, set()).add(en)
            if cn:
                _c.setdefault(jp, set()).add(cn)
        own_en = {k: next(iter(v)) for k, v in _e.items() if len(v) == 1}
        own_cn = {k: next(iter(v)) for k, v in _c.items() if len(v) == 1}

        def _en(jp: str) -> tuple[str, str]:
            if jp in own_en:
                return own_en[jp], "catalog_same_name"
            g = T.resolve_name_en(jp, en1, en2)
            got = g[0] if isinstance(g, tuple) else g
            if got:
                return got, "pokeapi_finish_ingest"
            v = en2.get(jp)          # トレーナーズ等 (既存 rule_trainer_dict と同じ出所)
            return (v, "api_dict_finish_ingest") if v else ("", "")

    # ★カテゴリの全行を見る (2026-09-06)。条件で絞ると、条件に入れ忘れた項目が
    #   永久に埋まらない (実際 hp/stage/color がそれで 1,500行ずつ空のままだった)。
    #   specs が変わった行だけ書くので、余分な更新は起きない。
    rows = db.execute(
        "SELECT id, product_id, set_name_official, name_jp, name, name_en, specs FROM products "
        "WHERE category=?", (cat,)).fetchall()
    print(f"=== 仕上げ {cat} ({'APPLY' if commit else 'DRY-RUN'}) — 対象 {len(rows)}行 ===")
    game, maker = api.derive_game_ebay(cat), api.derive_manufacturer(cat)
    filled, unmapped, done = Counter(), Counter(), 0
    for r in rows:
        s = json.loads(r["specs"] or "{}")
        before = json.dumps(s, sort_keys=True)
        if game and not s.get("game_ebay"):
            s["game_ebay"] = game
            filled["game_ebay"] += 1
        if maker and not s.get("manufacturer_ebay"):
            s["manufacturer_ebay"] = maker
            filled["manufacturer_ebay"] += 1
        for k, v in CONSTANTS.items():
            if not s.get(k):
                s[k] = v
                filled[k] += 1
        for dst, src_key, fn in PLAN.get(cat, []):
            if str(s.get(dst) or "").strip():
                continue
            raw = s.get(src_key)
            if raw is None or not str(raw).strip():
                continue
            v = fn(raw)
            if v:
                s[dst] = v
                filled[dst] += 1
            else:
                unmapped[f"{src_key}={str(raw)[:20]!r}"] += 1
        raw_ct = str(s.get("card_type") or s.get("Card Type") or "").strip()
        if raw_ct and not s.get("card_type_ebay"):
            if raw_ct in ctmap:
                s["card_type_ebay"] = ctmap[raw_ct]
                filled["card_type_ebay"] += 1
            else:
                unmapped[f"card_type={raw_ct!r}"] += 1
        raw_r = str(s.get("rarity") or s.get("Rarity") or "").strip()
        if raw_r and not s.get("rarity_ebay"):
            v = rarmap.get(raw_r)
            if v:
                s["rarity_ebay"] = v
                filled["rarity_ebay"] += 1
            else:
                unmapped[f"rarity={raw_r!r}"] += 1
        if not s.get("set_name_ebay"):
            v = _set_of(r["set_name_official"], r["product_id"])
            if v:
                s["set_name_ebay"] = v
                s["set_name_ebay_source"] = f"finish_ingest_{NOW[:10].replace('-', '')}"
                filled["set_name_ebay"] += 1
            else:
                unmapped[f"set={r['set_name_official']!r}"] += 1
        new_en = new_en_src = ""
        if en1 is not None and not (r["name_en"] or "").strip():
            new_en, new_en_src = _en((r["name_jp"] or r["name"] or "").strip())
            if new_en:
                filled["name_en"] += 1
                jp0 = (r["name_jp"] or r["name"] or "").strip()
                if jp0 in own_cn and not s.get("character_name"):
                    s["character_name"] = own_cn[jp0]
                    filled["character_name"] += 1
            else:
                unmapped[f"name_en={(r['name_jp'] or r['name'])!r}"] += 1
        if commit and (json.dumps(s, sort_keys=True) != before or new_en):
            if new_en:
                db.execute("UPDATE products SET name_en=?, name_en_source=? WHERE id=?",
                           (new_en, new_en_src, r["id"]))
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), NOW, r["id"]))
            done += 1
            if done % 500 == 0:            # ★途中保存: 落ちても ここまでは残る
                db.commit()
                print(f"    ... {done}行 保存")
    if commit:
        db.commit()
    db.close()

    for k, v in filled.most_common():
        print(f"  + {k:24s} {v}行")
    if unmapped:
        print(f"  ★変換表に無い (空欄のまま。ここに1行足す):")
        for k, v in unmapped.most_common(10):
            print(f"      {v:5d}行  {k}")
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'}")
    return len(unmapped)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", required=True)
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    sys.exit(0 if run(a.cat, a.commit) == 0 else 1)


if __name__ == "__main__":
    main()
