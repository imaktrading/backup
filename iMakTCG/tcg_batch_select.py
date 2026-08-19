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


def balanced_sample(certs, title_map, limit, shuffle=None):
    """franchise 均等に round-robin で limit 件選ぶ。

    各 franchise 内はシャッフル(上位行偏り防止)。巡回は Pokemon→OnePiece→DragonBall→その他。
    ある franchise が尽きたら飛ばして他で埋めるので、在庫が偏っていても「可能な限り均等」になる。
    shuffle: list を in-place シャッフルする関数 (既定 random.shuffle、test 用に注入可)。
    戻り: 選ばれた cert の list (順序も round-robin)。
    """
    if shuffle is None:
        import random
        shuffle = random.shuffle
    groups = {}
    for c in certs:
        groups.setdefault(classify_franchise((title_map or {}).get(c, "")), []).append(c)
    for g in groups.values():
        shuffle(g)
    order = [g for g in _PRIMARY if g in groups] + [g for g in groups if g not in _PRIMARY]
    picked, i = [], 0
    while len(picked) < limit and any(groups[g] for g in order):
        g = order[i % len(order)]
        if groups[g]:
            picked.append(groups[g].pop(0))
        i += 1
    return picked[:limit]
