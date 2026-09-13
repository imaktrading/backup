# -*- coding: utf-8 -*-
"""PSA 新規バッチの franchise 均等サンプリング + 目視済スキップ (純粋ロジック・テスト可能)。

psa_to_csv.main() が 92件等から 10件/回 を選ぶ際、従来は全体 random.shuffle → 先頭10 だった。
在庫は Pokemon が大半なので Pokemon ばかり選ばれ、One Piece / Dragon Ball が滞留していた
(2026-06-23 ユーザー要望: Pokemon / One Piece / Dragon Ball を均等に出品したい)。

選定時点では PSA cert を scrape していないため franchise は確定しないが、スプシ C列(日本語
タイトル)に明示フランチャイズ語 / OP系カード番号が入っており best-effort で分類できる
(実データ98件で誤判定ゼロを確認)。分類 → round-robin で均等に取る。在庫が偏っていても
各 franchise を満遍なく拾い、足りない franchise の分は他で埋める。
"""
import json
import re

_PRIMARY = ("Pokemon", "OnePiece", "DragonBall")

# 目視済(NONE/NG=識別不能)cert を一定期間 再出題しないためのスキップ台帳。
# post_psa_review が NONE/NG 判定時に追記、psa_to_csv.main() が選定プールから除外する。
# (2026-06-23 ユーザー要望: 一度目視したカードがちょいちょい再出現する → 再表示防止)
REVIEW_SKIP_PATH = r"C:/dev/iMak_data/dedupe/psa_review_skip.json"
# この期間は再出題しない。経過後は再浮上 (catalog 修正済なら今度は出品可)。
# ★2026-08-19 ユーザー指示で 14日 → 1日。catalog への依頼は当日中に処理されることが
#   多いので、2週間も伏せておくと直った後も出てこない = 出せるカードを寝かせる。
#   毎日また出てくることになるが、直っていなければ目視で1秒 弾くだけで済む。
REVIEW_SKIP_COOLDOWN_DAYS = 1


def load_review_skips(path=REVIEW_SKIP_PATH):
    """目視済スキップ台帳 {cert: {at, choice}} を読む。無ければ空 dict。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


# 参入しないゲーム/期の cert = **恒久**に出品対象外。cooldown とは別物。
# ★2026-08-09: 自己修復 (resolvable_now) を入れた結果、**永久に引けないカードが
#   14日ごとに永久に浮上する** 穴ができた。SDBH (スーパードラゴンボールヒーローズ) は
#   catalog が「意図的な非対応」と回答済 (Fusion World 専用 scraper / DB 0件 /
#   filter_map にも無し)。引ける日は来ないので、cooldown ではなく恒久に落とす。
#   解除するのは「参入する」と決めた時だけ (理由と決定者をファイルに残す)。
OUT_OF_SCOPE_PATH = r"C:/dev/iMak_data/dedupe/psa_out_of_scope.json"


def load_out_of_scope(path=OUT_OF_SCOPE_PATH):
    """恒久 対象外 cert の set。読めなければ空 (= 誰も止めない側に倒す)。

    `_` 始まりのキーは注記なので除く。
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        return set()
    return {str(k) for k in data if not str(k).startswith("_")}


