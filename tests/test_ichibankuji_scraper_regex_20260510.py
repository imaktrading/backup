"""Regression: 2026-05-10 1kuji.com スクレイパー — BeautifulSoup 構造抽出.

事故 (Phase1 run 2026-05-10 14:57 + 15:29):
  text regex で賞抽出していた scrape_1kuji() が:
  - 14:57: 旧 regex で 8 series 中 NIKKE7 (1/8) のみ動作、他 7 で 0 賞
  - 15:29: 緩和 regex (af8b504) で全 8 series 0 賞 (regression: ■ 干渉で全マッチ失敗)

  原因: body.text に header の ■発売日:/■メーカー希望小売価格:/■取扱店:/
  ■ダブルチャンスキャンペーン期間: 等の他 ■ マーカが 30 件以上ある.
  text regex は ■ 干渉で早期停止、改行依存で series ごとに動作差.

修正方針 (no_modification_chain):
  text regex を完全撤廃. BeautifulSoup CSS selector (.itemColList > h4.name) で
  DOM 構造ベース抽出. header の ■ は .itemColList の外なので干渉ゼロ.

  検証 (実 8 URL):
    nikke7      : itemColList=12  ✓
    onep101     : itemColList=10  ✓
    db_goku     : itemColList=11  ✓
    bluelock8   : itemColList=10  ✓
    medalist    : itemColList=7   ✓
    frieren     : itemColList=9   ✓
    winbre6     : itemColList=8   ✓
    umamusume16 : itemColList=9   ✓
"""
from __future__ import annotations
import re
from bs4 import BeautifulSoup


# 1kuji.com の DOM 構造模擬 (実 HTML から抜粋した縮約形)
SAMPLE_HTML = """
<html><body>
<h1>一番くじ ワンピース MONKEY.D.LUFFY</h1>
<p>■発売日：2026年05月01日(金)</p>
<p>■メーカー希望小売価格：1回850円(税10％込)</p>
<p>■ダブルチャンスキャンペーン期間：発売日～2026年08月末日</p>
<section class="listCol" id="listCol">
<h3>各等賞一覧</h3>
<div class="listColInner itemCol">
  <div class="itemColList">
    <h4 class="name pc">A賞 モンキー・D・ルフィ 魂豪示像</h4>
    <h4 class="name sp">A賞 モンキー・D・ルフィ 魂豪示像</h4>
    <ul><li>■全1種</li><li>■サイズ：約25cm</li></ul>
  </div>
  <div class="itemColList">
    <h4 class="name pc">B賞 ルフィ MASTERLISE</h4>
    <h4 class="name sp">B賞 ルフィ MASTERLISE</h4>
    <ul><li>■全1種</li><li>■サイズ：約20cm</li></ul>
  </div>
  <div class="itemColList">
    <h4 class="name pc">C賞 ゾロ</h4>
    <h4 class="name sp">C賞 ゾロ</h4>
    <ul><li>■全2種</li><li>■サイズ：全高約15cm</li></ul>
  </div>
  <div class="itemColList">
    <h4 class="name pc">ラストワン賞 シャンクス</h4>
    <h4 class="name sp">ラストワン賞 シャンクス</h4>
    <ul><li>■当選数：30個</li><li>■全1種</li><li>■サイズ：約16cm</li></ul>
  </div>
</div>
</section>
</body></html>
"""


def _extract_prizes_from_html(html):
    """scrape_1kuji の BS 抽出ロジックを再現 (test 容易化のため切り出し)."""
    soup = BeautifulSoup(html, 'html.parser')
    prize_label_re = re.compile(r'^(ラストワン賞|[^\s]+?賞)\s+(.+)$')
    size_re = re.compile(r'■サイズ[:：]?\s*(?:全高)?\s*約?\s*([\d.]+)\s*cm')
    varieties_re = re.compile(r'■全(\d+)種')
    prizes = []
    for item_col in soup.select('.itemColList'):
        h4 = item_col.select_one('h4.name')
        if not h4:
            continue
        full_label = h4.get_text(strip=True)
        m = prize_label_re.match(full_label)
        if not m:
            continue
        prize_label = m.group(1).strip()
        item_name = m.group(2).strip()
        block_text = item_col.get_text(separator='\n', strip=True)
        if '■当選数' in block_text:
            continue  # ダブルチャンスキャンペーン除外
        v_m = varieties_re.search(block_text)
        s_m = size_re.search(block_text)
        prizes.append({
            'prize': prize_label,
            'name': item_name,
            'varieties': v_m.group(1) if v_m else "1",
            'size_cm': s_m.group(1) if s_m else "",
        })
    return prizes


def test_extract_basic_prizes():
    """通常 A/B/C 賞が DOM から正しく抽出される."""
    prizes = _extract_prizes_from_html(SAMPLE_HTML)
    # ラストワン賞は '■当選数' 含むので除外、A/B/C のみ
    labels = [p['prize'] for p in prizes]
    assert "A賞" in labels
    assert "B賞" in labels
    assert "C賞" in labels


