# -*- coding: utf-8 -*-
"""DEミラー(eBaymag EUR)の FedEx を全廃し、価格帯で 2 系統に振り分ける。

  python de_mirror_fedex_removal.py                    # dry-run (書込なし・計画表示)
  python de_mirror_fedex_removal.py --go --limit 10     # 先頭10件だけ実行
  python de_mirror_fedex_removal.py --go                # 全件実行
  python de_mirror_fedex_removal.py --verify            # 実状態を GetItem で照合
  python de_mirror_fedex_removal.py --rollback          # 実行前スナップショットへ戻す

## なぜ 2 系統か
SpeedPAK Economy は **取引額 €150 以下 (IOSS)** の制約がある。DEミラーは >€150 が約半分
あるため、全件を Economy にはできない。>€150 は日本郵便枠に載せる (日本郵便の EU 引受停止は
「特定8か国 × €150 未満」のみで、**€150 超は引受継続**なので停止対象外)。

| 帯 | 国内 (DE 宛) | 国際 (AT 宛) |
|---|---|---|
| ≤€150 | DE_EconomySppedPAK      (SpeedPAK Economy) | DE_IntlEconomySppedPAK  (SpeedPAK Economy) |
| >€150 | DE_SparversandAusDemAusland (日本郵便)     | DE_SonstigeInternational (日本郵便)        |

料金は **現行据え置き** (国内 €14.86 / 国際 €17.49)。目的は FedEx 全廃であって価格変更ではない。
※ ≤€150 の国際 (AT) だけは Economy 実費 (0.5kg ¥3,088×燃油1.155=¥3,567) に対し €17.49 が
  やや不足する。EURミラー経由の AT 実売は 0 件なので当面据え置き、値上げは別判断。

対地は **AT のみで変えない** (ebay.de の流入は独語圏のみ = 拡大しても取れない。
memory: ebaymag_mirror_country_assignment)。

fix_de_speedpak_shipping.py (€0 leak 監視) は**触らない**。あちらは churn 対策の別責務。
"""
import os
import re
import sys
import json
import time

sys.stdout.reconfigure(encoding='utf-8')
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import dns_cache  # noqa: F401,E402
import fix_de_speedpak_shipping as fx  # noqa: E402  (token/refresh/post を再利用)

SNAP = 'de_mirror_fedex_removal_snapshot.json'
DONE = 'de_mirror_fedex_removal_done.json'   # 途中終了しても再開できるよう成功分を逐次記録
IOSS_CAP = 150.0            # SpeedPAK Economy の取引額上限 (EU / IOSS)
DOM_COST = '14.86'          # 現行据え置き
INTL_COST = '17.49'         # 現行据え置き

BANDS = {
    'economy': {  # ≤ €150
        'dom': 'DE_EconomySppedPAK',
        'intl': 'DE_IntlEconomySppedPAK',
    },
    'jppost': {   # > €150
        'dom': 'DE_SparversandAusDemAusland',
        'intl': 'DE_SonstigeInternational',
    },
}


def band_of(price):
    return 'economy' if price <= IOSS_CAP else 'jppost'


def shipping_xml(dom_svc, intl_svc, dom_cost=DOM_COST, intl_cost=INTL_COST):
    return ('<ShippingDetails><ShippingType>Flat</ShippingType>'
            f'<ShippingServiceOptions><ShippingService>{dom_svc}</ShippingService>'
            f'<ShippingServiceCost currencyID="EUR">{dom_cost}</ShippingServiceCost>'
            '<ShippingServicePriority>1</ShippingServicePriority></ShippingServiceOptions>'
            f'<InternationalShippingServiceOption><ShippingService>{intl_svc}</ShippingService>'
            f'<ShippingServiceCost currencyID="EUR">{intl_cost}</ShippingServiceCost>'
            '<ShippingServicePriority>1</ShippingServicePriority>'
            '<ShipToLocation>AT</ShipToLocation></InternationalShippingServiceOption>'
            '</ShippingDetails>')


def enumerate_eur(tok):
    """EUR 建て (= DEミラー) の active listing を全件、価格つきで返す。"""
    out = []
    for n in range(1, 60):
        inner = ('<ActiveList><Include>true</Include><Pagination>'
                 f'<EntriesPerPage>200</EntriesPerPage><PageNumber>{n}</PageNumber></Pagination></ActiveList>')
        t = fx.post('GetMyeBaySelling', inner, tok)
        al = t[t.find('<ActiveList>'):t.find('</ActiveList>')]
        items = re.findall(r'<Item>(.*?)</Item>', al, re.S)
        if not items:
            break
        for it in items:
            cp = re.search(r'<CurrentPrice currencyID="(\w+)">([\d.]+)<', it)
            iid = re.search(r'<ItemID>(\d+)</ItemID>', it)
            if cp and iid and cp.group(1) == 'EUR':
                out.append({'id': iid.group(1), 'price': float(cp.group(2))})
        tp = re.search(r'<TotalNumberOfPages>(\d+)</TotalNumberOfPages>', t)
        if tp and n >= int(tp.group(1)):
            break
    return out