def resolvable_now(certs, classify_fn=None):
    """今 catalog で引ける cert の set を返す(= もう止める理由が無いもの)。

    なぜ要るか (2026-08-09 実測):
        目視で NONE を付けた**当時の**判断が台帳に焼き付き、その後 catalog が直っても
        誰も見直していなかった。cooldown が切れるたびに同じ cert が浮上し、また
        NONE 扱いで沈む。**台帳49件のうち29件は、その時点で既に resolver が
        canonical product_id を返せた** (PERONA cert153420191 = 3ヶ月で20回以上
        catalog に蒸し返された件も含む)。

    判定は `iMakHQ/tools/psa_preflight.classify` に **SSOT**。ここで再実装しない
    (出品と同じ resolver を使うことが「引ける」の定義)。

    ★fail-closed: 判定できない時 (catalog import 不能 / cert cache 無し / 例外) は
      **空 set を返す = 何も外さない**。取りこぼす方に倒す。誤って外すと目視の
      再出題が増えるだけだが、判定不能を「引ける」に倒すと壊れた resolver で
      出品側へ流れてしまう。
    """
    certs = [str(c) for c in (certs or [])]
    if not certs:
        return set()
    if classify_fn is None:
        classify_fn = load_resolver()
    if classify_fn is None:
        # ★黙って no-op にしない。ここが静かに死ぬと「自己修復を入れた」つもりのまま
        #   14日ループが復活し、しかも誰も気づかない (= いちばん質の悪い壊れ方)。
        print("  ⚠️ 目視skipの自己修復: 判定器を読めないので **1件も解除しません**"
              " (psa_preflight/catalog の import を確認)")
        return set()

    out = set()
    for cert in certs:
        try:
            if classify_fn(cert) == "RESOLVED":
                out.add(cert)
        except Exception:
            continue                                     # 1件の失敗で全体を壊さない
    return out


def resolved_pids_now(certs):
    """cert → 今 resolver が返す product_id の dict。引けない/判定不能な cert は入れない。

    なぜ要るか (2026-08-09 実測):
        自己修復は「resolver が引ける = もう止める理由が無い」と見なすが、
        **人が既にその答えを見て『該当なし』と言っている**場合、同じ提案を出し直す
        だけになる。実測 cert158452539 は 7/23・8/06・8/09 の3回とも expected が
        `FB01-071_PARA` で同一、cert138056958 は BDK-006 で同一。cooldown を
        自己修復が毎回解除するので **毎日** 同じ問いが出る状態だった。

    fail-closed: 判定できなければ空 dict (= 何も外さない) を返す。
    """
    certs = [str(c) for c in (certs or [])]
    if not certs:
        return {}
    try:
        import os as _os
        import sqlite3 as _sq
        import sys as _sys
        _hq = _os.path.join(_os.path.dirname(_os.path.dirname(
            _os.path.abspath(__file__))), "iMakHQ", "tools")
        if _hq not in _sys.path:
            _sys.path.insert(0, _hq)
        import psa_preflight as _pf
        _pf._ensure_catalog()
        _con = _sq.connect(_pf.CATALOG_DB)
    except Exception:
        return {}
    out = {}
    for cert in certs:
        try:
            f = _pf.PSA_CERTS_DIR / f"{cert}.json"
            if not f.exists():
                continue
            meta = json.loads(f.read_text(encoding="utf-8"))
            r = _pf.classify(str(cert), meta, _con)
            if r.get("status") == "RESOLVED" and r.get("product_id"):
                out[str(cert)] = str(r["product_id"])
        except Exception:
            continue                                     # 1件の失敗で全体を壊さない
    return out


def load_resolver():
    """cert → 判定ステータス を返す callable。読めなければ None (呼び手が気づけるように)。

    判定の定義は `iMakHQ/tools/psa_preflight.classify` に **SSOT**。
    ここで resolver を再実装しない (出品と同じ引き方であることが「引ける」の意味)。
    """
    try:
        import os as _os
        import sqlite3 as _sq
        import sys as _sys
        _hq = _os.path.join(_os.path.dirname(_os.path.dirname(
            _os.path.abspath(__file__))), "iMakHQ", "tools")
        if _hq not in _sys.path:
            _sys.path.insert(0, _hq)
        import psa_preflight as _pf
        _pf._ensure_catalog()                            # 遅延 import をここで確定させる
        _con = _sq.connect(_pf.CATALOG_DB)
    except Exception:
        return None

    def _classify(cert):
        f = _pf.PSA_CERTS_DIR / f"{cert}.json"
        if not f.exists():
            return None                                  # cache 無し = 判定材料なし
        meta = json.loads(f.read_text(encoding="utf-8"))
        return _pf.classify(str(cert), meta, _con).get("status")

    return _classify


