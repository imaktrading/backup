"""tcg_catalog_audit — 出品CSVの主要フィールドを catalog(SSOT)と突き合わせて正誤判定する独立監査。

設計意図 (2026-06-13 新設・並行ビルドの第一歩):
  既存チェック(csv_auditor/check_csv)は「生成物どうしの内部整合」+「英語名ヒューリスティック」
  しか見ず、catalog 照合をしないため #4 'Brilliant Stars' 等の誤りを構造的に素通りさせた。
  本ツールは **生成された Item Specifics が catalog 公式値と一致するか** を cert→card_id 解決して
  決定論で判定する。= 「唯一効く正誤チェック」。read-only (CSV を書き換えない)。

  旧パイプラインは一切触らない。新パイプラインの正誤チェック本体 兼 旧の検証ハーネスとして使う。

照合対象 (catalog から決定論で取れるもの):
  - C:Card Name   vs catalog.name_en            (完全一致)
  - C:Character   の汚染検出 (name_en に無い token 混入 = set名等の混入)
  - C:Rarity      vs RARITY_MAP[catalog rarity] (catalog に rarity 無なら「推測(空欄にすべき)」)
  - C:Set         catalog.set_name_official(JP) と並記レポート。英語正規名の機械照合は
                  catalog.set_name_ebay 導入後に有効化 (現状は参考表示 = 過剰主張しない)

使い方:
  python tcg_catalog_audit.py [csv_path]   # 省略時は csv_output 最新の tcg_upload_*.csv
"""
from __future__ import annotations
import csv
import glob
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CSV_DIR = r"C:/dev/iMak/iMakHQ/csv_output"
PSA_CACHE_DIR = r"C:/dev/iMak/iMakeBayAPI/cache/psa_certs"
CATALOG_DB = r"C:/dev/iMak_data/catalog/products.sqlite"
_CATALOG_INTEG = r"C:/dev/iMak_catalog/iMakCatalog"

CERT_COL = "CDA:Certification Number - (ID: 27503)"

# catalog JP rarity code → 生成が使う eBay 英語 rarity 名
RARITY_MAP = {
    "C": "Common", "U": "Uncommon", "R": "Rare",
    "RR": "Double Rare", "RRR": "Triple Rare",
    "AR": "Art Rare", "SAR": "Special Art Rare",
    "SR": "Super Rare", "HR": "Hyper Rare", "UR": "Ultra Rare",
    "CHR": "Character Rare", "CSR": "Character Super Rare",
    "K": "Crown Rare", "ACE": "ACE SPEC Rare", "AR_C": "Art Rare",
}

_FRANCHISE_BY_GAME = {
    "pokemon": "pokemon_tcg", "one piece": "one_piece_tcg",
    "yu-gi-oh": "yugioh_tcg", "yugioh": "yugioh_tcg",
    "dragon ball": "dragonball_scg", "gundam": "gundam_tcg",
}

_lookup_cache = {}


def _load_resolver():
    """出品と同一 resolver (catalog_psa.lookup_*) を遅延 load."""
    if _lookup_cache:
        return _lookup_cache
    if _CATALOG_INTEG not in sys.path:
        sys.path.insert(0, _CATALOG_INTEG)
    from integrations import psa_to_csv as cp
    _lookup_cache.update({
        "pokemon_tcg": cp.lookup_pokemon,
        "one_piece_tcg": cp.lookup_one_piece,
        "dragonball_scg": cp.lookup_dragonball,
        "gundam_tcg": cp.lookup_gundam,
        "yugioh_tcg": getattr(cp, "lookup_yugioh", None),
    })
    return _lookup_cache


def _detect_franchise(game: str, brand: str):
    g = (game or "").lower().replace("é", "e")   # Pokémon → pokemon
    b = (brand or "").lower().replace("é", "e")
    for key, frid in _FRANCHISE_BY_GAME.items():
        if key in g or key in b:
            return frid
    return None


def _norm_tokens(s: str):
    """比較用に正規化: 小文字・所有格's除去・記号で分割した token 集合。"""
    s = (s or "").lower().replace("’", "'")
    s = re.sub(r"'s\b", "", s)          # Marnie's → Marnie
    return [t for t in re.split(r"[^a-z0-9]+", s) if t]


def _resolve_card_id(cert: str, franchise: str):
    """cert → catalog card_id (出品と同一 resolver)。"""
    p = os.path.join(PSA_CACHE_DIR, f"{cert}.json")
    if not os.path.exists(p):
        return None, "no_psa_cache"
    meta = json.load(open(p, encoding="utf-8"))
    brand = meta.get("Brand") or ""
    num = meta.get("CardNumber") or ""
    subj = meta.get("Subject") or ""
    fn = _load_resolver().get(franchise)
    if fn is None:
        return None, f"no_resolver:{franchise}"
    try:
        rec = fn(brand, num, subj, verbose=False)
    except TypeError:
        rec = fn(brand, num, subj)
    except Exception as e:
        return None, f"resolver_error:{type(e).__name__}"
    if not rec:
        return None, "unresolved"
    return (rec.get("card_id") or rec.get("id")), None


def _catalog_record(card_id: str):
    con = sqlite3.connect(CATALOG_DB)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT product_id,name_en,name,set_name_official,specs,language "
        "FROM products WHERE product_id=?", (card_id,)).fetchone()
    con.close()
    if not row:
        return None
    specs = {}
    try:
        specs = json.loads(row["specs"] or "{}")
    except Exception:
        pass
    return {
        "card_id": row["product_id"],
        "name_en": row["name_en"] or "",
        "set_official": row["set_name_official"] or "",
        "rarity_code": specs.get("rarity") or "",
        "language": row["language"] or "",
    }