def read_shipping(iid, tok):
    """GetItem で現在の 国内/国際 サービス・料金・宛先 を読む。"""
    x = fx.post('GetItem', f'<ItemID>{iid}</ItemID><DetailLevel>ReturnAll</DetailLevel>', tok, site='77')
    sd = x[x.find('<ShippingDetails>'):x.find('</ShippingDetails>')]

    def one(blk):
        s = re.search(r'<ShippingService>(.*?)</ShippingService>', blk)
        c = re.search(r'<ShippingServiceCost currencyID="(\w+)">([\d.]+)<', blk)
        return {'svc': s.group(1) if s else None,
                'cost': c.group(2) if c else None,
                'loc': re.findall(r'<ShipToLocation>(.*?)</ShipToLocation>', blk)}

    dom = re.findall(r'<ShippingServiceOptions>(.*?)</ShippingServiceOptions>', sd, re.S)
    intl = re.findall(r'<InternationalShippingServiceOption>(.*?)</InternationalShippingServiceOption>', sd, re.S)
    return {'dom': [one(b) for b in dom], 'intl': [one(b) for b in intl]}


def revise(iid, sd_xml, tok):
    """1件 revise。トークン失効時は refresh して1回だけ再試行。戻り値 (ack, tok, errmsg)。"""
    for attempt in (1, 2):
        resp = fx.post('ReviseFixedPriceItem', f'<Item><ItemID>{iid}</ItemID>{sd_xml}</Item>', tok, site='77')
        m = re.search(r'<Ack>(.*?)</Ack>', resp)
        ack = m.group(1) if m else '?'
        if ack in ('Success', 'Warning'):
            return ack, tok, ''
        if attempt == 1 and re.search(r'IAF|Token|gültig|abgelaufen|expired', resp, re.I):
            fx.refresh()
            tok = fx.token()
            continue
        errs = re.findall(r'<LongMessage>(.*?)</LongMessage>', resp)
        return ack, tok, ' | '.join(errs[:2])[:300]
    return '?', tok, 'retry exhausted'


def cmd_plan(rows):
    lo = [r for r in rows if r['price'] <= IOSS_CAP]
    hi = [r for r in rows if r['price'] > IOSS_CAP]
    print(f'DEミラー(EUR) active: {len(rows)}件')
    print(f'  ≤€{IOSS_CAP:.0f} : {len(lo):>4}件 → 国内 {BANDS["economy"]["dom"]:<28} '
          f'/ 国際 {BANDS["economy"]["intl"]} → AT')
    print(f'  >€{IOSS_CAP:.0f} : {len(hi):>4}件 → 国内 {BANDS["jppost"]["dom"]:<28} '
          f'/ 国際 {BANDS["jppost"]["intl"]} → AT')
    print(f'  料金は据え置き: 国内 €{DOM_COST} / 国際 €{INTL_COST}')
    print('\nFedEx (DE_IntlExpeditedSppedPAK) は全件から消える。')
    return lo, hi


def cmd_verify(rows, tok, n=None):
    """実状態を GetItem で照合。帯ごとの期待値と一致するか数える。"""
    sample = rows if n is None else rows[:n]
    ok = ng = 0
    bad = []
    fedex = 0
    for i, r in enumerate(sample, 1):
        b = BANDS[band_of(r['price'])]
        cur = read_shipping(r['id'], tok)
        dsvc = cur['dom'][0]['svc'] if cur['dom'] else None
        isvc = cur['intl'][0]['svc'] if cur['intl'] else None
        iloc = cur['intl'][0]['loc'] if cur['intl'] else []
        if isvc == 'DE_IntlExpeditedSppedPAK':
            fedex += 1
        if dsvc == b['dom'] and isvc == b['intl'] and iloc == ['AT']:
            ok += 1
        else:
            ng += 1
            bad.append({'id': r['id'], 'price': r['price'], 'dom': dsvc, 'intl': isvc, 'loc': iloc})
        if i % 25 == 0 or i == len(sample):
            print(f'  verify {i}/{len(sample)}  一致={ok} 不一致={ng} FedEx残={fedex}', flush=True)
    if bad:
        print(f'\n不一致 {len(bad)}件 (先頭10):')
        for b in bad[:10]:
            print(f'  {b["id"]} €{b["price"]}  dom={b["dom"]} intl={b["intl"]} loc={b["loc"]}')
    print(f'\nVERIFY: 一致={ok} 不一致={ng} FedEx残={fedex} / {len(sample)}件')
    return ng == 0 and fedex == 0


