#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B: CULL(在庫切れ&需要皆無) 段階的 出品停止 End CSV 生成。

CULL = qty=0 ∩ 一度も売れず watcher も付かず。掲載しても無害(qty=0=購入不可)だが、
整理 + 誤って qty を戻して売れる事故の予防として段階的に End する。

安全策 (2026-06-05 ユーザー合意):
  1. age>=21日 の行のみ (NEW_WAIT補正: 出品から時間不足の良品を巻き込まない)。
     age 不明(0)は fail-closed で対象外 (判定不能を破壊側に倒さない)。
  2. $100未満は対象外 (枠は金額で詰まっており、安い出品を落としても効かない)
  3. CAP=200件/回 (burst禁止: 1755件一括 END はしない。2026-08-23 に 50→200)。
  3. 自動アップ無し (End CSV を生成するのみ。eBay FileExchange へは人が手動アップ)。
  並び: age 降順 (最も長く需要0=最も確実に dead を先に) → 同 age は価格昇順 (損失小を先に)。

入力 : ../funnel_output/funnel_*.csv (CULL flag, age_days)
出力 : End CSV → C:/dev/iMak_data/revise/cull_end_YYYYMMDD.csv
       確認用一覧 → デスクトップ CULL出品停止候補_YYYYMMDD.csv
