"""G-shock bare↔suffix dedupe ROUND-2 + round-1 誤削除の復元。

依頼: requests/2026-06-11_gshock_bare_dedupe_round2_HQ_verdict.md (HQ GO)
原因: round-1 の HQ元リストが REGION regex バグ(AJF/AJR を地域コード誤認、実際は色A+JF)で
  (a) 104件取りこぼし (b) GBX-100-2(色2) を GBX-100-2AJF(色2A) に誤マージ削除。

手順 (順序重要):
  1. DB backup
  2. 復元: .bak から GBX-100-2 を再INSERT + GBX-100-2AJF を .bak 状態(汚染前specs)へ戻す
  3. round-2: corrected_list の 104件を best-union merge→削除 (round-1 と同ロジック)
  4. rollback JSON

正しい地域 suffix whitelist = JF/JR/JFS/JRS/SPCBOX/PFCT/JTC (J始まりのみ)。末尾Aは色。
"""
import sqlite3, json, shutil, sys
from datetime import datetime, timezone

DB = 'C:/dev/iMak_data/catalog/products.sqlite'
BAK_R1 = f'{DB}.bak_20260611_baredupe'   # round-1 前の状態 (復元 source)
LIST = 'C:/dev/iMak_data/catalog/requests/2026-06-11_gshock_bare_dedupe_round2_corrected_list.json'
STAMP = '20260611'
BAK_R2 = f'{DB}.bak_{STAMP}_round2'
ROLLBACK = f'C:/dev/iMak_data/catalog/migrations/gshock_bare_dedupe_round2_{STAMP}.json'

COLS = ['category','product_id','name','name_jp','set_name','set_name_official','specs',
        'images','source','source_url','created_at','updated_at','card_set_id','language',
        'name_en','name_en_source','variants']
MERGE_COLS = ('specs','images','name_jp','name_en','name_en_source','variants',
              'set_name','set_name_official','source_url')
FILL_IF_EMPTY = ('name_jp','name_en','name_en_source','variants')
RESTORE_SUFFIX_COLS = ('specs','images','name_jp','name_en','name_en_source','variants',
                       'set_name','set_name_official','source','source_url','updated_at')


def _row(cur, pid, cols='*'):
    cur.execute(f"SELECT {','.join(COLS)} FROM products WHERE category='gshock' AND product_id=?", (pid,))
    r = cur.fetchone()
    return dict(zip(COLS, r)) if r else None


def _merge_specs(bare, suffix):
    b = json.loads(bare or '{}'); s = json.loads(suffix or '{}')
    merged = {**b, **s}
    return json.dumps(merged, ensure_ascii=False), (merged != s)


def _merge_images(bare, suffix):
    b = json.loads(bare or '[]'); s = json.loads(suffix or '[]')
    seen = set(); out = []
    for u in list(s) + list(b):
        k = u if isinstance(u, str) else json.dumps(u, sort_keys=True)
        if k not in seen:
            seen.add(k); out.append(u)
    return json.dumps(out, ensure_ascii=False), (out != s)


def run(apply=False):
    data = json.load(open(LIST, encoding='utf-8'))
    restore = data['wrongly_deleted_restore']     # ['GBX-100-2']
    auto = data['round2_auto_1to1']               # 104
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')

    if apply:
        shutil.copy2(DB, BAK_R2); print(f'[backup] {BAK_R2}')
    c = sqlite3.connect(DB); cur = c.cursor()
    bak = sqlite3.connect(BAK_R1); bcur = bak.cursor()
    rb = {'date': now, 'restored': [], 'restored_suffix_reset': [],
          'deleted_bare_rows': [], 'pre_merge_suffix_rows': []}

    # --- 1. 復元 ---
    for pid in restore:
        src = _row(bcur, pid)
        if not src:
            print(f'  RESTORE skip (not in bak): {pid}'); continue
        live = _row(cur, pid)
        if live:
            print(f'  RESTORE skip (already present): {pid}')
        else:
            vals = [src[col] if col != 'updated_at' else now for col in COLS]
            if apply:
                cur.execute(f"INSERT INTO products ({','.join(COLS)}) VALUES ({','.join('?'*len(COLS))})", vals)
            rb['restored'].append(pid)
            print(f'  RESTORE re-insert: {pid} (src={src["source"]})')
        # 誤マージ汚染した suffix 行を .bak 状態へ戻す (GBX-100-2AJF)
        # 色2A↔2AJF の真dupは後段round2で正しく再マージされる
        suffix_pid = pid + 'AJF'
        bs = _row(bcur, suffix_pid); ls = _row(cur, suffix_pid)
        if bs and ls:
            sets = {col: bs[col] for col in RESTORE_SUFFIX_COLS}
            sets['updated_at'] = now
            if apply:
                cols = ', '.join(f'{k}=?' for k in sets)
                cur.execute(f"UPDATE products SET {cols} WHERE category='gshock' AND product_id=?",
                            list(sets.values()) + [suffix_pid])
            rb['restored_suffix_reset'].append({'product_id': suffix_pid,
                'specs_len_before': len(ls['specs'] or ''), 'specs_len_after': len(bs['specs'] or '')})
            print(f'  RESTORE reset suffix: {suffix_pid} specs {len(ls["specs"] or "")}->{len(bs["specs"] or "")}')

    # --- 2. round-2: 104 merge→delete ---
    n_specs = n_img = n_fill = n_del = 0
    for p in auto:
        bare = _row(cur, p['delete_bare']); suf = _row(cur, p['keep_suffix'])
        if not bare or not suf:
            print(f"  SKIP (missing) {p['delete_bare']} / {p['keep_suffix']}"); continue
        rb['deleted_bare_rows'].append(bare)
        rb['pre_merge_suffix_rows'].append({k: suf[k] for k in
            ('product_id','specs','images','name_jp','name_en','name_en_source','variants',
             'set_name','set_name_official','source_url')})
        sets = {}
        mspecs, ch1 = _merge_specs(bare['specs'], suf['specs'])
        if ch1: sets['specs'] = mspecs; n_specs += 1
        mimg, ch2 = _merge_images(bare['images'], suf['images'])
        if ch2: sets['images'] = mimg; n_img += 1
        for f in FILL_IF_EMPTY:
            if not suf.get(f) and bare.get(f):
                sets[f] = bare[f]; n_fill += 1
        if sets:
            sets['updated_at'] = now
            if apply:
                cols = ', '.join(f'{k}=?' for k in sets)
                cur.execute(f"UPDATE products SET {cols} WHERE category='gshock' AND product_id=?",
                            list(sets.values()) + [suf['product_id']])
        if apply:
            cur.execute("DELETE FROM products WHERE category='gshock' AND product_id=?", (bare['product_id'],))
        n_del += 1

    if apply:
        c.commit()
        json.dump(rb, open(ROLLBACK, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'[rollback] {ROLLBACK}')
    print(f"{'APPLIED' if apply else 'DRYRUN'}: restored={len(rb['restored'])} "
          f"suffix_reset={len(rb['restored_suffix_reset'])} round2_del={n_del} "
          f"specs_merged={n_specs} images_merged={n_img} fields_filled={n_fill}")


if __name__ == '__main__':
    run(apply='--apply' in sys.argv)