def _get(row, headers, col):
    i = headers.get(col)
    return (str(row[i]).strip() if i is not None and i < len(row) else "")


def compare_to_catalog(csv_name, csv_char, csv_rarity, rec):
    """生成フィールド vs catalog record を決定論で照合 (純関数=DB/網羅不要でテスト可能)。

    rec = {"name_en": str, "rarity_code": str}。findings list を返す ([] = 正)。
    """
    findings = []

    # 1) Card Name == catalog.name_en
    if rec.get("name_en"):
        if _norm_tokens(csv_name) != _norm_tokens(rec["name_en"]):
            findings.append(("MISMATCH",
                f"C:Card Name='{csv_name}' ≠ catalog name_en='{rec['name_en']}'"))

    # 2) Character 汚染 (name_en に無い token 混入 = set名等)
    if rec.get("name_en") and csv_char:
        name_toks = set(_norm_tokens(rec["name_en"]))
        extra = [t for t in _norm_tokens(csv_char) if t not in name_toks]
        if extra:
            findings.append(("POLLUTION",
                f"C:Character='{csv_char}' に catalog name_en 外の token {extra} 混入 (set名混入疑い)"))

    # 3) Rarity == map(catalog rarity)
    code = rec.get("rarity_code") or ""
    if code:
        expected = RARITY_MAP.get(code)
        if expected is None:
            findings.append(("RARITY_UNDEF",
                f"catalog rarity '{code}' の英語名が RARITY_MAP 未定義 (要追加)"))
        elif csv_rarity and csv_rarity.lower() != expected.lower():
            findings.append(("MISMATCH",
                f"C:Rarity='{csv_rarity}' ≠ catalog '{code}'→'{expected}'"))
    elif csv_rarity:
        findings.append(("GUESSED",
            f"C:Rarity='{csv_rarity}' だが catalog に rarity 無 = 推測 (Precision方針では空欄にすべき)"))

    return findings


def audit_row(row, headers):
    """1 行を catalog 照合。findings list を返す ([] = 正)。"""
    findings = []
    cert = _get(row, headers, CERT_COL)
    title = _get(row, headers, "*Title")
    game = _get(row, headers, "C:Game")
    if not cert:
        return [("SKIP", "cert 番号列が空 (PSA行でない可能性)")], None
    franchise = _detect_franchise(game, "")
    if not franchise:
        return [("SKIP", f"franchise 判定不能 (C:Game={game!r})")], None

    card_id, err = _resolve_card_id(cert, franchise)
    if err:
        return [("UNRESOLVED", f"cert {cert} → catalog 解決不能 ({err})")], None
    rec = _catalog_record(card_id)
    if not rec:
        return [("UNRESOLVED", f"card_id {card_id} が catalog に無い")], None

    csv_name = _get(row, headers, "C:Card Name")
    csv_char = _get(row, headers, "C:Character")
    csv_rarity = _get(row, headers, "C:Rarity")
    csv_set = _get(row, headers, "C:Set")

    findings.extend(compare_to_catalog(csv_name, csv_char, csv_rarity, rec))

    # Set: 英語正規名照合は catalog.set_name_ebay 導入後。今は参考表示のみ。
    info = {"cert": cert, "card_id": card_id, "csv_set": csv_set,
            "catalog_set_jp": rec["set_official"], "title": title,
            "language": rec["language"]}
    return findings, info


def audit_csv(csv_path):
    rows = list(csv.reader(open(csv_path, encoding="utf-8", newline="")))
    if not rows:
        print("空 CSV"); return 0
    headers = {h: i for i, h in enumerate(rows[0])}
    print("=" * 64)
    print(f"tcg_catalog_audit (catalog照合・read-only)\n対象: {os.path.basename(csv_path)}")
    print("=" * 64)
    bad = 0
    for n, row in enumerate(rows[1:], 1):
        findings, info = audit_row(row, headers)
        title = _get(row, headers, "*Title")
        hard = [f for f in findings if f[0] in ("MISMATCH", "POLLUTION", "GUESSED")]
        mark = "❌" if hard else ("⚠️" if findings else "✅")
        print(f"\n[{n}] {mark} {title}")
        if info:
            lang = " (JP)" if info["language"] == "ja" else ""
            print(f"     cert {info['cert']} → {info['card_id']}{lang}")
            print(f"     C:Set='{info['csv_set']}'  | catalog set(JP)='{info['catalog_set_jp']}'")
        for tag, msg in findings:
            print(f"     [{tag}] {msg}")
        if hard:
            bad += 1
    print("\n" + "=" * 64)
    print(f"結果: {len(rows)-1} 行中 catalog不一致(要修正) {bad} 行")
    print("※ Set英語名の機械照合は catalog.set_name_ebay 導入後に有効化 (現状は参考表示)")
    print("=" * 64)
    return bad


def find_latest_csv():
    cands = glob.glob(os.path.join(CSV_DIR, "tcg_upload_*.csv"))
    cands = [c for c in cands if not c.endswith(".bak") and ".bak" not in os.path.basename(c)]
    return max(cands, key=os.path.getmtime) if cands else None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else find_latest_csv()
    if not path or not os.path.exists(path):
        print(f"CSV が見つかりません: {path}"); sys.exit(1)
    bad = audit_csv(path)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
