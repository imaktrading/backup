# -*- coding: utf-8 -*-
"""UNIQLO/GU 商品の公式「仕上がり寸(inch)」を全サイズ取得する。

公式 JSON API には寸法が無く(sizeInformation空 / sizes は名前のみ / .../size-chart は404)、
sizeChartUrl(.../size/<code>_size.html)は S3 AccessDenied で bot 直リン不可。
だが PDP のサイズ表モーダルを自動操作すれば全サイズ(XS〜3XL 等)の実寸が読める。

使い方:
    python uniqlo_size_fetch.py E483259-000
    python uniqlo_size_fetch.py E483259-000 08 004   # color/size displayCode 任意

出力: サイズ | 身丈(Length) | 肩幅(Shoulder) | 身幅(Chest) | 裄丈(Sleeve) （inch）
JP→US は one-down(JP S=US XS … JP XXL=US XL, JP 3XL=US 2XL)。
"""
import sys, time, re, winreg
sys.stdout.reconfigure(encoding='utf-8')
import undetected_chromedriver as uc


def detect_chrome_major():
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            k = winreg.OpenKey(hive, r'Software\Google\Chrome\BLBeacon')
            v, _ = winreg.QueryValueEx(k, 'version')
            return int(v.split('.')[0])
        except Exception:
            pass
    return None


def fetch_finished_measurements(product_id, color='', size=''):
    """returns list of rows: (size_name, length, shoulder, chest, sleeve) as strings (inch)."""
    opts = uc.ChromeOptions()
    opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--window-size=1500,2800')
    opts.add_argument('--lang=ja-JP')
    d = uc.Chrome(options=opts, version_main=detect_chrome_major())

    def click_text(txt, exact=False):
        xp = f"//*[normalize-space(text())='{txt}']" if exact else f"//*[contains(text(),'{txt}')]"
        for e in d.find_elements('xpath', xp):
            try:
                d.execute_script('arguments[0].scrollIntoView({block:"center"});', e)
                try:
                    e.click()
                except Exception:
                    d.execute_script('arguments[0].click();', e)
                return True
            except Exception:
                pass
        return False

    try:
        url = f'https://www.uniqlo.com/jp/ja/products/{product_id}/00'
        q = []
        if color:
            q.append(f'colorDisplayCode={color}')
        if size:
            q.append(f'sizeDisplayCode={size}')
        if q:
            url += '?' + '&'.join(q)
        d.get(url)
        time.sleep(6)
        click_text('サイズを確認'); time.sleep(5)
        click_text('仕上がり寸', exact=True); time.sleep(2)
        click_text('inch', exact=True); time.sleep(2)
        body = d.find_element('tag name', 'body').text
    finally:
        try:
            d.quit()
        except Exception:
            pass

    # parse block: header "サイズ 身丈 肩幅 ... 身幅 裄丈" then per-size lines
    i = body.find('サイズ 身丈')
    if i < 0:
        raise RuntimeError('仕上がり寸テーブルが取得できず(モーダル未展開の可能性)')
    seg = body[i:i + 1200]
    lines = [x.strip() for x in seg.split('\n') if x.strip()]
    # lines after the header row: SizeName, then 4 numbers each on its own line
    rows = []
    j = 0
    # skip header tokens until first size label
    size_labels = ['XS', 'S', 'M', 'L', 'XL', 'XXL', '3XL', '4XL', 'XXS']
    k = 0
    while k < len(lines):
        if lines[k] in size_labels and k + 4 < len(lines):
            nums = lines[k + 1:k + 5]
            if all(re.match(r'^\d', n) for n in nums):
                rows.append((lines[k], *nums))
                k += 5
                continue
        k += 1
    return rows


if __name__ == '__main__':
    pid = sys.argv[1] if len(sys.argv) > 1 else 'E483259-000'
    col = sys.argv[2] if len(sys.argv) > 2 else ''
    siz = sys.argv[3] if len(sys.argv) > 3 else ''
    rows = fetch_finished_measurements(pid, col, siz)
    print(f'# {pid}  仕上がり寸 (inch)  身丈/肩幅/身幅/裄丈 = Length/Shoulder/Chest/Sleeve')
    for r in rows:
        print('  ', ' | '.join(r))
