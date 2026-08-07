# -*- coding: utf-8 -*-
"""eBay の fulfillment policy を全 marketplace から取って、スプシに保存する。

なぜ: `DDP対応sippingポリシー` スプシの `EU国一覧` が 2026-07-30 の
      「SpeedPAK Economy が EU27 へ拡大」より前の内容 (Economy=独だけ/他はFedEx) のまま。
      **実ポリシーは API で読めるので、推測でなく実物を保存する。**

★rate table の中身だけは API で読めない (rateTableId しか返らない)。そこは注記する。
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, r'C:\dev\iMak\iMakeBayAPI')
os.chdir(r'C:\dev\iMak\iMakeBayAPI')
import dns_cache  # noqa: F401,E402
import requests   # noqa: E402
import gspread    # noqa: E402
from google.oauth2.service_account import Credentials  # noqa: E402

TOK = json.load(open('ebay_oauth_token_sell.json'))['access_token']
SHEET = '10ey-ACBlbIBR5QbnWTjnwaltjINPOd6cUN-4N5xSUIo'
CR = r'C:\dev\iMak\double-hold-421922-7c0d38d3f73d.json'
SC = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
JST = timezone(timedelta(hours=9))

rows = []
for mkt in ('EBAY_US', 'EBAY_DE'):
    r = requests.get('https://api.ebay.com/sell/account/v1/fulfillment_policy',
                     headers={'Authorization': f'Bearer {TOK}'},
                     params={'marketplace_id': mkt, 'limit': 200}, timeout=60)
    if r.status_code != 200:
        print(f'{mkt}: HTTP {r.status_code} {r.text[:200]}')
        continue
    pols = r.json().get('fulfillmentPolicies', [])
    print(f'{mkt}: {len(pols)} 本')
    for p in pols:
        for so in p.get('shippingOptions', []):
            ot = so.get('optionType')
            rt = so.get('rateTableId') or ''
            cst = so.get('costType') or ''
            svcs = so.get('shippingServices') or []
            if not svcs:
                svcs = [{}]
            for s in svcs:
                loc = s.get('shipToLocations') or {}
                inc = ",".join(x.get('regionName', '') for x in loc.get('regionIncluded', []))
                exc = ",".join(x.get('regionName', '') for x in loc.get('regionExcluded', []))
                rows.append([
                    mkt, p.get('name', ''), p.get('fulfillmentPolicyId', ''),
                    ot, cst, s.get('shippingServiceCode', ''),
                    (s.get('shippingCost') or {}).get('value', ''),
                    (s.get('shippingCost') or {}).get('currency', ''),
                    (s.get('additionalShippingCost') or {}).get('value', ''),
                    'YES' if s.get('freeShipping') else '',
                    rt, inc, exc[:180],
                    (p.get('handlingTime') or {}).get('value', ''),
                ])

hdr = ['マーケット', 'ポリシー名', 'ポリシーID', '国内/国際', '課金方式', 'サービスコード',
       '送料', '通貨', '追加送料', '送料無料', 'rateTableId', '発送可能地域', '除外地域',
       '発送準備日数']
now = datetime.now(JST).strftime('%Y-%m-%d %H:%M')
title = f'ポリシー実物_{datetime.now(JST):%Y%m%d}'

sh = gspread.authorize(Credentials.from_service_account_file(CR, scopes=SC)).open_by_key(SHEET)
try:
    ws = sh.worksheet(title)
    sh.del_worksheet(ws)
except gspread.WorksheetNotFound:
    pass
ws = sh.add_worksheet(title=title, rows=len(rows) + 12, cols=len(hdr))
note = [
    [f'■ eBay の実ポリシー (Account API から自動取得)   取得日時: {now} JST'],
    ['  出典: GET /sell/account/v1/fulfillment_policy  (marketplace_id 別)。手入力ではない'],
    ['  ★rate table の中身 (国別の金額) は API では取得できない。rateTableId のみ。'
     '   金額は eBay の UI でしか見えない'],
    ['  ★2026-07-30 に SpeedPAK Economy の対地が「米英独豪」から EU27 全域へ拡大している。'
     '   旧タブ `EU国一覧` はそれ以前の内容なので注意'],
    [''],
]
ws.update(values=note + [hdr] + rows, range_name='A1', value_input_option='USER_ENTERED')
ws.format(f'A{len(note)+1}:N{len(note)+1}',
          {'textFormat': {'bold': True}, 'backgroundColor': {'red': .87, 'green': .90, 'blue': .96}})
ws.freeze(rows=len(note) + 1)
print(f'\n✅ 保存: タブ「{title}」 {len(rows)} 行')
print(f'   https://docs.google.com/spreadsheets/d/{SHEET}/edit#gid={ws.id}')
