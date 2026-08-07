#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G-SHOCK 再仕入れ可否ゲート (Amazon)。

RESTOCK∩G-SHOCK の各型番について、Amazon で「新品が買えるか + 価格」を確認 → 再仕入れ可否。
PSA ゲート(psa_resource_gate)の G-SHOCK 版。G-SHOCK は単チャネル(Amazon)。

技術: Amazon は公開 HTTP API 無し(anti-bot)→ Selenium。amazon_jp.search_amazon(型番→ASIN) +
  /dp ページ価格取得を再利用。価格表示=買える proxy。
id-strict: /dp の title に型番が含まれる事を確認してから採用 (誤マッチ防止、fail-closed)。
  ※新品 vs 中古/マケプレ の厳密判定は別途(stock_detection 原則)。v1 は買box価格=候補。

入力: funnel RESTOCK∩G-SHOCK。出力: 「G-shock再仕入れ」タブ。
"""
from __future__ import annotations

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# amazon_jp (型番→ASIN検索) を越境 read-only import
_MERCARI = r"C:\dev\iMak\iMakMercari"
if _MERCARI not in sys.path:
    sys.path.insert(0, _MERCARI)

# G-SHOCK フル型番: GA-2100FF-8A / DW-6900TU-1A5JF / GBD-200UU-9DR 等
MODEL_RE = re.compile(r"\b([A-Z]{1,4}-[A-Z]?\d{2,4}[A-Z0-9]*-[A-Z0-9]+)\b")
PRICE_RE = re.compile(r"￥\s?([0-9,]{3,})")


def extract_model(title):
    m = MODEL_RE.search(title or "")
    return m.group(1).upper() if m else None


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def verify_match(model, amazon_title):
    """誤マッチ防止: Amazon 商品 title に型番(記号無視)が含まれるか。"""
    return bool(model) and _norm(model) in _norm(amazon_title)


def parse_price(text):
    m = PRICE_RE.search(text or "")
    return int(m.group(1).replace(",", "")) if m else None


def seller_from_text(t):
    """buybox/merchant テキストから販売元名を抽出。"""
    t = t or ""
    m = re.search(r"販売元[\s:：]*\n?\s*([^\n]+)", t)
    if m:
        return m.group(1).strip()
    m = re.search(r"([^\s、。]+)\s*が販売", t)   # "Amazon.co.jp が販売、発送します"
    if m:
        return m.group(1).strip()
    return ""


def is_amazon_seller(buybox_text):
    """販売元が Amazon 自身かを判定 (3rd-party/FBA他社販売を除外)。

    販売元=Amazon → 出荷元も Amazon(新品・Amazon履行)。FBA(出荷元Amazon/販売元他社)は False。
    """
    s = seller_from_text(buybox_text)
    return ("amazon" in s.lower()) or ("アマゾン" in s)


def check_resource(model, driver, max_check=3):
    """型番 → Amazon検索 → /dp で title+価格 → 型番一致を確認 → 再仕入れ可否。

    Returns: {available, price_jpy, asin, url} or {"_error":...}
    """
    import amazon_jp
    from selenium.webdriver.common.by import By
    if not model:
        return {"_error": "empty_model", "available": False, "price_jpy": None}
    try:
        asins = amazon_jp.search_amazon(driver, model, max_results=max_check)
    except Exception as e:
        return {"_error": f"search_error:{type(e).__name__}", "available": False, "price_jpy": None}
    for asin in (asins or [])[:max_check]:
        try:
            driver.get(f"https://www.amazon.co.jp/dp/{asin}")
            time.sleep(3.0)
            title_el = driver.find_elements(By.ID, "productTitle")
            atitle = title_el[0].text if title_el else ""
            if not verify_match(model, atitle):
                continue  # 型番不一致=別商品、skip (id-strict)
            price = None
            for sel in ("#corePrice_feature_div", "span.a-price", "#priceblock_ourprice",
                        "#price", ".a-price .a-offscreen"):
                for e in driver.find_elements(By.CSS_SELECTOR, sel):
                    price = parse_price(e.get_attribute("innerHTML") or e.text)
                    if price:
                        break
                if price:
                    break
            # 販売元/出荷元 (Amazon限定: 3rd-party/FBA他社販売を除外)
            buybox_text = ""
            for sel in ("#merchant-info", "#tabular-buybox", "#fulfillerInfoFeature_feature_div",
                        "#merchantInfoFeature_feature_div", "#offerDisplayFeature_feature_div",
                        "#sellerProfileTriggerId"):
                for e in driver.find_elements(By.CSS_SELECTOR, sel):
                    buybox_text += " " + (e.text or "")
            amazon = is_amazon_seller(buybox_text)
            seller = seller_from_text(buybox_text)
            return {"available": (price is not None) and amazon,
                    "price_jpy": price, "asin": asin,
                    "url": f"https://www.amazon.co.jp/dp/{asin}",
                    "seller": seller, "amazon_seller": amazon}
        except Exception:
            continue
    return {"_error": "not_found", "available": False, "price_jpy": None}


def _load_restock_gshock():
    import csv
    import glob
    import demand_winners as dw
    fdir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "funnel_output"))
    fs = glob.glob(os.path.join(fdir, "funnel_*.csv"))
    if not fs:
        return []
    rows = list(csv.DictReader(open(max(fs, key=os.path.getmtime), encoding="utf-8")))
    return [r for r in rows
            if "RESTOCK" in (r.get("flags") or "").split("|")
            and dw.vein_of(r.get("title", "")) == "G-SHOCK"]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    limit = None
    for a in sys.argv[1:]:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])

    rows = _load_restock_gshock()
    if not rows:
        sys.exit("RESTOCK∩G-SHOCK がありません (先にファネル分析)。")
    if limit:
        rows = rows[:limit]
    print(f"対象 G-SHOCK: {len(rows)}枚 (Amazon再仕入れ確認)")

    import undetected_chromedriver as uc
    import mercari_psa_resource as _mp   # _chrome_major(): driver/Chrome 版不一致回避
    # ★2026-07-24 PSA と同じ資産化を横展開: End候補/在庫不明を待ち台帳に蓄積し毎回再チェック
    # (出品で得た「再仕入れ価値」を世代でリセットしない)。待ち台帳の未解決を今回チェックに合流。
    _WAIT_TAB = "G-shock再仕入れ待ち"
    try:
        import psa_restock_wait as _prw
        from sheet_io import read_tab as _rt
        _wled0 = _prw.ledger_from_rows(_rt(_WAIT_TAB))
        _have = {_mp._ebay_item_id(r.get("ebay_url", "") or "") for r in rows}
        _merged = 0
        for t in _prw.recheck_targets(_wled0):
            if t.get("itemID") and t["itemID"] not in _have:
                rows.append({"title": t.get("title", ""), "ebay_url": t.get("ebay_url", "")})
                _merged += 1
        if _merged:
            print(f"♻ {_WAIT_TAB}から {_merged}件を再チェックに合流(蓄積分・供給は動的)")
    except Exception as _e:
        print(f"⚠ {_WAIT_TAB}読込skip ({type(_e).__name__}: {_e})")
    _mp._quiet_chromedriver()      # chromedriver の黒窓を出さない (2026-07-30)
    opts = uc.ChromeOptions()
    opts.add_argument("--headless=new"); opts.add_argument("--no-sandbox")
    opts.add_argument("--lang=ja-JP"); opts.add_argument("--window-size=1280,1000")
    _maj = _mp._chrome_major()
    driver = uc.Chrome(options=opts, version_main=_maj) if _maj else uc.Chrome(options=opts)
    out_rows = [["型番", "title", "再仕入れ可否", "Amazon¥", "販売元", "ASIN", "AmazonURL", "ebay_url"]]
    go = 0
    _resourceable_ids = set()   # 再仕入れ可 itemID → 待ち台帳で復活可に
    _end_candidates = []        # 供給なし確定(not_found/3rd-party) → End候補
    _held_list = []             # Amazon到達不可(search_error)=在庫不明 → 蓄積して再取得
    try:
        driver.set_page_load_timeout(50)
        for i, r in enumerate(rows):
            model = extract_model(r.get("title", "") or "")
            if not model:
                print(f"  [{i+1}/{len(rows)}] (型番抽出不可) skip", flush=True)
                out_rows.append(["", (r.get("title") or "")[:60], "判定不可", "", "", "", "", r.get("ebay_url", "")])
                continue
            res = check_resource(model, driver)
            ok = res.get("available")
            if ok:
                go += 1
            if res.get("_error"):
                tag = "Amazon未登録"
            elif res.get("price_jpy") and not res.get("amazon_seller"):
                tag = f"3rd-party(販売元:{res.get('seller','?')}) ¥{res.get('price_jpy')} →除外"
            elif ok:
                tag = f"¥{res.get('price_jpy')} (Amazon販売)"
            else:
                tag = "在庫なし✕"
            print(f"  [{i+1}/{len(rows)}] {model}: {tag}", flush=True)
            out_rows.append([model, (r.get("title") or "")[:60],
                             "再仕入れ可◎" if ok else "不能✕(End候補)",
                             res.get("price_jpy") or "", res.get("seller", ""),
                             res.get("asin", ""), res.get("url", ""), r.get("ebay_url", "")])
            # 待ち台帳向け分類: 可 / 在庫不明(Amazon到達不可=search_error) / 供給なし確定
            _iid = _mp._ebay_item_id(r.get("ebay_url", "") or "")
            if not _iid:
                continue
            _rec = {"itemID": _iid, "key": "", "card_no": model,
                    "title": (r.get("title") or "")[:90], "ebay_url": r.get("ebay_url", "")}
            if ok:
                _resourceable_ids.add(_iid)
            elif str(res.get("_error", "")).startswith("search_error"):
                _held_list.append(_rec)      # Amazon到達不可=取れなかった → 在庫不明(End候補にしない)
            else:
                _end_candidates.append(_rec)  # not_found / 3rd-party = 供給なし確定 → End候補
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    print(f"\n再仕入れ可: {go}/{len(rows)}  不能(End候補): {len(rows)-go}")
    try:
        from sheet_io import write_rows_to_tab, MAINT_URL
        write_rows_to_tab("G-shock再仕入れ", out_rows)
        print(f"📊 「G-shock再仕入れ」タブ更新: {len(out_rows)-1}件 → {MAINT_URL}")
    except Exception as e:
        print(f"⚠ スプシ更新失敗: {type(e).__name__}: {e}")

    # ★資産化: End候補/在庫不明を待ち台帳に蓄積(消さず毎回再チェック)、供給戻りは復活可に。
    try:
        import psa_restock_wait as _prw, datetime as _dt
        from sheet_io import read_tab as _rt, write_rows_to_tab as _wt
        _today = _dt.date.today().isoformat()
        _prev = _prw.ledger_from_rows(_rt(_WAIT_TAB))
        _wled, _wst = _prw.reconcile(_prev, _end_candidates, _resourceable_ids, _today,
                                     held_candidates=_held_list)
        _wt(_WAIT_TAB, _prw.to_tab_rows(_wled))
        print(f"♻ {_WAIT_TAB}: 新規{_wst['new']} 継続{_wst['still_waiting']} 復活{_wst['revived']} "
              f"在庫不明{_wst.get('unknown', 0)} / 待ち計{_wst['total_wait']}")
        if _wst["revived"]:
            print(f"   → 復活可{_wst['revived']}件(供給戻り)= RESTOCK対象。タブ「{_WAIT_TAB}」参照")
    except Exception as e:
        print(f"⚠ {_WAIT_TAB}更新skip ({type(e).__name__}: {e})")


if __name__ == "__main__":
    main()
