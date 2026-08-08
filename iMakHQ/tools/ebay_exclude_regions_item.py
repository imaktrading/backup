"""発送除外国を **listing 1件ずつ** に追加する (2026-08-08 / plan B)。

なぜ道具が2本あるのか:
    `ebay_exclude_regions.py` (ポリシー側) は **ミラーには効かない**。
    2026-08-02 の実測で、eBay は「その市場の自国向け除外」を **PUT は受け付けるが保存しない**
    (`EBAY_DE --add DE,AT` = API 成功 43/43 に対し読み直すと 18/43、`EBAY_GB --add IE` は 1/12)。
    ミラーの販売対象国ゲートは **listing 側の `ExcludeShipToLocation`** にあるので、
    そこを item ごとに直すのがこちら。

    eBaymag 側でミラーを止めても listing は残る (2026-08-03 に停止 → 8/8 実測で
    ebay.de が 372件 生存、うち DE 除外済は 72件だけ)。**mag 停止だけでは塞がらない。**

安全側の作り (`ebay_exclude_regions.py` と同じ思想):
    - 実行前に **GetItem の ShippingDetails を全文スナップショット** (戻せない変更をしない)
    - **追加のみ**。既存の除外・送料・サービスは持ち回して復元する
    - `--dry-run` (既定) → `--limit 1` で1件試す → 全件、の順で流す
    - 1件ごとに **revise 後に読み直して検証**。送りっぱなしにしない
      (ポリシー側は「成功」と言って保存していなかった。同じ罠を踏まないため)
    - 失敗は silent drop せず件数と ItemID を出し、1件でも残れば exit 1

使い方:
    python ebay_exclude_regions_item.py --target de                    # dry-run
    python ebay_exclude_regions_item.py --target de --apply --limit 1  # まず1件
    python ebay_exclude_regions_item.py --target de --apply            # 全件
    python ebay_exclude_regions_item.py --target uk --verify           # 実状態だけ確認
    python ebay_exclude_regions_item.py --target de --rollback         # スナップショットへ戻す
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\dev\iMak")
API_DIR = ROOT / "iMakeBayAPI"
sys.path.insert(0, str(API_DIR))
try:
    import dns_cache  # noqa: F401  ★これが無いと getaddrinfo failed になる (この環境の作法)
except Exception:
    pass
import fix_de_speedpak_shipping as fx  # noqa: E402  (token/refresh/post を再利用)

# ミラーの単位。ドメインで判定する (`Site` は US 固定で当てにならない)
TARGETS = {
    # key: (ViewItemURL のドメイン, Trading API の SiteID, 追加する除外コード)
    "de": {"domain": "//www.ebay.de/", "site": "77", "add": ["DE", "AT"],
           "why": "2026-08-12 から DE 向けは授権代理人が必須 (無いと販売不可・罰金最大 €200,000)"},
    "uk": {"domain": "//www.ebay.co.uk/", "site": "3", "add": ["IE"],
           "why": "IE は EU。UK 本国 (GB) は残す"},
}
SNAP_DIR = API_DIR


def snap_path(target: str) -> Path:
    return SNAP_DIR / f"item_exclude_snapshot_{target}.json"


def enumerate_mirror(tok: str, domain: str) -> tuple[list[str], int]:
    """ViewItemURL のドメインで active listing を絞る。→ (該当ID, 見た全item数)

    ★ページ打ち切りは「そのページの **全 item 数**」で判定する。
      絞り込み後の件数で break すると、対象0件のページで止まって残りを全部見落とす
      (2026-08-08 に offer_calc で踏んだのと同型)。

    ★全item数も返すのは **fail-OPEN 防止**のため。API が失敗して空が返った時に
      「該当0件 = もう塞がっている」と読むと、**実際は開いているのに完了扱い**になる
      (2026-08-08 に実際にやった: 372件あるのに『active 0件・作業なし ✅』と報告した)。
      呼出側は「全item数が0 = 判定不能」として扱うこと。
    """
    out: list[str] = []
    seen = 0
    for n in range(1, 60):
        inner = ("<ActiveList><Include>true</Include><Pagination>"
                 f"<EntriesPerPage>200</EntriesPerPage><PageNumber>{n}</PageNumber>"
                 "</Pagination></ActiveList>")
        t = fx.post("GetMyeBaySelling", inner, tok)
        al = re.search(r"<ActiveList>(.*?)</ActiveList>", t, re.S)
        if not al:
            break
        items = re.findall(r"<Item>(.*?)</Item>", al.group(1), re.S)
        if not items:
            break
        for it in items:
            seen += 1
            vu = re.search(r"<ViewItemURL>(.*?)</ViewItemURL>", it)
            iid = re.search(r"<ItemID>(\d+)</ItemID>", it)
            if vu and iid and domain in vu.group(1).replace("&amp;", "&"):
                out.append(iid.group(1))
        tp = re.search(r"<ActiveList>.*?<PaginationResult>.*?"
                       r"<TotalNumberOfPages>(\d+)</TotalNumberOfPages>", t, re.S)
        if tp and n >= int(tp.group(1)):
            break
    return out, seen


def get_shipping(iid: str, tok: str, site: str) -> dict | None:
    """GetItem から ShippingDetails を読む。revise で送り返せる形に絞って返す。"""
    x = fx.post("GetItem", f"<ItemID>{iid}</ItemID><DetailLevel>ReturnAll</DetailLevel>",
                tok, site=site)
    if "<Ack>Failure</Ack>" in x or "<ShippingDetails>" not in x:
        return None
    sd = x[x.find("<ShippingDetails>"):x.find("</ShippingDetails>")]

    def opts(tag: str) -> list[dict]:
        blocks = re.findall(rf"<{tag}>(.*?)</{tag}>", sd, re.S)
        got = []
        for b in blocks:
            svc = re.search(r"<ShippingService>(.*?)</ShippingService>", b)
            cost = re.search(r'<ShippingServiceCost currencyID="(\w+)">([\d.]+)<', b)
            pri = re.search(r"<ShippingServicePriority>(\d+)</ShippingServicePriority>", b)
            got.append({"svc": svc.group(1) if svc else None,
                        "cur": cost.group(1) if cost else None,
                        "cost": cost.group(2) if cost else None,
                        "pri": pri.group(1) if pri else "1",
                        "loc": re.findall(r"<ShipToLocation>(.*?)</ShipToLocation>", b)})
        return got

    return {
        "type": (re.search(r"<ShippingType>(.*?)</ShippingType>", sd) or [None, "Flat"])[1]
        if re.search(r"<ShippingType>(.*?)</ShippingType>", sd) else "Flat",
        "dom": opts("ShippingServiceOptions"),
        "intl": opts("InternationalShippingServiceOption"),
        "exclude": sorted(set(re.findall(r"<ExcludeShipToLocation>(.*?)</ExcludeShipToLocation>", sd))),
        "shipto": re.findall(r"<ShipToLocations>(.*?)</ShipToLocations>", sd),
    }


def build_sd(cur: dict, exclude: list[str]) -> str:
    """既存の送料・サービスをそのまま持ち回し、除外だけ差し替えた ShippingDetails を組む。

    ★除外だけ送ると eBay が **送料サービスを消す**ことがあるので、必ず全部入れ直す。
    """
    parts = [f"<ShippingType>{cur['type']}</ShippingType>"]
    for o in cur["dom"]:
        if not o["svc"]:
            continue
        parts.append("<ShippingServiceOptions>"
                     f"<ShippingService>{o['svc']}</ShippingService>"
                     + (f'<ShippingServiceCost currencyID="{o["cur"]}">{o["cost"]}</ShippingServiceCost>'
                        if o["cost"] is not None else "")
                     + f"<ShippingServicePriority>{o['pri']}</ShippingServicePriority>"
                     "</ShippingServiceOptions>")
    for o in cur["intl"]:
        if not o["svc"]:
            continue
        parts.append("<InternationalShippingServiceOption>"
                     f"<ShippingService>{o['svc']}</ShippingService>"
                     + (f'<ShippingServiceCost currencyID="{o["cur"]}">{o["cost"]}</ShippingServiceCost>'
                        if o["cost"] is not None else "")
                     + f"<ShippingServicePriority>{o['pri']}</ShippingServicePriority>"
                     + "".join(f"<ShipToLocation>{L}</ShipToLocation>" for L in o["loc"])
                     + "</InternationalShippingServiceOption>")
    for code in exclude:
        parts.append(f"<ExcludeShipToLocation>{code}</ExcludeShipToLocation>")
    return "<ShippingDetails>" + "".join(parts) + "</ShippingDetails>"


def revise(iid: str, sd_xml: str, tok: str, site: str) -> tuple[bool, str, str]:
    """1件 revise。トークン失効なら refresh して1回だけ再試行。戻り値 (ok, tok, err)。"""
    for attempt in (1, 2):
        resp = fx.post("ReviseFixedPriceItem",
                       f"<Item><ItemID>{iid}</ItemID>{sd_xml}</Item>", tok, site=site)
        if "<Ack>Success</Ack>" in resp or "<Ack>Warning</Ack>" in resp:
            return True, tok, ""
        if "expired" in resp.lower() and attempt == 1:
            fx.refresh()
            tok = fx.token()
            continue
        msg = re.search(r"<LongMessage>(.*?)</LongMessage>", resp, re.S)
        return False, tok, (msg.group(1) if msg else resp[:200])
    return False, tok, "retry 尽きた"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=sorted(TARGETS), required=True)
    ap.add_argument("--apply", action="store_true", help="実際に revise する (既定は dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="先頭 N 件だけ (0 = 全件)")
    ap.add_argument("--verify", action="store_true", help="実状態を読むだけ")
    ap.add_argument("--rollback", action="store_true", help="スナップショットの除外セットに戻す")
    a = ap.parse_args()

    t = TARGETS[a.target]
    add, site = t["add"], t["site"]
    tok = fx.token()

    print(f"=== {a.target.upper()} ミラー ({t['domain']}) / 追加する除外 {','.join(add)} ===")
    print(f"    理由: {t['why']}")
    ids, seen = enumerate_mirror(tok, t["domain"])
    print(f"    出品全体 {seen} 件 / うちミラー {len(ids)} 件")
    # ★fail-OPEN 防止。全体が0件 = API 側の失敗 (token 失効・レート上限・通信断) であって
    #   「ミラーが無くなった」ではない。ここを ✅ で返すと **開いているのに完了扱い**になる。
    if seen == 0:
        print("  ❌ 出品を1件も列挙できていない = **判定不能**。"
              "token 失効 / API レート上限 / 通信断を疑うこと。0件を『片付いた』と読まない")
        return 1
    if not ids:
        print("  ✅ ミラーの active が 0 件 (出品自体は列挙できている)。作業なし")
        return 0

    if a.rollback:
        snap = json.loads(snap_path(a.target).read_text(encoding="utf-8"))
        ok = ng = 0
        for iid, cur in snap["items"].items():
            sd = build_sd(cur, cur["exclude"])
            good, tok, err = revise(iid, sd, tok, site)
            if good:
                ok += 1
            else:
                ng += 1
                print(f"  ❌ {iid} {err}")
        print(f"\nrollback: 成功 {ok} / 失敗 {ng}")
        return 1 if ng else 0

    # 現状を読む (= スナップショットでもある)
    print("\n=== 現状を GetItem で読む ===")
    cur_by_id: dict[str, dict] = {}
    need: list[str] = []
    err = 0
    for i, iid in enumerate(ids, 1):
        cur = get_shipping(iid, tok, site)
        if cur is None:
            err += 1
            print(f"  ⚠️ {iid} GetItem 失敗 — **未処理として残る**")
            continue
        cur_by_id[iid] = cur
        if not set(add) <= set(cur["exclude"]):
            need.append(iid)
        if i % 100 == 0:
            print(f"    {i}/{len(ids)} …", flush=True)
    done = len(cur_by_id) - len(need)
    print(f"  既に除外済 {done} 件 / **未除外 {len(need)} 件** / 読取失敗 {err} 件")

    if a.verify:
        return 1 if (need or err) else 0
    if not need:
        print("  ✅ 全件に入っている")
        return 1 if err else 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    sp = snap_path(a.target)
    sp.write_text(json.dumps({"stamp": stamp, "add": add, "items": cur_by_id},
                             ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  🗄 スナップショット: {sp.name} ({len(cur_by_id)} 件)")

    todo = need[:a.limit] if a.limit else need
    if not a.apply:
        print(f"\n(dry-run) 対象 {len(todo)} 件。--apply を付けると実行します")
        for iid in todo[:3]:
            c = cur_by_id[iid]
            print(f"   例) {iid} 除外{len(c['exclude'])}件 → +{[x for x in add if x not in c['exclude']]}")
        return 0

    print(f"\n=== revise {len(todo)} 件 ===")
    ok = ng = 0
    failed: list[str] = []
    for i, iid in enumerate(todo, 1):
        cur = cur_by_id[iid]
        sd = build_sd(cur, sorted(set(cur["exclude"]) | set(add)))
        good, tok, msg = revise(iid, sd, tok, site)
        if good:
            ok += 1
        else:
            ng += 1
            failed.append(iid)
            print(f"  ❌ {iid} {msg}")
        if i % 50 == 0:
            print(f"    {i}/{len(todo)} (成功 {ok} / 失敗 {ng})", flush=True)

    # ★送りっぱなしにしない。読み直して実状態を確認する
    print(f"\n=== 検証: {len(todo)} 件を読み直す ===")
    bad = []
    for iid in todo:
        again = get_shipping(iid, tok, site)
        if again is None or not set(add) <= set(again["exclude"]):
            bad.append(iid)
        elif not again["dom"] and cur_by_id[iid]["dom"]:
            bad.append(iid)  # 送料サービスが消えていたら失敗扱い
    print(f"  revise 応答: 成功 {ok} / 失敗 {ng}")
    if bad:
        print(f"  ❌ **反映されていない {len(bad)} 件** → {bad[:5]}")
        print("     = そこは まだ買える。ポリシー側と同じ『成功と言って保存しない』挙動の可能性。"
              "原因を潰して再実行すること")
        return 1
    print(f"  ✅ 全 {len(todo)} 件に {','.join(add)} が入り、送料サービスも残っている")
    if failed or err:
        print(f"  ⚠️ ただし revise 失敗 {len(failed)} 件 / 読取失敗 {err} 件が**未処理**")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
