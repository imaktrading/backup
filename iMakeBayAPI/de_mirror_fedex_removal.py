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
# ★2026-07-31 確定 (V9 スプシ・ユーザー確定):
#     送料 = (その手段の実費 − 国際エアパケット実費) + 当方負担の関税
#   - EU ≤€150 : SpeedPAK Economy (IOSS/DDP・関税は当方負担) → **有料**
#   - EU >€150 : 国際エアパケット (DDU・関税は買い手着払い)   → **€0**
#
#   朝の時点では「他ミラーは €0 なのに DE だけ €14.86 = 二重取り → 全部 €0」と判断していたが、
#   それが正しいのは **>€150 帯だけ**。≤€150 は SpeedPAK で送り DDP コスト(関税込)を当方が負担
#   するので、その差額はバイヤーから徴収する。全帯 €0 にすると ≤€150 が全額持ち出しになる。
#
#   ★「国際エアパケット実費」は V9 `設定` の **カテゴリ別 実送料(JPY)** で、2000〜3500 と幅がある。
#     DEミラー実測(2026-07-31, 708件)でも TCG/G-shock/UT(=2000) 以外に montbell 等が混在するため、
#     料金は 1本の定数ではなく **カテゴリごとに算出**する。
DDP_COST_JPY = {'DE': 3218.535, 'AT': 4133.295}   # 実費(0.5kg・燃油込) + 関税・手数料
FALLBACK_EURJPY = 184.4495                        # 取得失敗時のみ (実行時は live を引く)
DEFAULT_SHIP_JPY = 2000                           # カテゴリ不明時 (最頻値)

# V9 `設定` のカテゴリ別 実送料(JPY)
CATEGORY_SHIP_JPY = {
    'TCG(PSA10)': 2000, 'G-SHOCK': 2000, 'Tシャツ(UT)': 2000, 'Montbell(軽)': 2000,
    'ユニクロ(非UT)': 2000, 'トミカ': 2000, 'POPMart': 2000, 'ガシャポン': 2000,
    'サンリオ文具': 2000, 'ヴィンテージ玩具': 2000, 'ダイソー': 2000,
    'サンリオぬいぐるみ': 2500,
    'Montbell(重)': 3000, '一番くじ': 3000, 'フィギュア': 3000, 'バッグ(アネロ)': 3000, 'リール': 3000,
    'Porter': 3500,
}

BANDS = {
    'economy': {  # ≤ €150 … SpeedPAK Economy (DDP)。料金は economy_costs() でカテゴリ別に算出
        'dom': 'DE_EconomySppedPAK',
        'intl': 'DE_IntlEconomySppedPAK',
        'paid': True,
    },
    'jppost': {   # > €150 … 国際エアパケット (DDU)。カテゴリに依らず €0
        'dom': 'DE_SparversandAusDemAusland',
        'intl': 'DE_SonstigeInternational',
        'paid': False,
    },
}


