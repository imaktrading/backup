"""G-shock dedupe 方針変更: 削除 → 別名紐づけ(B案)。

依頼: requests/2026-06-11_gshock_dedupe_switch_to_alias_link_B.md (HQ+ユーザー決定)
supersede: bare_dedupe_BUILD / round2_HQ_verdict の「削除」部分を撤回。
  best-union merge と canonical=suffix形 は維持、**bare 行を物理削除せず別名として復活**。

実体: 既に削除した 243 bare 行を .bak から復元 → canonical を指す alias_of 列を付与。
  「公式フル形(suffix)=正、非公式短縮形(bare)=その別名」。非破壊・取りこぼしゼロ・recall 維持。

手順:
  1. DB backup
  2. ALTER TABLE products ADD COLUMN alias_of TEXT (+ index)
  3. 243 bare を .bak_20260611_baredupe から復元 + alias_of=canonical
     (round-1 139件[GBX-100-2 除く] + round-2 104件[GBX-100-2A 含む])
  4. GW-9400J-1B (真の 1:N) を復元 + alias_of=NULL (曖昧、resolver が "" 返す)
  5. GBX-100-2 (色2, 独立 canonical) はそのまま放置 (alias にしない)
  6. canonical(suffix行) の best-union merge 済 specs はそのまま維持
  7. rollback JSON
"""
import sqlite3, json, shutil, sys
from datetime import datetime, timezone

DB = 'C:/dev/iMak_data/catalog/products.sqlite'
BAK_SRC = f'{DB}.bak_20260611_baredupe'   # round-1 前 = 全 bare 行が在る復元 source
R1_LIST = 'C:/dev/iMak_data/catalog/requests/2026-06-11_gshock_bare_dedupe_list.json'
R2_LIST = 'C:/dev/iMak_data/catalog/requests/2026-06-11_gshock_bare_dedupe_round2_corrected_list.json'
STAMP = '20260611'
BAK = f'{DB}.bak_{STAMP}_aliasB'
ROLLBACK = f'C:/dev/iMak_data/catalog/migrations/gshock_dedupe_aliasB_{STAMP}.json'

# .bak から復元する列 (id/alias_of を除く)
COLS = ['category','product_id','name','name_jp','set_name','set_name_official','specs',
        'images','source','source_url','created_at','updated_at','card_set_id','language',
        'name_en','name_en_source','variants']


def _has_col(cur, table, col):
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())


def _bak_row(bcur, pid):
    bcur.execute(f"SELECT {','.join(COLS)} FROM products WHERE category='gshock' AND product_id=?", (pid,))
    r = bcur.fetchone()
    return dict(zip(COLS, r)) if r else None


def _live_exists(cur, pid):
    cur.execute("SELECT 1 FROM products WHERE category='gshock' AND product_id=?", (pid,))
    return cur.fetchone() is not None


def _build_alias_pairs():
    """(bare, canonical) の 243 ペア = round-1 139(GBX-100-2 除外) + round-2 104。"""
    r1 = json.load(open(R1_LIST, encoding='utf-8'))['auto_delete']
    r2 = json.load(open(R2_LIST, encoding='utf-8'))['round2_auto_1to1']
    pairs = [(p['delete_bare'], p['keep_suffix']) for p in r1 if p['delete_bare'] != 'GBX-100-2']
    pairs += [(p['delete_bare'], p['keep_suffix']) for p in r2]
    return pairs


def run(apply=False):
    pairs = _build_alias_pairs()
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    if apply:
        shutil.copy2(DB, BAK); print(f'[backup] {BAK}')
    c = sqlite3.connect(DB); cur = c.cursor()
    bak = sqlite3.connect(BAK_SRC); bcur = bak.cursor()

    # --- 2. schema: alias_of 列 ---
    if not _has_col(cur, 'products', 'alias_of'):
        if apply:
            cur.execute("ALTER TABLE products ADD COLUMN alias_of TEXT")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_products_alias_of ON products(alias_of)")
        print('  ADD COLUMN alias_of (+ index)')
    else:
        print('  alias_of already exists')

    rb = {'date': now, 'restored_alias': [], 'restored_ambiguous': [], 'canonical_missing': []}
    n_restore = n_link_only = 0

    def _restore_and_link(bare, canonical):
        nonlocal n_restore, n_link_only
        if not _live_exists(cur, bare):
            src = _bak_row(bcur, bare)
            if not src:
                print(f'  WARN bare not in .bak: {bare}'); return
            vals = [src[col] for col in COLS]
            if apply:
                cur.execute(f"INSERT INTO products ({','.join(COLS)}) VALUES ({','.join('?'*len(COLS))})", vals)
            n_restore += 1
        else:
            n_link_only += 1
        if apply:
            cur.execute("UPDATE products SET alias_of=? WHERE category='gshock' AND product_id=?",
                        (canonical, bare))

    # --- 3. 243 alias ---
    for bare, canonical in pairs:
        if canonical and not _live_exists(cur, canonical):
            rb['canonical_missing'].append({'bare': bare, 'canonical': canonical})
        _restore_and_link(bare, canonical)
        rb['restored_alias'].append({'bare': bare, 'alias_of': canonical})

    # --- 4. GW-9400J-1B (1:N) 復元 + alias_of=NULL ---
    amb = 'GW-9400J-1B'
    if not _live_exists(cur, amb):
        src = _bak_row(bcur, amb)
        if src:
            vals = [src[col] for col in COLS]
            if apply:
                cur.execute(f"INSERT INTO products ({','.join(COLS)}) VALUES ({','.join('?'*len(COLS))})", vals)
            rb['restored_ambiguous'].append(amb)

    if apply:
        c.commit()
        json.dump(rb, open(ROLLBACK, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'[rollback] {ROLLBACK}')
    print(f"{'APPLIED' if apply else 'DRYRUN'}: alias_pairs={len(pairs)} "
          f"restored={n_restore} link_only={n_link_only} "
          f"ambiguous_restored={len(rb['restored_ambiguous'])} "
          f"canonical_missing={len(rb['canonical_missing'])}")


if __name__ == '__main__':
    run(apply='--apply' in sys.argv)
