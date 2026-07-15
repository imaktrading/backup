# -*- coding: utf-8 -*-
"""eBaymag の DE ミラーで無料€0 のまま焼き直し漏れした listing を SpeedPAK に一括修正。

  python fix_de_speedpak_shipping.py --count   # 無料€0 の DE ミラー件数を数えるだけ
  python fix_de_speedpak_shipping.py           # 無料€0 の DE ミラーを全て SpeedPAK 化

正: 国内 DE_EconomySppedPAK €14.86 / 国際 DE_IntlExpeditedSppedPAK €17.49 → AT のみ。
詳細は EBAYMAG_SHIPPING_RUNBOOK.md。churn 対策で定期実行可(cron)。
"""
import os, sys, re, json, time, subprocess
sys.stdout.reconfigure(encoding='utf-8')
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import dns_cache  # noqa
import requests

TOKF = 'ebay_oauth_token_sell.json'
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