"""
import collections
import csv
import datetime
import glob
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
FUNNEL_DIR = os.path.normpath(os.path.join(_HERE, "..", "funnel_output"))
DESK = r"C:\Users\imax2\OneDrive\デスクトップ"
END_DIR = r"C:\dev\iMak_data\revise"

# 1回あたりの上限 (burst禁止)。
# ★2026-08-23 ユーザー指示で 50 → 200。理由: eBay 公式のとおり **月末時点で生きている出品は
#   翌月の枠にも計上される** ので、8/31 までに CULL を落とすかどうかで9月の出発点が変わる。
#   残り約1,800件を8日で処理するには 50/回 では間に合わない (36回)。
#   誤取下げの守りは件数と独立: 毎回 eBay の実在庫を見て、復活していた行を除外する
#   (2026-08-23 の1回目は 50件中 11件が復活で除外された)。
CAP = 200
# ★2026-08-31 ユーザー指示で 14 → 1。理由: CULL フラグ自体が「在庫0 かつ 表示/クリック/
#   販売が生涯ゼロ」で決まり (listing_funnel.classify)、年齢は見ていない。14日待ちは
#   「新規=まだ表示され始めていないだけかも」という懸念 (NEW_WAIT補正) のための別レイヤー
#   の安全マージンだったが、**在庫0の間は eBay 側が露出を抑制する**ので、待っても表示は
#   増えない (= 待つ理由が無い)。RESTOCK にも回らず(需要ゼロ)、補URLの対象にもならない
#   (需要ゼロなので探索対象に上がらない) = 何も手当てが無いまま居座るだけなので、
#   落とす方が実態に合う。
#   age_days=0 は「不明」の sentinel (`_i()` 参照) なので 0 は除外したまま維持する
#   (fail-closed。判定不能を破壊的動作に倒さない)。
MIN_AGE = 1      # これ未満(=0=年齢不明)は対象外 (fail-closed)。既知の若さでは待たない

# ★2026-08-24 ユーザー指示で $100 に設定 → 2026-08-31 に撤廃 (0に)。
#   元の理由: 枠は金額で詰まっており (点数は半分以上 余っている)、安い出品を落としても
#   「枠を空ける」目的には効かない (実測: $100 で切ると件数は 1,449→1,203 に減るのに、
#   金額は $356,660→$339,453 とほぼ落ちない)。
#   ★2026-08-31 ユーザー指摘: これは「枠を空けたいから安い物は後回し」の基準であって、
#   在庫0×需要ゼロ (CULLフラグ) で **何も手当てが無いまま居座るだけの出品**には無関係。
#   待つ理由が無いので、待たせない (MIN_AGE を 14→1 にした時と同じ理屈)。
#   ★この階層はもう安い物を落とせる (shelf_evict の Tier① は元々価格を見ていない。
#   両方から拾われるようになるだけで、判定が割れるわけではない)。
MIN_PRICE = 0.0

# ★2026-08-24 ユーザー指示: **US の出品だけを対象にする**。
#   UK / AU / CA は **eBaymag が US の親出品から作るミラー**で、こちらの持ち物ではない
#   (`ApplicationData=ebaymag.com-...` / SKU も eBaymag の内部番号でシートに存在しない)。
#   ミラーを直接落としても、親が生きていれば mag がまた作る = 意味がない。
#   親 (US) を落とせばミラーは付いてくる。
#   ★これは 8/24 まで抜けていた。実測 1,408件のうち **643件がミラー** だった
#   (CA 246 / AU 241 / UK 156)。隣の RESTOCK は 063b626 で US 限定済みだったが、
#   CULL には入っていなかった。
TARGET_SITE = "US"

# relist_from_funnel / seller_hub_relist と統一
END_HEADER = ["*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)", "ItemID", "EndCode"]
END_CODE = "OtherListingError"


def _i(v):
    try:
        return int(float(str(v).strip()))
    except (ValueError, TypeError):
        return 0


def _f(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return 0.0


# ★2026-08-24: 落とした itemID を憶える。itemID は一度終了したら二度と復活しないので、
#   永久に候補から外してよい。憶えないと、静的な funnel CSV の上位を済みが占領し続け、
#   毎回ほぼ空振りする (実測: 200件選んで 158件が済み、実際に進んだのは 37件)。
#   これがあると **レポートを取り直さなくても押すたびに次の200件**が出る。
DONE_FILE = os.path.join(END_DIR, "cull_done_item_ids.txt")


def load_done():
    """これまでに落とした itemID (読めなければ空)。"""
    try:
        with io.open(DONE_FILE, encoding="utf-8") as f:
            return {ln.strip() for ln in f if ln.strip()}
    except OSError:
        return set()


def remember_done(ids):
    """落とした分を追記する。書けなくても本処理は止めないが黙らない。"""
    ids = [str(i).strip() for i in ids if str(i).strip()]
    if not ids:
        return
    try:
        os.makedirs(os.path.dirname(DONE_FILE), exist_ok=True)
        with io.open(DONE_FILE, "a", encoding="utf-8") as f:
            for i in ids:
                f.write(i + chr(10))
    except OSError as e:
        print(f"  ⚠ 済みリストに書けませんでした (次回また候補に出ます): {e}")


def listed_this_month(row, today=None):
    """その出品を **今月** 出したか (純関数, test可)。

    当月の枠が戻るのは今月出品した分だけなので、そこを先に処理したい。
    age_days が無い/読めない行は False (先頭に持ってこない)。
    """
    today = today or datetime.date.today()
    age = _i(row.get("age_days"))
    if age <= 0:
        return False
    d = today - datetime.timedelta(days=age)
    return (d.year, d.month) == (today.year, today.month)


def is_target_site(row, site=TARGET_SITE):
    """落としてよい出品か (= US の親出品か)。純関数。

    UK / AU / CA は eBaymag のミラーなので落とさない (TARGET_SITE の注記参照)。
    site 欄が空の行は **落とさない** (fail-closed)。ミラーかどうか分からないものを
    落とす方が高くつく。
    """
    return (row.get("site") or "").strip().upper() == site


# ★2026-09-05: 除外理由は **ここだけ**で定義する。
#   従来はフィルタ (select の内包表記) と 画面表示 (len(cull)-len(eligible) の引き算) が
#   別々に書かれており、**引き算した数を「age<1日/age不明/$0未満」と決め打ちで表示**していた。
#   実測 (9/5 の走行): 除外150件の内訳は 既落とし77 + アパレル保護76 で、
#   年齢や価格で外れた行は **0件**。数字は正しいのに理由が嘘という状態だった。
#   判定と集計が同じ1本を通るようにして、二度と食い違わないようにする。
def reject_reason(row, done=(), min_age=MIN_AGE, min_price=MIN_PRICE, site=TARGET_SITE):
    """CULL 行を End 対象から外す理由。対象なら None。

    並び = 判定順。**select() はこの関数だけを見る** (フィルタを二重に書かない)。
    """
    from shelf_evict import is_protected as _is_protected
    if not (site is None or is_target_site(row, site)):
        return "US以外 (eBaymag のミラー。親の US を落とせば付いてくる)"
    if _i(row.get("age_days")) < min_age:
        return f"age<{min_age}日 / age不明"
    if _f(row.get("price")) < min_price:
        return f"${min_price:.0f}未満"
    if row.get("item_id") in done:
        return "既に落とした"
    if _is_protected(row.get("title")):
        return "アパレル保護 (公式在庫が戻れば監視くんが数量を戻す)"
    return None


def select(rows, cap=CAP, min_age=MIN_AGE, min_price=MIN_PRICE, today=None,
           done_ids=None, site=TARGET_SITE):
    """CULL ∩ US ∩ age>=min_age を age降順・価格昇順で並べ、先頭 cap 件。

    age 不明(0)は対象外 (fail-closed)。テスト可能なよう純関数化。
    site=None で サイトの絞りを外す (件数の把握用。取り下げには使わない)。
    """
    # ★2026-08-31: アパレル (UNIQLO/GU 等) を除外する。MIN_PRICE ($100) を撤廃するまでは
    #   UT系Tシャツの多くが $100 未満で偶然弾かれていたが、撤廃した実測で 153件中92件が
    #   アパレルだと判明した。shelf_evict.py の 2026-08-28 決定 (公式在庫が戻れば監視くんが
    #   数量を戻すので、取り下げると戻せなくなる) と同じ理由でここも守る必要がある。
    #   判定ロジックの二重管理を避けるため shelf_evict.is_protected を呼ぶ (遅延import:
    #   shelf_evict は cull_end を import しており、モジュール先頭では循環になる)。
    cull = [r for r in rows if "CULL" in (r.get("flags") or "").split("|")]
    done = done_ids or set()
    eligible = [r for r in cull
                if reject_reason(r, done, min_age, min_price, site) is None]
    # ★2026-08-24: **今月出品した分を先に**。当月の枠が戻るのはそこだけ
    #   (実測: 古い順だけで 361件 落として当月に戻ったのは 1.5%)。
    #   今月分は金額の大きい順 = 戻る額を最大化。それ以前は従来どおり age 降順
    #   (最も長く需要0 = 最も確実に dead) → 価格昇順。
    def _key(r):
        cur = listed_this_month(r, today)
        if cur:
            return (0, -_f(r.get("price")), 0.0)
        return (1, -_i(r.get("age_days")), _f(r.get("price")))
    eligible.sort(key=_key)
    return cull, eligible, eligible[:cap]


def end_status(row, done_ids=None, today=None, min_age=MIN_AGE, min_price=MIN_PRICE,
               site=TARGET_SITE):
    """その CULL 行が **落ちたのか / まだなら何が理由で残っているのか** (純関数, test可)。

    ★2026-08-25 ユーザー要望: 在庫なしシートに「どのバケツか / CULL なら取下げ済か」を出す。
      門は `select()` と同じものを同じ順で見る。表示側で条件を書き直すと必ずズレるので、
      **判定はここ (門の持ち主) に置き、表示側は文字列を写すだけ**にする。
    """
    if row.get("item_id") in (done_ids or set()):
        return "🗑 取下げ 済"
    if site is not None and not is_target_site(row, site):
        return "🗑 取下げ 未 (US以外 = eBaymag のミラー。親を落とせば消える)"
    from shelf_evict import is_protected as _is_protected
    if _is_protected(row.get("title")):
        return "🗑 取下げ 未 (アパレル = 監視くんが公式在庫を見て自動復活)"
    age = _i(row.get("age_days"))
    if age < min_age:
        return f"🗑 取下げ 未 (出品 {min_age}日未満)" if age > 0 else "🗑 取下げ 未 (出品日 不明)"
    # ★2026-08-31: MIN_PRICE を撤廃 (0)。price 列が読めない/マイナス等の異常値だけ
    #   ここで拾う (通常の価格は素通りする)。
    if _f(row.get("price")) < min_price:
        return f"🗑 取下げ 未 (価格が不正: ${min_price:.0f} 未満)"
    return "🗑 取下げ 未 (次回の対象)"


def count_workload(funnel_dir=None, today=None):
    """押したら何件落とせるか / あと何件残っているか (2026-08-24 ユーザー要望)。

    ★ボタンのラベルとヒントに出すためのもの。**eBay を1回も叩かない**。
      材料は funnel CSV (ローカル) と 済み台帳だけで、main() の既定経路と同じ数え方。
      (8/24 に API の1日上限で取下げが5時間止まったので、表示のために叩かない)

    戻り: {"remaining": 残り全部, "next": 今回押したら出る件数, "cap": 1回の上限,
           "done": これまでに落とした数, "cull": CULL 全体, "src": 使った funnel,
           "usd_next": 今回で空く出品枠($), "usd_remaining": 残り全部で空く額($),
           "error": 読めなかった理由}

    ★2026-09-04 ユーザー要望「取下げは、金額開かないのかな」。
      eBay の出品枠は **今 売れる状態にある出品の総額**で決まるので、
      「何件落とせるか」より「いくら空くか」が判断材料になる (棚ボタンと同じ考え)。
    """
    out = {"remaining": 0, "next": 0, "cap": CAP, "done": 0, "cull": 0,
           "usd_next": 0.0, "usd_remaining": 0.0, "src": "", "error": ""}
    try:
        fs = glob.glob(os.path.join(funnel_dir or FUNNEL_DIR, "funnel_*.csv"))
        if not fs:
            out["error"] = "funnel_*.csv がありません (先に『📊 ファネル分析』)"
            return out
        src = max(fs, key=os.path.getmtime)
        rows = list(csv.DictReader(open(src, encoding="utf-8")))
        done = load_done()
        cull, eligible, picked = select(rows, done_ids=done, today=today)
        def _usd(rs):
            t = 0.0
            for r in rs:
                try:
                    t += float((r.get("price") or "0").strip() or 0)
                except (TypeError, ValueError):
                    pass
            return round(t, 2)
        out.update(remaining=len(eligible), next=len(picked), done=len(done),
                   cull=len(cull), src=os.path.basename(src),
                   usd_next=_usd(picked), usd_remaining=_usd(eligible))
    except Exception as e:                                     # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"[:60]
    return out


def verify_oos(picked, fetch_fn, status_fn=None):
    """各 picked の現eBay 状態を実機確認し、**まだ生きていて qty==0** のものだけ残す。

    古い funnel を小分け処理する間に補充された listing を誤って取り下げる事故を防ぐ
    (2026-06-28)。fail-closed = qty>0(在庫復活) も qty取得不能(None/例外) も End しない。

    ★2026-08-23: **既に終了済みの listing を除外していなかった**。
      funnel CSV は静的なので、qty だけ見ると終了済みも「qty=0」で通ってしまい、
      毎回 同じ上位N件が選ばれて **2回目以降ずっと進まない**。
      実害: 1回目に End した33件が、2回目の CSV にそのまま載っていた。
      `status_fn` (item_id → ListingStatus) を渡して Active 以外を落とす。

    戻り: (kept, revived, ended, failed)。fetch_fn / status_fn は test 用に注入可能。
    """
    kept, revived, ended, failed = [], [], [], []
    for r in picked:
        if status_fn is not None:
            try:
                st = status_fn(r["item_id"])
            except Exception:                                      # noqa: BLE001
                st = None
            if st is None:
                failed.append(r)                     # 分からない = 触らない
                continue
            if st != "Active":
                ended.append(r)                      # 既に終わっている = もう対象でない
                continue
        try:
            q = fetch_fn(r["item_id"])
        except Exception:                                          # noqa: BLE001
            q = None
        if q is None:
            failed.append(r)
        elif q > 0:
            revived.append(r)
        else:
            kept.append(r)
    return kept, revived, ended, failed


def rows_from_live(fetch_active_fn):
    """出品中の一覧から CULL 行を作る (funnel CSV を使わない)。

    ★2026-08-23: funnel は Seller Hub のレポートを手で落とさないと更新できず、
      7/23 のまま古かった。CULL の材料 (在庫0 / 販売0 / watcher 0 / 出品日) は
      **ActiveList から全部取れる**ので、レポート無しで最新の対象を出せるようにする。
      eBay は 0 の要素を省くので、**QuantitySold / WatchCount が無い = 0** と読む。

    fetch_active_fn: () -> [{item_id, avail, sold, watch, age_days, price, title, site}]
    戻り: funnel CSV と同じ形の dict list (flags に CULL を立てる)。純関数寄り (test 可)。
    ★site が取れない古い呼出のために既定 "US" を入れる (この経路は件数把握のみで、
      取り下げには使わない。空にすると US 限定の絞りで常に0件になる)。
    """
    out = []
    for it in fetch_active_fn():
        if it["avail"] > 0 or it["sold"] > 0 or it["watch"] > 0:
            continue                      # 買える / 売れた / 見られている → CULL ではない
        out.append({"item_id": it["item_id"], "title": it.get("title", ""),
                    "site": it.get("site") or TARGET_SITE,
                    "price": str(it.get("price", 0)), "age_days": str(it["age_days"]),
                    "flags": "CULL"})
    return out


def _fetch_active_live():
    """ActiveList を全ページ取って CULL 判定に要る項目だけ返す。"""
    import re as _re
    sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "iMakeBayAPI")))
    import fix_de_speedpak_shipping as fx
    fx.refresh()
    tok = fx.token()
    today = datetime.datetime.utcnow()
    seen, out = set(), []
    for page in range(1, 60):
        inner = ("<ActiveList><Include>true</Include><Pagination>"
                 "<EntriesPerPage>200</EntriesPerPage>"
                 f"<PageNumber>{page}</PageNumber></Pagination></ActiveList>"
                 "<DetailLevel>ReturnAll</DetailLevel>")
        xml = fx.post("GetMyeBaySelling", inner, tok, site="0")
        if "<Ack>Failure</Ack>" in (xml or ""):
            sys.exit(f"出品一覧の取得に失敗 ({page}ページ目)。途中結果では判断しない (fail-closed)")
        blocks = _re.findall(r"<Item>(.*?)</Item>", xml or "", _re.S)
        if not blocks:
            break
        for b in blocks:
            def g(tag, d=""):
                m = _re.search(rf"<{tag}>(.*?)</{tag}>", b)
                return m.group(1) if m else d
            iid = g("ItemID")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            st = g("StartTime")
            try:
                age = (today - datetime.datetime.strptime(st[:19], "%Y-%m-%dT%H:%M:%S")).days
            except ValueError:
                age = 0                    # 分からない = 対象外 (select が落とす)
            price = _re.search(r'<CurrentPrice currencyID="\w+">([\d.]+)</CurrentPrice>', b)
            out.append({"item_id": iid,
                        "avail": _i(g("Quantity")) - _i(g("QuantitySold")),
                        "sold": _i(g("QuantitySold")),
                        "watch": _i(g("WatchCount")),
                        "age_days": age,
                        "price": float(price.group(1)) if price else 0.0,
                        "site": (g("Site") or TARGET_SITE).strip(),
                        "title": g("Title")})
    return out


def end_on_ebay(picked, post_fn=None, token_fn=None):
    """1件ずつ eBay に取り下げを送る → (成功した itemID list, [(itemID, 失敗理由)])。

    ★2026-08-24: FileExchange を介さず直接送る (ユーザー指示「ボタンは元々自動」)。
      直前に verify_oos で 1件ずつ実状態を見ているので、ここは送るだけ。
      **「既に終了済み」は成功に数える** (目的は達成されている)。
      通信で落ちた分は失敗として残し、成功に混ぜない (silent drop を作らない)。
    """
    import re as _re
    if post_fn is None:
        sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "iMakeBayAPI")))
        import fix_de_speedpak_shipping as fx
        fx.refresh()
        tok = fx.token()
        post_fn, token_fn = fx.post, (lambda: tok)
    tok = token_fn()
    ok, ng = [], []
    for n, r in enumerate(picked, 1):
        iid = r["item_id"]
        xml = post_fn("EndFixedPriceItem",
                      f"<ItemID>{iid}</ItemID><EndingReason>NotAvailable</EndingReason>", tok)
        ack = _re.search(r"<Ack>(\w+)</Ack>", xml or "")
        msgs = _re.findall(r"<LongMessage>(.*?)</LongMessage>", xml or "")
        if ack and ack.group(1) in ("Success", "Warning"):
            ok.append(iid)
        elif msgs and "already been closed" in msgs[0]:
            ok.append(iid)                     # 目的は達成済み
        else:
            ng.append((iid, msgs[0][:80] if msgs else "応答不明"))
        if n % 50 == 0:
            print(f"    {n}/{len(picked)} 送信済 (成功 {len(ok)})", flush=True)
    return ok, ng


def writeback_previous():
    """**前回アップした分**のスプシ後始末を先に済ませる (2026-08-24)。

    End しても `cull_end` はスプシを触らないので、B列に死んだ itemID が残る。
    このシステムは **B列が埋まっている = 出品済み** として動くため、仕入元が復活しても
    二度と出品されない (実測: 8/23 の 361件 のうち 167件 が残っていた)。

    ★別ボタンを増やさず、**取下げボタンを押すたびに前回分を掃除する**形にした。
      押す順番が「掃除 → 次の CSV」で固定されるので、やり忘れが起きない。
      失敗しても本処理は止めない (掃除は次回また拾える。CSV が出ないほうが困る)。
    """
    try:
        import cull_writeback as CW
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠ 後始末 skip (読込失敗): {type(e).__name__}: {e}")
        return
    files = CW.find_result_files()
    if not files:
        print("  (前回の End 結果ファイルは見つかりませんでした → 後始末なし)")
        return
    print(f"  前回分の後始末: End 結果 {len(files)}ファイルを反映します", flush=True)
    try:
        sys.argv = [sys.argv[0], "--commit"]
        CW.main()
    except SystemExit:
        pass
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠ 後始末が最後まで行きませんでした (次回また拾います): "
              f"{type(e).__name__}: {e}")


def main():
    argv = list(sys.argv)
    live = "--live" in argv
    if "--no-writeback" not in argv:
        writeback_previous()
        sys.argv = argv                       # writeback で書き換えた分を戻す
        print()
    if live:
        print("出品中の一覧を eBay から直接取得します (funnel CSV は使いません)...", flush=True)
        rows = rows_from_live(_fetch_active_live)
        src = "eBay ActiveList (live)"
    else:
        fs = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
        if not fs:
            sys.exit("funnel_*.csv がありません。先に『📊 ファネル分析』を実行してください。")
        src = max(fs, key=os.path.getmtime)
        rows = list(csv.DictReader(open(src, encoding="utf-8")))
        src = os.path.basename(src)
    done_ids = load_done()
    cull, eligible, picked = select(rows, done_ids=done_ids)

    print(f"対象 funnel: {src}")
    print(f"CULL(在庫切れ&需要皆無) = {len(cull)}件")
    # ★理由は数えた実数のみ出す (引き算した数に理由を後付けしない)。
    for _why, _n in collections.Counter(
            w for r in cull if (w := reject_reason(r, done_ids))).most_common():
        _hint = f" (押すたびに次の{CAP}件が出ます)" if _why == "既に落とした" else ""
        print(f"  ※ 除外 {_n}件 — {_why}{_hint}")
    print(f"  → 残った候補 = {len(eligible)}件")
    print(f"  今回 End 対象 (CAP {CAP}/回, age降順) = {len(picked)}件")
    if not picked:
        print("対象なし。処理終了。")
        return

    # ★2026-08-23: --live は **数えるだけ**。End CSV は作らない。
    #   実測: live 判定 1,601件のうち **457件 (29%) は funnel では CULL でなかった**
    #   (うち 73件は RESTOCK/NO_CONVERT = 需要が実証されている)。
    #   ActiveList は「今の出品が売れたか」しか見えず、**一度売れて出し直した実績が見えない**。
    #   母数を知るには使えるが、取り下げる対象を選ぶ材料にはならない。
    if live:
        print()
        print("※ --live は件数の把握のみです。End CSV は作りません。")
        print("   取り下げる対象は Seller Hub のレポート → ファネル更新 から選んでください")
        print("   (live 判定は過去の販売実績が見えず、需要のある出品を CULL と誤判定します)")
        return

    # 古い funnel を小分け処理する間に補充された listing を誤取下げしないよう、
    # End 直前に現eBay qty を実機確認 (fail-closed: qty>0/不明は除外)。
    # CULL_NO_VERIFY=1 で明示スキップ可 (緊急時/オフライン)。
    if os.environ.get("CULL_NO_VERIFY") == "1":
        print("  ※ CULL_NO_VERIFY=1: 現eBay在庫の実機確認をスキップ")
    else:
        sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "iMakeBayAPI")))
        try:
            from ebay_getitem_images import fetch_listing_qty, fetch_listing_status
        except Exception as e:
            sys.exit(f"在庫検証モジュール読込失敗のため中止 (fail-closed): {e}\n"
                     "  → どうしても検証なしで進めるなら CULL_NO_VERIFY=1")
        print(f"  現eBay状態を実機確認中 ({len(picked)}件, 終了済/qty>0/不明は除外)...",
              flush=True)
        picked, revived, ended, failed = verify_oos(picked, fetch_listing_qty,
                                                    fetch_listing_status)
        if ended:
            print(f"  ⏭ 既に終了済みで除外 = {len(ended)}件 (前回までに End 済)")
            # ★2026-08-24: **自分が落としたもの以外も憶える**。出品期間の満了などで
            #   自然に終わった分は済みリストに載らず、毎回 候補の枠を食い続けていた
            #   (実測: 同じ43件が3回連続で除外され、その分だけ処理量が減っていた)。
            #   終わっている事実は同じなので、記録して二度と拾わない。
            remember_done([r["item_id"] for r in ended])
        if revived:
            print(f"  ⚠ 在庫復活で除外 = {len(revived)}件 (補充された listing の誤取下げ防止)")
            for r in revived:
                print(f"     復活: {r['item_id']} {(r.get('title') or '')[:45]}")
        if failed:
            print(f"  ⚠ 状態を取れず除外 (fail-closed) = {len(failed)}件")
            # ★2026-08-24: 失敗が半分を超えたら **API の日次上限**を疑う (実際に踏んだ:
            #   GetItem が ErrorCode 518 で全滅し、149/200 が「取れない」に落ちた)。
            #   そのまま続けると「確認できた少数だけ」を送る形になり、判断の母数が壊れる。
            #   上限は日付が変わる (米国太平洋時間の0時 = 日本時間 16時ごろ) と戻る。
            if len(failed) > len(picked) + len(revived) + len(ended):
                print("  ⛔ 半数以上が取れていません。**eBay API の1日の上限**の可能性が高いです。")
                print("     このまま送ると母数が壊れるので中止します。")
                print("     → 日本時間 16時ごろに上限が戻ります。それから押し直してください。")
                return
        print(f"  → End 確定 (qty=0 実機確認済) = {len(picked)}件")
        if not picked:
            print("実機確認後の End 対象なし。処理終了。")
            return

    stamp = datetime.date.today().strftime("%Y%m%d")
    os.makedirs(END_DIR, exist_ok=True)
    end_path = os.path.join(END_DIR, f"cull_end_{stamp}.csv")
    with open(end_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(END_HEADER)
        for r in picked:
            w.writerow(["End", r["item_id"], END_CODE])

    # ★2026-08-24: 確認用一覧は **おまけ**。開きっぱなしだと PermissionError で落ち、
    #   その後の送信まで巻き添えにしていた (実際に踏んだ)。書けなくても本処理は続ける。
    cand_path = os.path.join(DESK, f"CULL出品停止候補_{stamp}.csv")
    fields = ["item_id", "title", "site", "category", "price", "age_days", "watch", "ebay_url"]
    for attempt, path in enumerate((cand_path,
                                    os.path.join(END_DIR, f"CULL候補_{stamp}.csv"))):
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                for r in picked:
                    w.writerow(r)
            cand_path = path
            break
        except OSError as e:
            print(f"  ⚠ 確認用一覧を書けません ({type(e).__name__})。"
                  f"{'別の場所に出します' if attempt == 0 else '一覧なしで続行します'}")
            cand_path = "(出せませんでした)"

    print(f"\nEnd CSV (控え): {end_path}")
    print(f"確認用一覧: {cand_path}")

    if "--csv-only" in argv:
        print(f"\n▶ --csv-only: eBay へは送りません。FileExchange に手動アップ → {len(picked)}件")
        return

    # ★2026-08-24 ユーザー指示: **ボタンは元々自動**。FileExchange を経由せず直接送る。
    #   2026-06-05 の「自動アップ無し」を外す判断の根拠:
    #     - 送る直前に **1件ずつ eBay の実状態を見ている** (今日も 在庫復活6件 / 終了済115件 が外れた)
    #     - 対象は CULL のみ / $100以上 / 14日以上 / 1回 CAP件 まで
    #     - qty=0 = そもそも買えない出品なので、売上を失わない
    #   人が事前に中身を見る機会は無くなるので、確認用一覧は残す (事後に見る)。
    ok_ids, ng = end_on_ebay(picked)
    remember_done(ok_ids)                      # 次回から候補に出さない
    print(f"\n▶ eBay に送信 → 成功 {len(ok_ids)}件 / {len(picked)}件")
    for iid, msg in ng[:8]:
        print(f"   ⚠ {iid}: {msg}")
    if ok_ids:
        try:
            import cull_writeback as CW
            n = CW.apply(set(ok_ids), commit=True)
            print(f"▶ スプシ更新 → {n}件 (B列を空 + Q列に印)")
        except Exception as e:                                 # noqa: BLE001
            print(f"   ⚠ スプシ更新が最後まで行きませんでした (次回の押下で拾います): "
                  f"{type(e).__name__}: {e}")
        # ★2026-08-25: 在庫なしシートの「状態」列を実態に戻す。押した瞬間に済みが増えるので、
        #   ここで直さないと落とした行が「未 (次回の対象)」のまま残る (実際に 122件 残った)。
        #   eBay は叩かない (funnel CSV と 済み台帳だけ)。
        try:
            import oos_status_refresh as OS
            src = OS.latest_funnel_csv()
            if src:
                OS.main_commit(src)
        except Exception as e:                                 # noqa: BLE001
            print(f"   ⚠ 在庫なしシートの状態列は次回に持ち越します: {type(e).__name__}: {e}")
    print(f"▶ 残りは レポート再DL → ファネル再実行 → 本ツール再走 で段階的に (1回{CAP}件まで)")


if __name__ == "__main__":
    main()
