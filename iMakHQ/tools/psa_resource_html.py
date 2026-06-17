# -*- coding: utf-8 -*-
"""PSA再仕入れ 目視ビューア生成。

仕入候補(main)+ 補URL を「正カード(catalog画像)」と横並びにした HTML を出力。
番号一致では弾けない 変種取り違え(CHR/VMAX・JP/Asia 等)を、買う前に目視で確認する。

- 正カード画像  : catalog の canonical 画像(card_meta_for_key の image)
- Mercari 候補  : item m<id> → 静的CDN画像(scraping不要)
- SNKRDUNK 候補 : ページの og:image(取得時に1回 fetch、失敗時はリンクのみ)

I/O は fetch_snkr_image / build_html のみ。build_html は純粋(画像URLを受け取って描画)。
"""
import html as _html
import re
import time
import urllib.request


def mercari_image_url(url):
    """https://jp.mercari.com/item/m<id> → 静的CDN の1枚目画像URL(scraping不要)。"""
    m = re.search(r"\b(m\d{9,})\b", url or "")
    if not m:
        return ""
    return f"https://static.mercdn.net/item/detail/orig/photos/{m.group(1)}_1.jpg"


_SNKR_CACHE = {}


def fetch_snkr_image(url, retries=3):
    """SNKRDUNK 商品ページの og:image を取得(キャッシュ + DNSリトライ)。失敗は ''。"""
    if not url or "snkrdunk.com" not in url:
        return ""
    if url in _SNKR_CACHE:
        return _SNKR_CACHE[url]
    img = ""
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            htmltext = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
            mm = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', htmltext)
            if mm:
                img = mm.group(1)
            break
        except Exception as e:
            if "getaddrinfo" in str(e) and a < retries - 1:
                time.sleep(3); continue
            break
    _SNKR_CACHE[url] = img
    return img


def candidate_image(channel, url):
    if channel == "mercari" or "mercari.com" in (url or ""):
        return mercari_image_url(url)
    if "snkrdunk.com" in (url or ""):
        return fetch_snkr_image(url)
    return ""


def _s(v):
    """list/tuple は ' / ' 連結、None は空、それ以外 str(catalog hint が list で来るため)。"""
    if isinstance(v, (list, tuple)):
        return " / ".join(str(x) for x in v if x not in (None, ""))
    return "" if v is None else str(v)


def build_html(items, out_path):
    """items: [{title, ref_image, ref_label, ng(bool), candidates:[{channel,url,price,image,is_main}]}]
    → out_path に HTML 書込。返り = out_path。"""
    css = """
    body{font-family:'Segoe UI',Meiryo,sans-serif;margin:0;background:#f4f4f4;font-size:15px}
    h1{background:#333;color:#fff;margin:0;padding:12px 16px;font-size:18px}
    .row{background:#fff;margin:10px;border:1px solid #ccc;border-radius:6px;overflow:hidden}
    .row.ng{opacity:.55}
    .head{padding:8px 12px;background:#e8e8e8;font-weight:bold;border-bottom:1px solid #ddd}
    .body{display:flex;gap:12px;padding:12px;align-items:flex-start;flex-wrap:wrap}
    .ref{flex:0 0 220px;text-align:center}
    .ref img{max-width:200px;max-height:200px;border:2px solid #2a7}
    .ref .lbl{font-size:13px;color:#060;margin-top:4px;word-break:break-word}
    .cands{display:flex;gap:8px;flex-wrap:wrap;flex:1}
    .cand{width:150px;text-align:center;border:1px solid #ddd;border-radius:4px;padding:6px;background:#fafafa}
    .cand.main{border-color:#c50;border-width:2px;background:#fff7f0}
    .cand img{max-width:138px;max-height:138px}
    .cand .meta{font-size:12px;margin-top:3px}
    .cand a{font-size:12px;color:#06c;text-decoration:none}
    .ch{display:inline-block;font-size:11px;padding:1px 5px;border-radius:3px;background:#ddd;margin-bottom:3px}
    .ch.mercari{background:#fde}.ch.snkrdunk{background:#def}
    .noimg{width:138px;height:138px;display:flex;align-items:center;justify-content:center;color:#999;font-size:12px;border:1px dashed #ccc}
    """
    parts = [f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>PSA再仕入れ 目視</title><style>{css}</style></head><body>"]
    parts.append(f"<h1>PSA再仕入れ 目視ビューア — {len(items)}件(左=仕入れたい正カード / 右=候補。変種が同じか確認)</h1>")
    for it in items:
        cls = "row ng" if it.get("ng") else "row"
        parts.append(f"<div class='{cls}'>")
        parts.append(f"<div class='head'>{_html.escape(_s(it.get('title')))}</div>")
        parts.append("<div class='body'>")
        # 正カード
        ref_img = _s(it.get("ref_image"))
        img_tag = f"<img src='{_html.escape(ref_img)}' loading='lazy'>" if ref_img else "<div class='noimg'>正画像なし(KEY未解決)</div>"
        parts.append(f"<div class='ref'>{img_tag}<div class='lbl'>{_html.escape(_s(it.get('ref_label')) or '正カード')}</div></div>")
        # 候補
        parts.append("<div class='cands'>")
        cands = it.get("candidates") or []
        if not cands:
            parts.append("<div class='noimg'>候補なし(End候補)</div>")
        for cd in cands:
            ch = cd.get("channel", "")
            cimg = cd.get("image") or ""
            tag = f"<img src='{_html.escape(cimg)}' loading='lazy'>" if cimg else "<div class='noimg'>画像取得不可</div>"
            price = cd.get("price")
            pstr = f"¥{price:,}" if isinstance(price, int) else (f"¥{price}" if price else "")
            main = " main" if cd.get("is_main") else ""
            parts.append(
                f"<div class='cand{main}'><span class='ch {ch}'>{_html.escape(ch)}{' ★最安' if cd.get('is_main') else ''}</span>"
                f"{tag}<div class='meta'>{pstr}</div><a href='{_html.escape(cd.get('url',''))}' target='_blank'>開く</a></div>"
            )
        parts.append("</div></div></div>")
    parts.append("</body></html>")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    return out_path