def already_rejected_same_answer(skip_data, certs, resolved_pids=None):
    """「人が既にその答えを見て断った」cert の set。= 自己修復で解除してはいけないもの。

    台帳の `pid` (却下された product_id) と **今 resolver が返す product_id** が同じなら、
    出し直しても同じ問いにしかならない。catalog か resolver が変わって答えが**変わった**
    時だけ再出題する。

    ★2026-08-09 実測: この歯止めが無いため cert158452539/158452540/140936782/138056958 が
      毎回 RESOLVED 判定で cooldown を解除され、同一 expected のまま再出題されていた
      (158452539 は4回・138056958 は4回)。

    fail-closed: 台帳に `pid` が無い (旧形式) / 判定不能 → **この歯止めを効かせない**
    (= 従来どおり自己修復が働く)。黙って永久 hide する方には倒さない。
    """
    certs = [str(c) for c in (certs or [])]
    if not certs:
        return set()
    pids = resolved_pids_now(certs) if resolved_pids is None else {
        str(k): str(v) for k, v in (resolved_pids or {}).items()}
    out = set()
    for cert in certs:
        info = (skip_data or {}).get(cert) or {}
        prev = (info.get("pid") or "").strip() if isinstance(info, dict) else ""
        if prev and pids.get(cert) == prev:
            out.add(cert)
    return out


def active_review_skips(skip_data, now, cooldown_days=REVIEW_SKIP_COOLDOWN_DAYS,
                        resolvable=None, out_of_scope=None, resolved_pids=None):
    """cooldown 期間内に NONE/NG 目視された cert の set を返す(= 今回スキップ対象)。

    at(ISO日時)が cooldown 内 → スキップ。経過/不明 → スキップしない(永久hide回避 = 再浮上させる)。
    now は datetime(test 用に注入可)。

    ★2026-08-09b: **恒久 対象外 (参入しないゲーム)** は cooldown と無関係に常にスキップ。
      自己修復と対にしないと、永久に引けないカードが14日ごとに永久に浮上する。

    ★2026-08-09: **今 catalog で引ける cert は cooldown 中でもスキップしない**。
      「目視した時に引けなかった」は当時の事実であって、catalog が直った後も
      止め続ける理由にはならない。これが無いと台帳が自己修復せず、
      14日ごとに同じ cert が浮いては沈むループになる (実測 49件中29件が該当)。
      resolvable=None なら resolvable_now() で自動判定 (判定不能なら何も外さない)。
    """
    import datetime as _dt
    out = set()
    for cert, info in (skip_data or {}).items():
        at = info.get("at") if isinstance(info, dict) else None
        if not at:
            continue
        try:
            t = _dt.datetime.fromisoformat(at)
        except Exception:
            continue
        if (now - t).days < cooldown_days:
            out.add(str(cert))
    # ★恒久 対象外は cooldown の外。自己修復でも解除しない。
    #   これが無いと「永久に引けないカードが14日ごとに永久に浮上する」ことになる。
    oos = load_out_of_scope() if out_of_scope is None else {str(c) for c in out_of_scope}
    if not out:
        return set(oos)
    ok = resolvable_now(out) if resolvable is None else {str(c) for c in resolvable}
    # ★人が既に「その答え」を見て断っている cert は解除しない。解除すると同一 expected の
    #   問いを毎日出し直すだけになる (2026-08-09 実測: 4件が毎回浮上していた)。
    ok = ok - already_rejected_same_answer(skip_data, ok, resolved_pids=resolved_pids)
    return (out - ok) | oos


