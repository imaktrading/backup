"""G-shock bare↔suffix 同実物 dedupe (canonical=suffix込み完全形)。

依頼: requests/2026-06-11_gshock_bare_dedupe_BUILD.md (HQ→Catalog, ユーザー方針決定済)
方針: 1物理商品=1 canonical KEY。bare行を suffix行へ best-union マージしてから削除。

★landmine: 140件中117件は bare の specs がリッチ(ShockBase詳細)。blind DELETE 禁止。
手順: bare の specs/images/name_jp/name_en/variants のうち suffix が欠く/貧弱な分を
suffix へマージ → しかる後 bare を DELETE。

可逆: 実行前に DB を .bak コピー + 削除した bare 全行 & マージ前 suffix 行を
rollback JSON に dump。

manual_review 1件 (GW-9400J-1B): JF/JR 両候補とも canonical 存在 + bare に固有データ
無し(specs同質) → 推測せず bare を単純削除(両 suffix 残す, fail-closed)。
"""
import sqlite3, json, shutil, sys
from datetime import datetime, timezone

DB = 'C:/dev/iMak_data/catalog/products.sqlite'
LIST = 'C:/dev/iMak_data/catalog/requests/2026-06-11_gshock_bare_dedupe_list.json'
STAMP = '20260611'
BAK = f'{DB}.bak_{STAMP}_baredupe'
ROLLBACK = f'C:/dev/iMak_data/catalog/migrations/gshock_bare_dedupe_{STAMP}.json'

FILL_IF_EMPTY = ('name_jp', 'name_en', 'name_en_source', 'variants')


def _row(cur, pid):
    cur.execute(
        "SELECT id,product_id,name,name_jp,name_en,name_en_source,set_name,"
        "set_name_official,specs,images,source,variants,updated_at "
        "FROM products WHERE category='gshock' AND product_id=?", (pid,))
    r = cur.fetchone()
    if not r:
        return None
    cols = ['id','product_id','name','name_jp','name_en','name_en_source','set_name',
            'set_name_official','specs','images','source','variants','updated_at']
    return dict(zip(cols, r))


def _merge_specs(bare, suffix):
    """suffix を canonical とし、bare の欠落 key で補完 (suffix 値優先)。"""
    b = json.loads(bare or '{}'); s = json.loads(suffix or '{}')
    merged = {**b, **s}  # suffix が衝突 key を勝つ、bare が欠落 key を埋める
    return merged, (merged != s)


def _merge_images(bare, suffix):
    """URL union (suffix 先, bare の追加分を末尾)。"""
    b = json.loads(bare or '[]'); s = json.loads(suffix or '[]')
    seen = set(); out = []
    for u in list(s) + list(b):
        k = u if isinstance(u, str) else json.dumps(u, sort_keys=True)
        if k not in seen:
            seen.add(k); out.append(u)
    return out, (out != s)


def run(apply=False):
    data = json.load(open(LIST, encoding='utf-8'))
    auto = data['auto_delete']; manual = data['manual_review']
    if apply:
        shutil.copy2(DB, BAK)
        print(f'[backup] {BAK}')
    c = sqlite3.connect(DB); cur = c.cursor()
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    rollback = {'date': now, 'deleted_bare_rows': [], 'pre_merge_suffix_rows': [],
                'merges_applied': [], 'manual_deleted': []}
    n_merge_specs = n_merge_img = n_fill = 0

    # --- 140 auto: merge then delete ---
    for p in auto:
        bare = _row(cur, p['delete_bare']); suf = _row(cur, p['keep_suffix'])
        if not bare or not suf:
            print(f"  SKIP (missing) {p['delete_bare']} / {p['keep_suffix']}")
            continue
        rollback['deleted_bare_rows'].append(bare)
        rollback['pre_merge_suffix_rows'].append({k: suf[k] for k in
            ('product_id','specs','images','name_jp','name_en','name_en_source','variants')})
        sets = {}; applied = {'suffix': suf['product_id'], 'from_bare': bare['product_id']}
        mspecs, ch1 = _merge_specs(bare['specs'], suf['specs'])
        if ch1:
            sets['specs'] = json.dumps(mspecs, ensure_ascii=False); n_merge_specs += 1
            applied['specs_keys_added'] = sorted(set(mspecs) - set(json.loads(suf['specs'] or '{}')))
        mimg, ch2 = _merge_images(bare['images'], suf['images'])
        if ch2:
            sets['images'] = json.dumps(mimg, ensure_ascii=False); n_merge_img += 1
        for f in FILL_IF_EMPTY:
            if not suf.get(f) and bare.get(f):
                sets[f] = bare[f]; n_fill += 1; applied.setdefault('filled', []).append(f)
        if sets:
            sets['updated_at'] = now
            cols = ', '.join(f'{k}=?' for k in sets)
            if apply:
                cur.execute(f"UPDATE products SET {cols} WHERE category='gshock' AND product_id=?",
                            list(sets.values()) + [suf['product_id']])
            rollback['merges_applied'].append(applied)
        if apply:
            cur.execute("DELETE FROM products WHERE category='gshock' AND product_id=?",
                        (bare['product_id'],))

    # --- manual: bare に固有データ無し → 単純削除 ---
    m = manual[0]
    mb = _row(cur, m['bare'])
    if mb:
        rollback['manual_deleted'].append(mb)
        if apply:
            cur.execute("DELETE FROM products WHERE category='gshock' AND product_id=?", (m['bare'],))

    if apply:
        c.commit()
        json.dump(rollback, open(ROLLBACK, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'[rollback] {ROLLBACK}')
    print(f"{'APPLIED' if apply else 'DRYRUN'}: auto={len(auto)} "
          f"specs_merged={n_merge_specs} images_merged={n_merge_img} fields_filled={n_fill} "
          f"manual_deleted={1 if mb else 0}")


if __name__ == '__main__':
    run(apply='--apply' in sys.argv)