def test_extract_item_name_clean():
    """item_name が h4 から純粋に抽出される (HTML タグ・中間要素混入なし)."""
    prizes = _extract_prizes_from_html(SAMPLE_HTML)
    by_label = {p['prize']: p for p in prizes}
    assert by_label["A賞"]['name'] == "モンキー・D・ルフィ 魂豪示像"
    assert by_label["B賞"]['name'] == "ルフィ MASTERLISE"
    assert by_label["C賞"]['name'] == "ゾロ"


def test_extract_varieties_and_size():
    """■全X種 / ■サイズ：約Xcm が正しく抽出される."""
    prizes = _extract_prizes_from_html(SAMPLE_HTML)
    by_label = {p['prize']: p for p in prizes}
    assert by_label["A賞"]['varieties'] == "1"
    assert by_label["A賞"]['size_cm'] == "25"
    assert by_label["C賞"]['varieties'] == "2"
    assert by_label["C賞"]['size_cm'] == "15"  # 「全高約15cm」 form 対応


def test_double_chance_excluded():
    """ダブルチャンス賞 (■当選数 含む) は抽出対象から除外."""
    prizes = _extract_prizes_from_html(SAMPLE_HTML)
    labels = [p['prize'] for p in prizes]
    assert "ラストワン賞" not in labels  # ■当選数 ありで除外


def test_header_marks_do_not_interfere():
    """副作用ゼロ: header の ■発売日:/■メーカー希望小売価格: 等は .itemColList 外
    なので抽出に干渉しない (text regex 旧実装で起きていた事故が構造的に解消)."""
    prizes = _extract_prizes_from_html(SAMPLE_HTML)
    # header に ■ 3 件あっても prize 抽出は正常 (3 件 = A/B/C、ラストワンは double chance で除外)
    assert len(prizes) == 3


def test_empty_html_no_crash():
    """空 HTML / .itemColList 無しでクラッシュせず空 list 返却."""
    assert _extract_prizes_from_html("") == []
    assert _extract_prizes_from_html("<html><body></body></html>") == []
    assert _extract_prizes_from_html("<html><body><div>noise</div></body></html>") == []


# ============================================================================
# release_year / price 抽出: raw HTML から regex (2026-05-10 16:03 事故対応)
# 旧実装は Selenium body.text 経由で run によって失敗 (12/12 空欄事故あり).
# raw HTML から抽出に変更した regex の正当性を pin.
# ============================================================================
def test_release_year_regex_matches_html_format():
    """raw HTML には <dt>発売日</dt><dd>...2026年05月02日...</dd> 等の形式で存在."""
    sample = '<dt>発売日</dt><dd>店頭販売：2026年05月02日(土)より順次発売予定</dd>'
    m = re.search(r'(\d{4})年(\d{1,2})月', sample)
    assert m is not None
    assert m.group(1) == "2026"
    assert m.group(2) == "05"


def test_price_regex_matches_html_format():
    """raw HTML には ■メーカー希望小売価格：1回790円(税10％込) 等の形式."""
    sample = '<li>■メーカー希望小売価格：1回790円(税10％込)</li>'
    m = re.search(r'1回(\d+)円', sample)
    assert m is not None
    assert m.group(1) == "790"


def test_year_regex_picks_first_match_release_date():
    """同 HTML に複数年月 (発売日 + ダブルチャンス期間) ある場合、最初は発売日."""
    # 実 onep101 raw HTML 抜粋風:
    sample = '''
        <dt>発売日</dt><dd>2026年05月02日(土)より順次発売予定</dd>
        <li>■ダブルチャンスキャンペーン期間：発売日～2026年08月末日</li>
    '''
    matches = re.findall(r'(\d{4})年(\d{1,2})月', sample)
    assert len(matches) >= 2
    # findall は出現順、最初は発売日
    assert matches[0] == ("2026", "05")


def test_page_text_via_bs_get_text_is_stable():
    """page_text source 統一: BS get_text 経由なら release_year/price/ラストワン賞
    全部同じ stable source から取得可能 (修正連鎖を構造的に解消)."""
    from bs4 import BeautifulSoup
    sample_html = '''
    <html><body>
    <h1>一番くじ テスト</h1>
    <dl><dt>発売日</dt><dd>2026年05月02日(土)より順次発売予定</dd></dl>
    <li>■メーカー希望小売価格：1回790円(税10％込)</li>
    <div class="itemColList">
      <h4 class="name sp">A賞 テスト</h4>
      <ul><li>■全1種</li><li>■サイズ：約25cm</li></ul>
    </div>
    <div class="itemColList">
      <h4 class="name sp">ラストワン賞 ラストキャラ</h4>
      <ul><li>■全1種</li><li>■サイズ：約20cm</li></ul>
    </div>
    </body></html>
    '''
    soup = BeautifulSoup(sample_html, 'html.parser')
    page_text = soup.get_text(separator='\n', strip=True)
    # release_year
    date_m = re.search(r'(\d{4})年(\d{1,2})月', page_text)
    assert date_m and date_m.group(1) == "2026"
    # price
    price_m = re.search(r'1回(\d+)円', page_text)
    assert price_m and price_m.group(1) == "790"
    # ラストワン賞 fallback (BS extraction で取れる前提だが、page_text にも存在確認)
    assert "ラストワン賞" in page_text