def classify_franchise(title):
    """C列(日本語)タイトル → franchise ('Pokemon'|'OnePiece'|'DragonBall')。best-effort。

    明示フランチャイズ語を最優先、次に OP/DB 系カード番号、既定は Pokemon(在庫の大半)。
    Pokemon を OnePiece/DragonBall に誤分類しない方を優先(誤って少数派を水増ししないため)。
    """
    t = title or ""
    T = t.upper()
    # 明示フランチャイズ語 (最優先)
    if "ドラゴンボール" in t:
        return "DragonBall"
    if "ワンピース" in t:
        return "OnePiece"
    if "ポケモン" in t:
        return "Pokemon"
    # カード番号 (前に英字が無い境界 = "POP17" の "OP" 誤検出を防ぐ)
    if re.search(r"(?<![A-Z])(OP|ST|EB|PRB)\d{2}-\d{2,3}", T):
        return "OnePiece"
    if re.search(r"(?<![A-Z])(E\d{2}|FB\d{2}|FS\d{2})-?\d", T):
        return "DragonBall"
    if "エナジーマーカー" in t:        # Dragon Ball Energy Marker (E01系)
        return "DragonBall"
    return "Pokemon"                   # 既定 = 在庫の大半


# ★2026-09-08 ユーザー確定「ポケモン7」。均等(1:1:1)をやめ、**ポケモン7割**にする。
#   根拠 (2026-09-08 実測 / funnel + US live):
#     ポケモン    273件 / 棚 $53,439 / 売れた 11 → $1万あたり 2.06
#     ワンピース   211件 / 棚 $60,086 / 売れた  3 → $1万あたり 0.50
#     ガンダム     15件 / ドラゴンボール 10件 → どちらも 売れた 0
#   2026-06-23 に均等にしたのは「ワンピ/DB が滞留するから」だったが、3ヶ月回した結果
#   **滞留ではなく売れていなかった**ことが分かった。棚(金額枠)は超過中なので、
#   同じ $ を使うなら効率の高い方に寄せる。
#   残り3割は ワンピース→ドラゴンボール→その他 の順ぐりで配る (0件にはしない = 需要の再確認枠)。
POKEMON_SHARE = 0.7


def demand_by_set(funnel_rows):
    """ファネル(出品ごとの実績) → {セット記号: 需要スコア} (純関数, test可)。

    ★2026-09-08 ユーザー確定「ポケモン70%、売れ筋優先」。
      配点は既存の需要スコア (demand_winners.py) をそのまま使う:
        実売*100 + watch*8 + 表示*0.05  (信頼度: 実売 >> watch > 表示)
      PSA の実売は月14件と薄いので、**点数の大半はウォッチで決まる**。
      「売れた実績」ではなく「欲しがられている気配」の順、という理解で使うこと。
    セット記号は英語タイトルの `#SV8a-203` / `#203/187` 形式から取る。
    """
    out = {}
    for r in (funnel_rows or []):
        t = (r.get("title") or "")
        if not t.lower().startswith("psa 10"):
            continue
        # ワンピ等: `#OP09-001` / ポケモン: `Sv8a: Terastal…` (番号は `#203/187` で
        # セット記号を持たないので、セット名の前置きから取る)
        m = re.search(r"#([A-Za-z0-9]{1,6})-\d{1,4}", t) or \
            re.search(r"\b([A-Za-z]{1,3}\d{1,2}[A-Za-z]?):", t)
        if not m:
            continue
        def _f(k):
            try:
                return float(r.get(k) or 0)
            except (TypeError, ValueError):
                return 0.0
        s = m.group(1).upper()
        out[s] = out.get(s, 0.0) + (_f("sold_qty") + _f("sales90")) * 100             + _f("watch") * 8 + _f("impr_total") * 0.05
    return out


def set_of_key(key):
    """商品管理シートの鍵 (`pokemon_tcg:SV8a-203` / `OP09-001_p1`) → セット記号 (純関数)。

    取れない鍵 (`item:m123...` / 空) は None = **売れ筋の順位を付けられない**。
    """
    k = (key or "").strip()
    if not k:
        return None
    m = re.match(r"^(?:[a-z_]+:)?([A-Za-z0-9]{1,6})-\d{1,4}", k)
    return m.group(1).upper() if m else None