def eur_jpy():
    """実行時点の EUR/JPY を V9 `設定`!F2 から引く。失敗時は FALLBACK (警告つき)。"""
    try:
        sys.path.insert(0, r'C:/dev/iMak/iMakHQ/tools')
        import gspread
        from google.oauth2.service_account import Credentials
        import sheet_io as _si
        cr = Credentials.from_service_account_file(
            _si.CREDS_PATH, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        v = gspread.authorize(cr).open_by_key(
            '1YLnR4aW5cgjquYXUaNPb_hnVwrHegobZyh-eAT6tVM0').worksheet('設定').acell('F2').value
        return float(str(v).replace(',', ''))
    except Exception as e:      # noqa: BLE001
        print(f'  ⚠ EUR/JPY を取得できず fallback {FALLBACK_EURJPY} 使用 ({type(e).__name__})')
        return FALLBACK_EURJPY


def economy_costs(ship_jpy, rate):
    """≤€150 帯の (国内DE, 国際AT) 送料 (純関数)。

    差額が負になるカテゴリ (実送料 > DDPコスト) は 0 にする = バイヤーから取り過ぎない。
    """
    def one(dest):
        return f'{max((DDP_COST_JPY[dest] - ship_jpy) / rate, 0.0):.2f}'
    return one('DE'), one('AT')


def costs_for(band, ship_jpy, rate):
    """帯 + カテゴリ実送料 → (国内, 国際) 送料文字列 (純関数)。>€150 は常に €0。"""
    if not BANDS[band]['paid']:
        return '0.00', '0.00'
    return economy_costs(ship_jpy, rate)


def _money(v):
    """'14.86' / 14.86 / None を比較可能な小数2桁文字列に (純関数)。None は ''。"""
    if v in (None, ''):
        return ''
    try:
        return f'{float(v):.2f}'
    except (TypeError, ValueError):
        return str(v)


FX_TOLERANCE_EUR = 0.20      # 為替ドリフト許容 (€0.20 ≈ ¥37)


def _cost_matches(actual, expected):
    """実料金が期待どおりか (純関数)。

    ★為替は毎回 live で引くので、書込時と照合時で期待値が数セント動く。厳密一致にすると
    正しく反映済でも「不一致」になる (実測: €6.61 書込 → 照合時 €6.64 で false negative)。
    - **無料(0) と有料の取り違えは許さない** … 帯を間違えた = 定義違反なので厳格に見る
    - 有料どうしは ±FX_TOLERANCE_EUR まで許容
    """
    a, e = _money(actual), _money(expected)
    if e == '' or a == '':
        return a == e
    fa, fe = float(a), float(e)
    if fe == 0.0 or fa == 0.0:
        return fa == fe
    return abs(fa - fe) <= FX_TOLERANCE_EUR


def ship_jpy_of(row):
    """listing の SKU/タイトルから V9 カテゴリの実送料(JPY)を決める (純関数)。

    ★確実に判るものだけ分類し、不明は DEFAULT_SHIP_JPY。推測で 3000 側に倒すと
    バイヤーから取る額が減る (= こちらの持ち出し) ので、不明は最頻値 2000 に置く。
    """
    sku = (row.get('sku') or '').strip()
    title = (row.get('title') or '')
    up = sku.upper()
    if up.startswith('PSA10') or title.startswith('PSA 10'):
        return CATEGORY_SHIP_JPY['TCG(PSA10)']
    if re.search(r'\bG-SHOCK\b|CASIO', title, re.I):
        return CATEGORY_SHIP_JPY['G-SHOCK']
    if 'UNIQLO' in up or up.startswith('UT-') or 'TEMPLATE_NWT' in up:
        return CATEGORY_SHIP_JPY['Tシャツ(UT)']
    if 'MONTBELL' in up:
        return CATEGORY_SHIP_JPY['Montbell(軽)']
    return DEFAULT_SHIP_JPY


def band_of(price):
    return 'economy' if price <= IOSS_CAP else 'jppost'


def shipping_xml(dom_svc, intl_svc, dom_cost, intl_cost):
    """★料金は必ず呼び手が渡す (帯 + カテゴリで変わるため既定値を持たせない。2026-07-31)。"""
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
                # SKU/Title も持つ (カテゴリ別の実送料を決めるのに要る。2026-07-31)
                sku = re.search(r'<SKU>(.*?)</SKU>', it)
                ttl = re.search(r'<Title>(.*?)</Title>', it, re.S)
                out.append({'id': iid.group(1), 'price': float(cp.group(2)),
                            'sku': sku.group(1) if sku else '',
                            'title': ttl.group(1) if ttl else ''})
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
    rate = eur_jpy()
    d2, i2 = economy_costs(DEFAULT_SHIP_JPY, rate)
    print(f'  料金 (EUR/JPY={rate:.4f}):')
    print(f'    ≤€{IOSS_CAP:.0f} = (DDPコスト − カテゴリ別実送料) / レート'
          f'  … 実送料¥{DEFAULT_SHIP_JPY} なら 国内 €{d2} / 国際 €{i2}')
    for jpy in sorted({v for v in CATEGORY_SHIP_JPY.values()} - {DEFAULT_SHIP_JPY}):
        dd, ii = economy_costs(jpy, rate)
        print(f'                                        実送料¥{jpy} なら 国内 €{dd} / 国際 €{ii}')
    print(f'    >€{IOSS_CAP:.0f} = 国内 €0.00 / 国際 €0.00 (DDU・関税は買い手着払い)')
    print('\nFedEx (DE_IntlExpeditedSppedPAK) は全件から消える。')
    return lo, hi


def cmd_verify(rows, tok, n=None):
    """実状態を GetItem で照合。帯ごとの期待値と一致するか数える。

    ★2026-07-31: **料金も照合する**。従来はサービス名/宛先しか見ておらず、料金が
    €14.86/€17.49 のままでも「一致」と報告していた (実測でサービスだけ切替済・料金据置と判明)。
    verify が緑なのに実態が違う = 最も避けたい検証の穴なので塞ぐ。
    """
    sample = rows if n is None else rows[:n]
    rate = eur_jpy()
    ok = ng = 0
    bad = []
    fedex = 0
    for i, r in enumerate(sample, 1):
        band = band_of(r['price'])
        b = BANDS[band]
        exp_d, exp_i = costs_for(band, ship_jpy_of(r), rate)
        cur = read_shipping(r['id'], tok)
        dsvc = cur['dom'][0]['svc'] if cur['dom'] else None
        isvc = cur['intl'][0]['svc'] if cur['intl'] else None
        iloc = cur['intl'][0]['loc'] if cur['intl'] else []
        dcost = cur['dom'][0].get('cost') if cur['dom'] else None
        icost = cur['intl'][0].get('cost') if cur['intl'] else None
        if isvc == 'DE_IntlExpeditedSppedPAK':
            fedex += 1
        svc_ok = (dsvc == b['dom'] and isvc == b['intl'] and iloc == ['AT'])
        cost_ok = _cost_matches(dcost, exp_d) and _cost_matches(icost, exp_i)
        if svc_ok and cost_ok:
            ok += 1
        else:
            ng += 1
            bad.append({'id': r['id'], 'price': r['price'], 'dom': dsvc, 'intl': isvc,
                        'loc': iloc, 'cost': f'{dcost}/{icost}', 'exp': f'{exp_d}/{exp_i}',
                        'why': ('svc' if not svc_ok else '') + ('cost' if not cost_ok else '')})
        if i % 25 == 0 or i == len(sample):
            print(f'  verify {i}/{len(sample)}  一致={ok} 不一致={ng} FedEx残={fedex}', flush=True)
    if bad:
        print(f'\n不一致 {len(bad)}件 (先頭10):')
        for b in bad[:10]:
            print(f'  {b["id"]} €{b["price"]} [{b["why"]}] dom={b["dom"]} intl={b["intl"]} '
                  f'loc={b["loc"]} 料金 {b["cost"]} (期待 {b["exp"]})')
    print(f'\nVERIFY: 一致={ok} 不一致={ng} FedEx残={fedex} / {len(sample)}件')
    return ng == 0 and fedex == 0


def cmd_go(rows, tok, limit=None):
    target = rows if limit is None else rows[:limit]
    rate = eur_jpy()                       # ★実行時点のレートで再計算 (依頼書の指示)
    import collections as _c
    mix = _c.Counter(ship_jpy_of(r) for r in target if band_of(r['price']) == 'economy')
    print(f'EUR/JPY={rate:.4f} / ≤€{IOSS_CAP:.0f} 帯のカテゴリ実送料内訳: '
          + ' / '.join(f'¥{k}×{v}' for k, v in sorted(mix.items())))
    for jpy in sorted(mix):
        d, i = economy_costs(jpy, rate)
        print(f'    実送料¥{jpy} → 国内 €{d} / 国際 €{i}')
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
        band = band_of(r['price'])
        b = BANDS[band]
        dom_c, intl_c = costs_for(band, ship_jpy_of(r), rate)
        ack, tok, err = revise(r['id'], shipping_xml(b['dom'], b['intl'], dom_c, intl_c), tok)
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

    # ★2026-07-31: 帯を指定して試験できるようにする。--limit だけだと先頭から取るため、
    #   >€150 (€0) ばかり当たって **有料側 (≤€150) を実証できない**。
    if '--band' in args:
        want = args[args.index('--band') + 1]
        if want not in BANDS:
            print(f'--band は {list(BANDS)} のいずれか'); return
        rows = [r for r in rows if band_of(r['price']) == want]
        print(f'\n★--band {want} で絞込: {len(rows)}件')

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
