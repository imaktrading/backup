# -*- coding: utf-8 -*-
"""DE ミラーの送料 leak 検出器 (2026-07-31 に **正常判定を反転**)。

  python fix_de_speedpak_shipping.py --count   # 現行の送料設定を数えるだけ (判定はしない)
  python fix_de_speedpak_shipping.py           # 同上 (自動修正はしない。理由は下記)

★正は **帯で違う** (2026-07-31 ユーザー確定・V9 スプシに実装済):

    送料 = (その手段の実費 − 国際エアパケット実費) + 当方負担の関税

  - **EU ≤€150** : SpeedPAK Economy (IOSS/DDP・関税は当方負担) → **有料**
                   実送料¥2000 のカテゴリなら 国内 €6.61 / 国際 €11.57 (レートで変動)
  - **EU >€150** : 国際エアパケット (DDU・関税は買い手着払い)  → **€0**

  経緯: 同一SKU 5ミラーの実測 (PSA10 Pikachu / SKU m76107330544) で
    UK £188.35 + £0 / CA C$355.36 + C$0 / AU A$363.69 + A$0  → 本体だけで ¥40.5千に揃う
    DE  €220.62 + €14.86                                     → DE だけ ¥2,700 高い
  となり「DE だけ二重取り → 全部 €0」と判断したが、**それが正しいのは >€150 帯だけ**。
  ≤€150 は SpeedPAK で送り DDP コスト(関税込)を当方が負担するので、その差額は徴収する。
  全帯 €0 にすると ≤€150 が全額持ち出しになる。

  → 従来の「€0 は焼き直し漏れ = €14.86 に戻す」も、7/31 朝の「€0 が正」も **どちらも誤り**。
    帯 (と ≤€150 ではカテゴリ別実送料) を見ないと正否は判定できない。

★自動修正はしない: 送料を直すには価格帯 (≤€150=Economy / >€150=日本郵便) で
  **ShippingService も切り替える**必要があり、本ツールは帯を見ていない。
  修正は帯を持つ `de_mirror_fedex_removal.py` で行うこと。

詳細は EBAYMAG_SHIPPING_RUNBOOK.md。
"""
import os, sys, re, json, time, subprocess
sys.stdout.reconfigure(encoding='utf-8')
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import dns_cache  # noqa
import requests

# ★2026-08-21: トークンの場所は credentials.py が決める (共有領域が本物)。
#   2か所に置いたまま片方だけ更新されると腐るため (カタログ依頼)。
from credentials import token_path as _token_path   # noqa: E402
TOKF = _token_path('sell')
EP = 'https://api.ebay.com/ws/api.dll'
SD = ('<ShippingDetails><ShippingType>Flat</ShippingType>'
      '<ShippingServiceOptions><ShippingService>DE_EconomySppedPAK</ShippingService>'
      '<ShippingServiceCost currencyID="EUR">14.86</ShippingServiceCost><ShippingServicePriority>1</ShippingServicePriority></ShippingServiceOptions>'
      '<InternationalShippingServiceOption><ShippingService>DE_IntlExpeditedSppedPAK</ShippingService>'
      '<ShippingServiceCost currencyID="EUR">17.49</ShippingServiceCost><ShippingServicePriority>1</ShippingServicePriority>'
      '<ShipToLocation>AT</ShipToLocation></InternationalShippingServiceOption></ShippingDetails>')


def token():
    return json.load(open(TOKF))['access_token']


def refresh():
    for _ in range(6):
        r = subprocess.run([sys.executable, 'oauth_sell_setup.py', 'refresh'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        if 'access_token' in ((r.stdout or '') + (r.stderr or '')):
            return
        time.sleep(3)


def post(callname, inner, tok, site='0'):
    hdr = {'X-EBAY-API-CALL-NAME': callname, 'X-EBAY-API-SITEID': site,
           'X-EBAY-API-COMPATIBILITY-LEVEL': '1271', 'X-EBAY-API-IAF-TOKEN': tok, 'Content-Type': 'text/xml'}
    body = (f'<?xml version="1.0" encoding="utf-8"?><{callname}Request xmlns="urn:ebay:apis:eBLBaseComponents">'
            f'{inner}</{callname}Request>')
    for _ in range(4):
        try:
            r = requests.post(EP, data=body.encode('utf-8'), headers=hdr, timeout=90)
            r.encoding = 'utf-8'
            return r.text
        except requests.exceptions.ConnectionError:
            time.sleep(3)
    return ''


def enumerate_free_de(tok):
    free = []
    for n in range(1, 60):
        inner = ('<ActiveList><Include>true</Include><Pagination>'
                 f'<EntriesPerPage>100</EntriesPerPage><PageNumber>{n}</PageNumber></Pagination></ActiveList>')
        t = post('GetMyeBaySelling', inner, tok)
        al = t[t.find('<ActiveList>'):t.find('</ActiveList>')]
        items = re.findall(r'<Item>(.*?)</Item>', al, re.S)
        if not items:
            break
        for it in items:
            cp = re.search(r'<CurrentPrice currencyID="(\w+)">', it)
            sc = re.search(r'<ShippingServiceCost currencyID="(\w+)">([\d.]+)</ShippingServiceCost>', it)
            if cp and cp.group(1) == 'EUR' and sc and float(sc.group(2)) == 0.0:
                free.append(re.search(r'<ItemID>(\d+)</ItemID>', it).group(1))
    return free


def main():
    refresh()
    tok = token()
    free = enumerate_free_de(tok)
    print(f'無料€0 の DE ミラー: {len(free)} 件')
    if '--count' in sys.argv or not free:
        return
    ok = warn = fail = 0
    failed = []
    for i, iid in enumerate(free, 1):
        resp = post('ReviseFixedPriceItem', f'<Item><ItemID>{iid}</ItemID>{SD}</Item>', tok, site='77')
        ack = re.search(r'<Ack>(.*?)</Ack>', resp)
        ack = ack.group(1) if ack else '?'
        if ack not in ('Success', 'Warning') and re.search(r'IAF|Token|gültig|abgelaufen', resp):
            refresh(); tok = token()
            resp = post('ReviseFixedPriceItem', f'<Item><ItemID>{iid}</ItemID>{SD}</Item>', tok, site='77')
            ack = re.search(r'<Ack>(.*?)</Ack>', resp)
            ack = ack.group(1) if ack else '?'
        if ack == 'Success':
            ok += 1
        elif ack == 'Warning':
            warn += 1
        else:
            fail += 1; failed.append(iid)
        if i % 25 == 0 or i == len(free):
            print(f'{i}/{len(free)}  ok={ok} warn={warn} fail={fail}', flush=True)
        time.sleep(0.15)
    print(f'DONE ok={ok} warn={warn} fail={fail}')
    if failed:
        json.dump(failed, open('de_speedpak_failed.json', 'w'))


if __name__ == '__main__':
    main()