def balanced_sample(certs, title_map, limit, shuffle=None, cost_of=None,
                    pokemon_share=None, explore=0.2, demand_of=None):
    """franchise 比率つきで limit 件選ぶ (既定: ポケモン7割 / 残り3割は他を順ぐり)。

    各グループ内の順番 (2026-09-08 ユーザー確定):
      - **仕入値の安い順**。実測で 出品価格 $100未満の売却率 5.2% に対し $400超は 1.6%。
        安いほど売れ、しかも同じ棚(金額)でたくさん出せる。
      - ただし `explore` の割合だけ **ランダム**を混ぜる。値段の分からない物や
        まだ出したことのない系統を、順位だけで永久に殺さないため。
    cost_of: cert → 仕入値(円) を返す関数。None / 取れない cert は「値段不明」として
             安い順の後ろに置く (推測で前に出さない)。
    shuffle: list を in-place シャッフルする関数 (既定 random.shuffle、test 用に注入可)。
    戻り: 選ばれた cert の list。
    """
    if shuffle is None:
        import random
        shuffle = random.shuffle
    share = POKEMON_SHARE if pokemon_share is None else pokemon_share
    groups = {}
    for c in certs:
        groups.setdefault(classify_franchise((title_map or {}).get(c, "")), []).append(c)
    for g in groups.values():
        shuffle(g)                      # 探索枠 (安い順を当てる前の並びをランダムにしておく)
    if demand_of is not None:
        # ★売れ筋優先 (2026-09-08 ユーザー確定)。順位を付けられない物 (鍵が無い/形が違う)
        #   は **後ろにランダムのまま** 置く (「それ以外は適当でいい」)。
        #   出品が進んで順位付きが減れば、そのぶん出番が回る。
        for name, g in groups.items():
            scored = [(demand_of(c), c) for c in g]
            known = sorted([(d, c) for d, c in scored if d is not None],
                           key=lambda x: -x[0])
            unknown = [c for d, c in scored if d is None]
            groups[name] = [c for _, c in known] + unknown
    elif cost_of is not None:
        n_explore = max(0, int(round(limit * explore)))
        for name, g in groups.items():
            keep_random = g[:n_explore]              # ランダムのまま残す分
            rest = g[n_explore:]
            rest.sort(key=lambda c: (cost_of(c) is None, cost_of(c) or 0))
            groups[name] = keep_random + rest
    if share and "Pokemon" in groups:
        return _sample_with_share(groups, limit, share)
    order = [g for g in _PRIMARY if g in groups] + [g for g in groups if g not in _PRIMARY]
    picked, i = [], 0
    while len(picked) < limit and any(groups[g] for g in order):
        g = order[i % len(order)]
        if groups[g]:
            picked.append(groups[g].pop(0))
        i += 1
    return picked[:limit]


def _sample_with_share(groups, limit, share):
    """ポケモンに `share` の枠を割り当て、残りを他グループへ順ぐりに配る (純関数)。

    ポケモンが足りなければ他で埋め、他が無ければポケモンで埋める (枠を空けない)。
    """
    pk = list(groups.get("Pokemon") or [])
    others_order = [g for g in _PRIMARY if g != "Pokemon" and groups.get(g)] +                    [g for g in groups if g not in _PRIMARY and groups.get(g)]
    others = {g: list(groups[g]) for g in others_order}
    n_pk = min(len(pk), int(round(limit * share)))
    picked = pk[:n_pk]
    i = 0
    while len(picked) < limit and any(others[g] for g in others_order):
        g = others_order[i % len(others_order)]
        if others[g]:
            picked.append(others[g].pop(0))
        i += 1
    if len(picked) < limit:                 # 他が尽きた → ポケモンで埋める
        picked += pk[n_pk:n_pk + (limit - len(picked))]
    return picked[:limit]


