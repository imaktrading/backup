#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カタログの alias 寄せでレアリティが変わった出品中の PSA を、カタログの値に合わせて Revise する (2026-10-06)。

ADV 依頼・ユーザー GO (2026-10-06「うん」)。対象は対応表で「レアリティが変わる」組の出品中 (US 本体のみ)。
- 今の Item Specifics を GetItem で **全部** 読み、Rarity と Features だけ差し替えて送る
  (FileExchange/Revise は丸ごと入れ替え。2026-09-03 に1項目だけ送って85件全滅した)
- タイトルはカタログから作り直した物 (出品くんと同じ build_title_from_fields)
- 送った後に GetItem で読み直して、送った値になったかを確かめる

    python rarity_alias_revise.py <itemID> [<itemID> ...]           # 計画だけ
    python rarity_alias_revise.py <itemID> ... --write              # 送る
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "iMakTCG")))
import live_set_revise as L  # noqa: E402
import sheet_io as S  # noqa: E402


def merged_aspects(current, new_values):
    """今の項目 + 差し替える項目 → 送る項目 (純関数)。空の新値では上書きしない。"""
    out = {k: list(v) for k, v in (current or {}).items() if v}
    for k, v in (new_values or {}).items():
        if v:
            out[k] = [v]
    return out


def item_xml(item_id, title, aspects):
    nv = "".join(f"<NameValueList><Name>{L._esc(n)}</Name>"
                 + "".join(f"<Value>{L._esc(x)}</Value>" for x in vals) + "</NameValueList>"
                 for n, vals in aspects.items())
    t = f"<Title>{L._esc(title)}</Title>" if title else ""
    return f"<Item><ItemID>{item_id}</ItemID>{t}<ItemSpecifics>{nv}</ItemSpecifics></Item>"


def _title_now(iid):
    import requests
    x = L.decode_xml(requests.post(L.EP, data=(
        '<?xml version="1.0" encoding="utf-8"?><GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f"<ItemID>{iid}</ItemID></GetItemRequest>").encode(), headers=L._oauth_headers("GetItem"), timeout=40).content)
    L._record_call("GetItem")
    m = re.search(r"<Title>(.*?)</Title>", x, re.S)
    site = re.search(r"<Site>(.*?)</Site>", x)
    return (L.norm(m.group(1)) if m else ""), (site.group(1) if site else "")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    import tcg_listing_fields as T
    write = "--write" in argv
    ids = [a for a in argv if a.isdigit()]
    rows = S._product_ws().get_all_values()
    by = {(r[1].strip() if len(r) > 1 else ""): r for r in rows[1:]}
    ok = ng = 0
    for iid in ids:
        r = by.get(iid)
        if not r:
            print(f"✗ {iid}: シートに無い → 送らない"); ng += 1; continue
        key, cert = r[S.PRODUCT_COL_KEY].strip(), r[S.PRODUCT_COL_CERT].strip()
        f, err = T.build_listing_fields(cert, "One Piece TCG", forced_card_id=key.split(":")[-1])
        if not f:
            print(f"✗ {iid}: カタログから作れない ({err}) → 送らない"); ng += 1; continue
        cur = L.fetch_aspects(iid)
        title_now, site = _title_now(iid)
        if not cur or site != "US":
            print(f"✗ {iid}: 今の項目が読めない / US 以外 ({site}) → 送らない"); ng += 1; continue
        new = {"Rarity": f.get("C:Rarity", ""), "Features": (f.get("C:Features") or "").split("|")[0].strip()}
        title = T.build_title_from_fields(f).strip()
        asp = merged_aspects(cur, new)
        print(f"■ {iid} {key}\n   Title {title_now}\n      → {title}\n   Rarity {cur.get('Rarity')} → {new['Rarity']} / "
              f"Features {cur.get('Features')} → {new['Features']} / 項目 {len(cur)}→{len(asp)}")
        if not write:
            continue
        import fix_de_speedpak_shipping as fx
        resp = fx.post("ReviseFixedPriceItem", item_xml(iid, title, asp), fx.token(), site="0")
        if not ("<Ack>Success</Ack>" in resp or "<Ack>Warning</Ack>" in resp):
            m = re.search(r"<LongMessage>(.*?)</LongMessage>", resp, re.S)
            print(f"   ✗ 失敗: {m.group(1) if m else resp[:200]}"); ng += 1; continue
        after = L.fetch_aspects(iid) or {}
        t_after, _s = _title_now(iid)
        good = (after.get("Rarity") == [new["Rarity"]] and (not new["Features"] or after.get("Features") == [new["Features"]])
                and len(after) >= len(cur) and t_after == title)
        print(f"   {'✅' if good else '⚠️要対応'} 読み直し: Rarity {after.get('Rarity')} / Features {after.get('Features')} / "
              f"項目 {len(after)} / Title {'一致' if t_after == title else t_after}")
        ok += good
        ng += not good
    print(f"結果: OK {ok} / NG {ng}" if write else "(送っていない。--write で送る)")
    return 0 if not ng else 1


if __name__ == "__main__":
    sys.exit(main())