def cmd_go(rows, tok, limit=None):
    target = rows if limit is None else rows[:limit]
    # --- 実行前スナップショット (rollback 用) ---
    snap = json.load(open(SNAP)) if os.path.exists(SNAP) else {}
    todo = [r for r in target if r['id'] not in snap]
    print(f'スナップショット取得: {len(todo)}件 (既存 {len(snap)}件はスキップ)')
    for i, r in enumerate(todo, 1):
        snap[r['id']] = {'price': r['price'], 'before': read_shipping(r['id'], tok)}
        if i % 25 == 0 or i == len(todo):
            print(f'  snap {i}/{len(todo)}', flush=True)
            json.dump(snap, open(SNAP, 'w'), ensure_ascii=False)
    json.dump(snap, open(SNAP, 'w'), ensure_ascii=False)

    # --- 既に反映済 (前回 run) はスキップ = 途中終了からの再開 ---
    done = set(json.load(open(DONE))) if os.path.exists(DONE) else set()
    if '--force' in sys.argv:
        done = set()
    todo2 = [r for r in target if r['id'] not in done]
    print(f'revise 対象: {len(todo2)}件 (反映済 {len(target) - len(todo2)}件はスキップ)')

    ok = warn = fail = 0
    failed = []
    for i, r in enumerate(todo2, 1):
        b = BANDS[band_of(r['price'])]
        ack, tok, err = revise(r['id'], shipping_xml(b['dom'], b['intl']), tok)
        if ack in ('Success', 'Warning'):
            done.add(r['id'])
            ok += 1 if ack == 'Success' else 0
            warn += 1 if ack == 'Warning' else 0
        else:
            fail += 1
            failed.append({'id': r['id'], 'price': r['price'], 'ack': ack, 'err': err})
            print(f'  FAIL {r["id"]} €{r["price"]} ack={ack} {err}', flush=True)
        if i % 25 == 0 or i == len(todo2):
            json.dump(sorted(done), open(DONE, 'w'))   # 逐次保存 = 落ちても再開できる
            print(f'{i}/{len(todo2)}  ok={ok} warn={warn} fail={fail} (累計反映 {len(done)})', flush=True)
        time.sleep(0.15)
    json.dump(sorted(done), open(DONE, 'w'))
    print(f'DONE ok={ok} warn={warn} fail={fail} / 累計反映 {len(done)}/{len(target)}')
    remain = [r['id'] for r in target if r['id'] not in done]
    if failed or remain:
        json.dump({'failed': failed, 'remaining': remain},
                  open('de_mirror_fedex_removal_failed.json', 'w'), ensure_ascii=False)
        print(f'★未処理 {len(remain)}件 = 要対応 (再実行で自動再開) '
              f'→ de_mirror_fedex_removal_failed.json')
    return tok, not remain


def cmd_rollback(tok):
    if not os.path.exists(SNAP):
        print('スナップショットが無い。rollback 不可。')
        return
    snap = json.load(open(SNAP))
    print(f'rollback 対象: {len(snap)}件')
    ok = fail = 0
    for i, (iid, v) in enumerate(snap.items(), 1):
        bf = v['before']
        if not bf['dom'] or not bf['intl']:
            print(f'  SKIP {iid} (before が不完全)')
            continue
        d, it = bf['dom'][0], bf['intl'][0]
        sd = shipping_xml(d['svc'], it['svc'], d['cost'], it['cost'])
        ack, tok, err = revise(iid, sd, tok)
        if ack in ('Success', 'Warning'):
            ok += 1
        else:
            fail += 1
            print(f'  FAIL {iid} {ack} {err}')
        if i % 25 == 0 or i == len(snap):
            print(f'  {i}/{len(snap)} ok={ok} fail={fail}', flush=True)
        time.sleep(0.15)
    print(f'ROLLBACK DONE ok={ok} fail={fail}')


def main():
    args = sys.argv[1:]
    limit = None
    if '--limit' in args:
        limit = int(args[args.index('--limit') + 1])

    fx.refresh()
    tok = fx.token()

    if '--rollback' in args:
        cmd_rollback(tok)
        return

    rows = enumerate_eur(tok)
    rows.sort(key=lambda r: r['id'])
    lo, hi = cmd_plan(rows)

    if '--verify' in args:
        cmd_verify(rows if limit is None else rows[:limit], tok)
        return

    if '--go' not in args:
        print('\n(dry-run。書込なし。実行するには --go を付ける)')
        return

    tok, all_ok = cmd_go(rows, tok, limit)
    print('\n--- 実状態を照合 ---')
    cmd_verify(rows if limit is None else rows[:limit], tok)


if __name__ == '__main__':
    main()