FUNNEL_GLOB = r"C:/dev/iMak/iMakHQ/funnel_output/funnel_*.csv"


def _pid_from_psa_cache(certs):
    """cert → catalog の product_id を **PSA データの手元キャッシュ** から引く (I/O・失敗は空)。

    出品くんの前段 (psa_preflight.classify) と同じ解決を使う。解決できない物は入れない。
    """
    out = {}
    try:
        import json as _json
        import sqlite3 as _sq3
        import sys as _sys
        _sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
        import psa_preflight as _pf
        con = _sq3.connect(_pf.CATALOG_DB)
    except Exception:                                          # noqa: BLE001
        return out
    try:
        for c in certs:
            f = _pf.PSA_CERTS_DIR / f"{c}.json"
            if not f.exists():
                continue
            try:
                r = _pf.classify(str(c), _json.loads(f.read_text(encoding="utf-8")), con)
            except Exception:                                  # noqa: BLE001
                continue
            if r.get("status") == "RESOLVED" and r.get("product_id"):
                out[c] = r["product_id"]
    finally:
        con.close()
    return out


def build_demand_of(certs, funnel_glob=None, key_map=None, fallback_key_of=None):
    """cert → 売れ筋スコア を返す関数を作る (I/O。材料が無ければ全部 None = 従来の順)。

    ★2026-09-08 ユーザー確定「ポケモン70%、売れ筋優先。それ以外は適当でいい」。
      鍵 (商品管理シート AI列) からセット記号を取り、ファネルのセット別スコアを引く。
      点が付くのは実測でプールの44% (2026-09-08: 1,172件中513件)。残りは None。
    ★2026-09-13: **219件中0件** に点が付いていた。鍵 (AI列) は出品した後に入る物で、
      「既出品の2枚目」を前段で落とすようになってから、残る候補は全部 鍵が無い = 構造的に0件。
      鍵が無い候補は **PSA データの手元キャッシュから product_id を引いて** セット記号を取る
      (出品くんの前段と同じ解決)。キャッシュは夜間 iMakHQ_PsaCacheWarm_0130 が貯める
      (このタスクが 8/19 から一度も動いていなかったのも同日に発覚・有効化)。
    """
    import csv as _csv
    import glob as _glob
    import os as _os
    try:
        files = _glob.glob(funnel_glob or FUNNEL_GLOB)
        if not files:
            return lambda c: None
        src = max(files, key=_os.path.getmtime)
        with open(src, encoding="utf-8") as f:
            score = demand_by_set(list(_csv.DictReader(f)))
        if key_map is None:
            import sys as _sys
            _sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
            _sys.path.insert(0, r"C:/dev/iMak/iMakeBayAPI")
            import sheet_io as _sio
            vals = _sio._product_ws().get_all_values()
            kc, ic = _sio.PRODUCT_COL_KEY, 8
            key_map = {(r[ic] or "").strip(): (r[kc] if len(r) > kc else "")
                       for r in vals[1:] if len(r) > ic and (r[ic] or "").strip()}
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠ 売れ筋の点を作れませんでした ({type(e).__name__}) → 従来の順で選びます")
        return lambda c: None
    if fallback_key_of is None:
        _need = [c for c in certs if not (key_map.get(c) or "").strip()]
        _pids = _pid_from_psa_cache(_need)
        fallback_key_of = _pids.get

    def key_of(c):
        return (key_map.get(c) or "").strip() or (fallback_key_of(c) or "")
    n = sum(1 for c in certs if score.get(set_of_key(key_of(c))) is not None)
    n_fb = sum(1 for c in certs if not (key_map.get(c) or "").strip()
               and score.get(set_of_key(fallback_key_of(c) or "")) is not None)
    print(f"  🔥 売れ筋順: {n}/{len(certs)}件に点が付きます (うち PSAデータから {n_fb}件 / "
          f"残りは点なし=後ろ・順不同)")
    return lambda c: score.get(set_of_key(key_of(c)))
