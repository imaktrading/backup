"""auto_catalog_add_request.py — missing_models.csv watcher.

C:/dev/iMak_data/catalog/missing_models.csv の新規 model を検知して、
Catalog Claude 向け追加依頼書を C:/dev/iMak_data/catalog/requests/ に自動生成する。

- Claude を使わず純 Python (= 過去並列 session 事故 type と無縁)
- 既処理 sentinel: missing_models_processed.csv (= (category, model) key で保持)
- 依頼書 filename: YYYY-MM-DD_auto_catalog_add_<category>.md
- 同日同 category 既存ファイルは skip (= 翌日 chance、 重複投入回避)
- 議論要件 (= ranking logic / 既存修正 / specs 拡充) は本仕組み対象外、
  HQ から個別依頼書

ユーザー合意 2026-05-25: 「カタログ追加は確認なしに依頼するようにしてほしい」
"""
from __future__ import annotations

import csv
import datetime
import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

DATA_ROOT = Path("C:/dev/iMak_data/catalog")
MISSING_CSV = DATA_ROOT / "missing_models.csv"
PROCESSED_CSV = DATA_ROOT / "missing_models_processed.csv"
REQUESTS_DIR = DATA_ROOT / "requests"

# A群 suppression list (2026-08-10): 公式が物理的に画像を持たない pid の外部宣言。
# 該当 pid は毎日 missing_models.csv に再検出されても依頼書を出さない。
# revalidation は entry を消して既存 rescue script を打つ手動運用 (定期 re-check なし)。
# 回答書: hq/requests/2026-08-10_catalog_auto_request_suppress_known_no_image_response.md
SUPPRESSION_JSON = Path(__file__).parent / "known_no_image_a_group.json"

CATEGORY_LABELS: dict[str, str] = {
    "gshock":         "G-SHOCK 腕時計",
    "pokemon_tcg":    "Pokemon TCG",
    "one_piece_tcg":  "One Piece TCG",
    "dragonball_scg": "Dragonball SCG",
    "gundam_tcg":     "Gundam TCG",
    "montbell":       "montbell",
    "uniqlo_ut":      "UNIQLO UT",
    "workman":        "Workman",
}


# ---------------------------------------------------------------------------
# catalog 実在 pre-check (2026-08-08)
#
# なぜ: `post_psa_review._route_none_to_catalog` にだけ pre-check があり (18b36a2)、
#   **こちらの watcher が素通ししていた**ため、既に catalog にあるカードの追加依頼が
#   毎日 catalog に届いていた。ここは書き手を問わない最終防衛線
#   (psa_to_csv / psa_restock_csv / 将来の writer のどれから来ても引っかかる)。
#
# 依頼書: C:/dev/iMak_data/hq/requests/2026-08-08_auto_catalog_add_needs_same_precheck.md
#
# ★判定の定義は post_psa_review に SSOT。ここでは **再実装しない** (2箇所に書くと必ずズレる)。

# `_route_none_to_catalog` が書く既知トークン `(auto候補<PID>=` の逆処理。
# 名前検索でも曖昧一致でもなく、SSOT 側が埋めた literal を抜くだけ。
_AUTO_CANDIDATE_RE = re.compile(r"\(auto候補([^=]+)=")

# post_psa_review が _PID_NO_IMAGE で emit する note format `catalog <PID> は在るが画像が無く目視できない`。
# 2026-08-10 追加: A群 suppression の pid 抽出用。**catalog_present 経路では使わない**
# (NO_IMAGE 行を silent に catalog_present で drop すると 2026-08-09 の意図的 NO_IMAGE→catalog
# 経路を破壊する。suppression list 明示照合だけに使う)。
_NO_IMAGE_PID_RE = re.compile(r"catalog\s+(\S+?)\s+は在るが画像が無く目視できない")
_NO_IMAGE_NOTE_MARK = "は在るが画像が無く目視できない"

# post_psa_review が _PID_OK で emit する note (2026-08-19)。
# `catalog <PID> は在る(画像あり)が人が現物と別絵柄と判断 variant欠落の疑い`
# NO_IMAGE と同じく **行が catalog に在ることを前提に出す依頼**なので、catalog_present で
# drop すると意図した依頼を毎日握り潰すことになる。
_VARIANT_GAP_PID_RE = re.compile(r"catalog\s+(\S+?)\s+は在る\(画像あり\)")
_VARIANT_GAP_NOTE_MARK = "variant欠落の疑い"


def _extract_expected_pid(model: str) -> str | None:
    """model 文字列から canonical PID を抜く。抜けなければ None (= 判定不能)。

    missing_models.csv の model には3形式ある:
      1. post_psa_review 由来 (auto候補) … `cert… (auto候補OP07-118=該当なし 要調査)`
         → `(auto候補<PID>=` に canonical PID が埋まっている
      2. post_psa_review 由来 (NO_IMAGE, 2026-08-09〜) …
         `cert… (catalog SM9a-067 は在るが画像が無く目視できない 画像を追加してほしい)`
         → `catalog <PID> は` に canonical PID が埋まっている (A群 suppression 判定用)
      3. psa_to_csv 由来 … `ONE PIECE JAPANESE 3RD ANNIVERSARY SET-118`
         → **canonical PID ではない**ので None を返し、従来通り依頼を出す (fail-closed)
    """
    if not model:
        return None
    m = _AUTO_CANDIDATE_RE.search(model)
    if m:
        return m.group(1).strip() or None
    m = _NO_IMAGE_PID_RE.search(model)
    if m:
        return m.group(1).strip() or None
    m = _VARIANT_GAP_PID_RE.search(model)
    if m:
        return m.group(1).strip() or None
    return None


def _load_catalog_probe():
    """post_psa_review から `_catalog_has_pid` と log path を借りる (再実装しない)。

    取れなければ (None, None) を返し、呼出側は **全件を従来通り依頼**に回す (fail-closed)。
    """
    try:
        spec = importlib.util.spec_from_file_location(
            "post_psa_review_probe", str(Path(__file__).parent / "post_psa_review.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._catalog_has_pid, mod._VIEWER_DISAGREEMENT_LOG_PATH
    except Exception as e:      # noqa: BLE001  取れないこと自体は握りつぶさず表示する
        print(f"[warn] catalog実在 pre-check を読み込めない ({e}) → 全件を従来通り依頼")
        return None, None


def _filter_catalog_present(new_by_cat: dict[str, list[dict]],
                            unique: dict[tuple[str, str], dict] | None = None,
                            db_path=None) -> int:
    """catalog に実在する (category, model) を new_by_cat から取り除き、件数を返す。

    fail-closed 契約 (18b36a2 準拠):
      - `_catalog_has_pid` が **True の時だけ**除外する
      - False (未収録) / None (pid 空・DB 不在・抽出不能) は従来通り依頼を出す
      - 名前検索フォールバック禁止 (canonical KEY 完全一致のみ)
      - 除外した件は理由付きで viewer_disagreement.log へ (18b36a2 と同じ log)

    ★`unique` を渡すと missing_models.csv 側からも落とす。
      落とさないと **毎日同じ行を再判定して log に同じ行を積む**ため
      (「毎回検出して毎回捨てる」= 動いているのか壊れているのか読めなくなる)。
      processed sentinel には入れない ので、catalog から消えれば次の検出でまた載る。
    """
    has_pid, vd_path = _load_catalog_probe()
    if has_pid is None:
        return 0

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    removed = 0
    for category, rows in list(new_by_cat.items()):
        kept: list[dict] = []
        for r in rows:
            # NO_IMAGE 形式 (2026-08-09〜) は行が catalog に「あるまま画像だけ欠けている」ことを
            # 依頼する経路。行の存在を根拠に catalog_present で drop すると 2026-08-09 の
            # 意図的な NO_IMAGE→catalog 依頼を毎日握り潰すことになる。
            # A群 (補完不能) の除外は _filter_suppression が明示 list で担当する。
            _model = r.get("model") or ""
            if _NO_IMAGE_NOTE_MARK in _model or _VARIANT_GAP_NOTE_MARK in _model:
                kept.append(r)
                continue
            pid = _extract_expected_pid(r["model"])
            exists = has_pid(category, pid, db_path) if pid else None
            if exists is not True:
                kept.append(r)
                continue
            # viewer/adapter 側の食い違い → catalog に依頼を出さない
            try:
                vd_path.parent.mkdir(parents=True, exist_ok=True)
                with vd_path.open("a", encoding="utf-8") as vf:
                    vf.write(f"{ts}\t[auto_catalog_add_watcher]\t{category}\t{pid}"
                             f"\tmodel={r['model']}\n")
            except OSError:
                pass
            if unique is not None:
                unique.pop((category, r["model"]), None)
            print(f"    ⏭️ Skip auto_catalog_add (catalog実在): {category}:{pid}")
            removed += 1
        if kept:
            new_by_cat[category] = kept
        else:
            del new_by_cat[category]
    return removed


_CERT_RE = re.compile(r"cert(\d{6,})")

# 「同じカードが catalog に別の id で在る」時に依頼を出さないための最終ゲート (2026-08-22)。
#
# なぜ: 2026-08-21 に「catalog 未登録」として 5件の追加依頼を出したが、
#   3件は当日 catalog に登録済、2件は **こちら側が組み立てた id** (`PRB01-004`) で
#   探していただけで、実体は `ST17-004_p1` として在った。catalog から2本の訂正が返り、
#   同じ日に「訂正の訂正」まで出している。
#   下の `_filter_catalog_present` は **期待 pid の完全一致**しか見ないので、
#   別 id で在るケースを素通りさせる。
#
# 何を見るか: 出品と同じ resolver (`psa_preflight.classify`)。
#   RESOLVED (解決した) / INDEX-FAILURE (索引の揺れで在った) / REVIEW (候補が在る)
#   のどれかなら **catalog に不足は無い** ので依頼しない。GAP の時だけ依頼する。
#
# fail-closed: cert が抜けない / cache が無い / 例外 → **従来どおり依頼を出す**。
def _filter_resolver_resolves(new_by_cat: dict[str, list[dict]],
                              unique: dict[tuple[str, str], dict] | None = None) -> int:
    """catalog に別 id で実在するものを落とし、件数を返す (判定不能は残す)。"""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import psa_preflight as _pf
        import sqlite3
        con = sqlite3.connect(_pf.CATALOG_DB)
    except Exception as e:      # noqa: BLE001
        print(f"[warn] resolver pre-check を読み込めない ({e}) → 全件を従来通り依頼")
        return 0

    removed = 0
    try:
        for category, rows in list(new_by_cat.items()):
            kept: list[dict] = []
            for r in rows:
                model = r.get("model") or ""
                # 画像が無い / variant 欠落 は「行は在るが中身が足りない」依頼なので触らない
                if _NO_IMAGE_NOTE_MARK in model or _VARIANT_GAP_NOTE_MARK in model:
                    kept.append(r)
                    continue
                m = _CERT_RE.search(model)
                meta_path = (Path(_pf.PSA_CERTS_DIR) / f"{m.group(1)}.json") if m else None
                if not (meta_path and meta_path.exists()):
                    kept.append(r)                      # cert 不明 / cache 無 → 従来どおり
                    continue
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    res = _pf.classify(m.group(1), meta, con)
                except Exception:
                    kept.append(r)                      # 判定不能 → 従来どおり
                    continue
                status = res.get("status")
                if status not in ("RESOLVED", "INDEX-FAILURE", "REVIEW"):
                    kept.append(r)
                    continue
                found = (res.get("product_id") or res.get("recovered")
                         or ", ".join(res.get("candidates") or []))
                print(f"    ⏭️ Skip auto_catalog_add (別 id で catalog に在る): "
                      f"{category} cert{m.group(1)} → {status} {found}")
                if unique is not None:
                    unique.pop((category, model), None)
                removed += 1
            if kept:
                new_by_cat[category] = kept
            else:
                del new_by_cat[category]
    finally:
        con.close()
    return removed


# ---------------------------------------------------------------------------
# 入口検査 (2026-08-19, 提案C)
#
# なぜ: カード名もセット名も空の依頼書が実際に出た
#   (`2026-08-17_auto_catalog_add_.md` = category 欄が空、本文が「`` カテゴリの…」)。
#   **catalog が調べようのない依頼は出さない** = fail-closed。
#   書き手 (newcand_confirm / post_psa_review / psa_to_csv) を問わない最終防衛線なのでここに置く。
# 回答書: hq/requests/2026-08-19_act_code_proposals_tcg_response.md の 5
#
# ★2026-08-19 撤回: ここに URL の domain rule
#   (`snkrdunk.com/apparels/` を TCG では弾く) を一度入れたが、**誤りなので消した**。
#   snkrdunk はトレカを `/apparels/` パスで配信している (自社の仕入コードがそれを使っている:
#   `snkrdunk_psa_resource.py:35` `CARD_PAGE_TMPL = ".../apparels/{card_id}"`)。
#   実測 TCG 行の主URL 45件 / 補URL 270件がこの形。衣料品専用パスではない。
#   **URL の形では衣料品とトレカを区別できない。同種の rule を足さないこと。**
#   元の実害 (空の依頼書) は下の カテゴリ空 / タイトル空 の2つで足りている。
#   依頼書: hq/requests/2026-08-19_snkrdunk_apparels_overblock.md

REJECTED_LOG = Path(__file__).parent.parent / "logs" / "missing_models_rejected.log"

# model 末尾の注記 `(…)` を剥がす。注記に nest した括弧は現状どの書き手も出さない。
_NOTE_TAIL_RE = re.compile(r"\s*\([^()]*\)\s*$")
# 数字を含む語 / `番号不明` は「名前」ではない (cert151234 / OP05-002 / #013 / 番号不明)。
_NUMBERISH_RE = re.compile(r"^(番号不明|(?=.*\d)[A-Za-z0-9\-/_#\.]+)$")


def title_part(model: str) -> str:
    """model から「カード名らしい語」だけ残す (純関数, test可)。空文字なら名前が無い。"""
    s = (model or "").strip()
    prev = None
    while prev != s:                      # 注記が複数付いていても全部剥がす
        prev = s
        s = _NOTE_TAIL_RE.sub("", s).strip()
    return " ".join(t for t in s.split() if not _NUMBERISH_RE.match(t))


def reject_reason(category: str, model: str) -> str | None:
    """依頼を起票してはいけない行なら理由、問題なければ None (純関数, test可)。"""
    cat = (category or "").strip()
    if not cat:
        return "カテゴリ空 (どの作品か判らない依頼は catalog 側で調べようがない)"
    if not title_part(model):
        return "タイトル空 (カード名が無い依頼は catalog 側で調べようがない)"
    return None


def _filter_invalid_entries(new_by_cat: dict[str, list[dict]],
                            unique: dict[tuple[str, str], dict] | None = None,
                            log_path: Path | None = None) -> int:
    """入口検査に落ちた行を new_by_cat + unique から取り除き、件数を返す。

    silent drop しない: 落とした行は必ず理由付きで log と stdout に残す
    (`failclosed_must_skip_not_destructive`)。
    """
    path = log_path if log_path is not None else REJECTED_LOG
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    removed = 0
    lines: list[str] = []
    for category, rows in list(new_by_cat.items()):
        kept: list[dict] = []
        for r in rows:
            why = reject_reason(category, r.get("model") or "")
            if not why:
                kept.append(r)
                continue
            lines.append(f"{ts}\t{category or '(空)'}\t{why}\t{r.get('model') or ''}\n")
            if unique is not None:
                unique.pop((category, r["model"]), None)
            print(f"    ⏭️ Skip auto_catalog_add (入口検査): {category or '(空)'} — {why}")
            removed += 1
        if kept:
            new_by_cat[category] = kept
        else:
            del new_by_cat[category]
    if lines:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.writelines(lines)
        except OSError as e:      # noqa: BLE001  log が書けなくても除外自体は続ける
            print(f"[warn] {path.name} に書けない ({e})")
    return removed


# ---------------------------------------------------------------------------
# A群 suppression (2026-08-10)
#
# なぜ: 公式 (pokemon-card.com 等) が物理的に持たない pid は catalog 側で埋めようがない。
#   毎日 auto 依頼が再生成 → 毎日 catalog が「投入不要」を返す = 無駄ループ。
#   HQ が「補完不能」と確定した pid を明示 list で持ち、依頼書生成前に落とす。
# 元依頼: catalog/requests 経由 _routed/2026-08-10_catalog_to_hq_auto_request_suppress_known_no_image.md
# 回答書: hq/requests/2026-08-10_catalog_auto_request_suppress_known_no_image_response.md
# 判定は HQ 側運用ロジック (=②) の欠陥のため、Catalog worktree 変更なし。


def _load_suppression(path: Path | None = None) -> dict[str, dict[str, dict]]:
    """A群 suppression list を読む。JSON 破損 / ファイル不在は空 dict (fail-safe)。

    構造: {category: {pid: {decided_at, reason, ref}}}
    schema 検証:
      - 未知カテゴリは受け入れる (将来カテゴリ追加時に手動追記できるように)
      - pid が空 or decided_at が不正 ISO 日付なら entry を落として警告
      - 全体を落とさない (1件壊れても他は活かす)
    """
    p = path if path is not None else SUPPRESSION_JSON
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:  # noqa: BLE001  JSON 破損等
        print(f"[warn] suppression list を読めない ({p.name}: {e}) → 空として続行")
        return {}
    if not isinstance(raw, dict):
        print(f"[warn] suppression list の構造が dict でない → 空として続行")
        return {}
    cleaned: dict[str, dict[str, dict]] = {}
    for category, entries in raw.items():
        if category.startswith("_"):  # `_comment` 等の meta キーは無視
            continue
        if not isinstance(entries, dict):
            print(f"[warn] suppression {category}: entries が dict でない → 無視")
            continue
        cat_out: dict[str, dict] = {}
        for pid, meta in entries.items():
            if not pid or not isinstance(pid, str):
                print(f"[warn] suppression {category}: 空 pid → 無視")
                continue
            if not isinstance(meta, dict):
                print(f"[warn] suppression {category}:{pid}: meta が dict でない → 無視")
                continue
            decided_at = str(meta.get("decided_at", "")).strip()
            try:
                datetime.date.fromisoformat(decided_at[:10])
            except Exception:
                print(f"[warn] suppression {category}:{pid}: decided_at 不正 ({decided_at!r}) → 無視")
                continue
            cat_out[pid.strip()] = meta
        if cat_out:
            cleaned[category] = cat_out
    return cleaned


def _filter_suppression(new_by_cat: dict[str, list[dict]],
                        unique: dict[tuple[str, str], dict] | None,
                        suppression: dict[str, dict[str, dict]]) -> int:
    """A群 suppression list に載る pid を new_by_cat + unique から取り除き、件数を返す。

    fail-closed 契約 (catalog_present と同じ運用):
      - pid が抽出できない (Case2 psa_to_csv 形式等) → 従来通り依頼 (silent drop しない)
      - suppression に無い pid → 従来通り依頼
      - **カテゴリ跨ぎで救わない**: pokemon の SM12-112 を one_piece の依頼で drop しない
      - **viewer_disagreement.log には書かない**: A群は disagreement ではなく HQ 確定 skip

    silent drop 防止: 落とした各行を print で必ず残す
    (`failclosed_must_skip_not_destructive` と対、`no_partial_shipping_with_todo` に沿う)。
    """
    if not suppression:
        return 0
    removed = 0
    for category, rows in list(new_by_cat.items()):
        cat_supp = suppression.get(category) or {}
        if not cat_supp:
            continue
        kept: list[dict] = []
        for r in rows:
            pid = _extract_expected_pid(r["model"])
            if not pid or pid not in cat_supp:
                kept.append(r)
                continue
            meta = cat_supp[pid]
            reason = str(meta.get("reason") or "(reason unset)")
            decided_at = str(meta.get("decided_at") or "?")
            if unique is not None:
                unique.pop((category, r["model"]), None)
            print(f"    ⏭️ Skip auto_catalog_add (A群 known_no_image): "
                  f"{category}:{pid} — {reason} (decided {decided_at})")
            removed += 1
        if kept:
            new_by_cat[category] = kept
        else:
            del new_by_cat[category]
    return removed


def _load_processed() -> set[tuple[str, str]]:
    if not PROCESSED_CSV.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    # ★2026-08-19: BOM 付きで書かれた行があると 1列目のキーが "﻿category" になり
    #   KeyError で watcher ごと止まる。読む側だけ utf-8-sig にする (書く側は触らない)。
    with PROCESSED_CSV.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            keys.add((r["category"], r["model"]))
    return keys


def _append_processed(rows: list[dict]) -> None:
    is_new = not PROCESSED_CSV.exists() or PROCESSED_CSV.stat().st_size == 0
    with PROCESSED_CSV.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["category", "model", "detected_at"])
        for r in rows:
            w.writerow([r["category"], r["model"], r["detected_at"]])


def _prune_old_missing(unique: dict[tuple[str, str], dict], max_age_days: int = 30,
                       today: str = "") -> int:
    """detected_at が max_age_days より古い行を unique から in-place 削除 (純関数寄り, test可)。
    戻り: 間引いた件数。today 未指定なら本日。ISO 日付の辞書順比較。"""
    if not today:
        today = datetime.date.today().strftime("%Y-%m-%d")
    try:
        cutoff = (datetime.date.fromisoformat(today[:10])
                  - datetime.timedelta(days=max_age_days)).isoformat()
    except Exception:
        return 0
    drop = [k for k, r in unique.items()
            if len((r.get("detected_at") or "")[:10]) == 10
            and r["detected_at"][:10] < cutoff]
    for k in drop:
        del unique[k]
    return len(drop)


def _rewrite_missing(unique: dict[tuple[str, str], dict]) -> None:
    """missing_models.csv を dedup 後の内容で書き戻す (= 容量管理)."""
    with MISSING_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category", "model", "detected_at"])
        for r in sorted(unique.values(), key=lambda x: (x["category"], x["model"])):
            w.writerow([r["category"], r["model"], r["detected_at"]])


def _write_request(out_path: Path, category: str, rows: list[dict]) -> None:
    today = datetime.date.today().strftime("%Y-%m-%d")
    label = CATEGORY_LABELS.get(category, category)
    rows_sorted = sorted(rows, key=lambda r: r["model"])
    table_body = "".join(
        f"| `{r['model']}` | {r['detected_at']} |\n" for r in rows_sorted
    )
    out_path.write_text(
        f"# 自動依頼: {label} カタログ追加 (auto-generated)\n\n"
        f"- **依頼日**: {today}\n"
        f"- **依頼者**: HQ Claude `auto_catalog_add_request.py`\n"
        f"- **緊急度**: 低 (= バッチ追加、 即時 NG)\n"
        f"- **フェーズ**: 本実装 (= 公式 ID 確定済の単純追加、 議論不要)\n"
        f"- **生成元**: `C:/dev/iMak_data/catalog/missing_models.csv` 新規行\n"
        f"- **判定**: **ユーザー判断スキップ済** "
        f"(= 「カタログ追加は確認なしに依頼」 合意 2026-05-25)\n\n"
        f"---\n\n"
        f"## 追加対象 ({len(rows_sorted)} models)\n\n"
        f"| model | detected_at |\n"
        f"|---|---|\n"
        f"{table_body}\n"
        f"---\n\n"
        f"## 依頼内容\n\n"
        f"上記 model を `{category}` カテゴリの Catalog DB に追加してください。\n\n"
        f"- 公式情報元のみ採用 (= Bandai TCG+ API / カシオ公式 / 各 supplier 公式)\n"
        f"- ID 完全一致 lookup で名称取得、 推測禁止 (= fail-closed 原則)\n"
        f"- 既存登録あれば「投入不要」 と報告 (= adapter 抽出 bug 等の構造問題を別途調査)\n"
        f"- 完了後 本依頼書を `_processed.md` rename + 短いレポート追加\n\n"
        f"## 自動運用注意\n\n"
        f"- 本依頼書は `auto_catalog_add_request.py` が自動生成 (= 純 Python、 Claude 未使用)\n"
        f"- 同日同 category の追加 detect は **本ファイル既存なら skip** (= 翌日新規 file)\n"
        f"- 議論要件 (= ranking logic / 既存修正 / specs 拡充) は本仕組み対象外、 "
        f"HQ から個別依頼書\n",
        encoding="utf-8",
    )


def main() -> int:
    if not MISSING_CSV.exists():
        print(f"no missing_models.csv at {MISSING_CSV}")
        return 0

    # 1. missing_models 全行読込 + (cat, model) dedup
    unique: dict[tuple[str, str], dict] = {}
    with MISSING_CSV.open(encoding="utf-8-sig") as f:   # BOM 付き行で止まらない (2026-08-19)
        for r in csv.DictReader(f):
            k = (r["category"], r["model"])
            if k not in unique or r["detected_at"] > unique[k]["detected_at"]:
                unique[k] = r

    # 1b. 長期滞留(detected_at > 30日)を間引き(K1・容量管理 + 再import停止)。
    # 30日経っても catalog 未追加 = 依頼済の構造案件(pdca 側で stale 退役済)。再 import で
    # seen_count を永遠に増やし続けるのを止める。新規検出が来れば detected_at 新でまた載る。
    pruned_old = _prune_old_missing(unique)
    if pruned_old:
        print(f"[prune] missing_models 古い行(>30日)を {pruned_old} 件間引き")

    # 2. 既処理と差分
    processed = _load_processed()
    new_by_cat: dict[str, list[dict]] = defaultdict(list)
    for k, r in unique.items():
        if k not in processed:
            new_by_cat[r["category"]].append(r)

    # 2a. 入口検査 (2026-08-19, 提案C): catalog が調べようのない依頼を起票しない
    skipped_invalid = _filter_invalid_entries(new_by_cat, unique)
    if skipped_invalid:
        print(f"[skip] 入口検査で {skipped_invalid} 件除外 → {REJECTED_LOG.name}")

    # 2b. catalog 実在 pre-check (18b36a2 と同じ fail-closed 契約, 2026-08-08)
    skipped_present = _filter_catalog_present(new_by_cat, unique)
    if skipped_present:
        print(f"[skip] catalog実在 pre-check で {skipped_present} 件除外 "
              f"→ viewer_disagreement.log")

    # 2b-2. resolver pre-check (2026-08-22): 別 id で catalog に在るものを落とす
    skipped_resolved = _filter_resolver_resolves(new_by_cat, unique)
    if skipped_resolved:
        print(f"[skip] resolver pre-check で {skipped_resolved} 件除外 "
              f"(catalog に別 id で在る)")

    # 2c. A群 suppression (公式が物理的に持たない pid → 毎日の再依頼を止める, 2026-08-10)
    suppression = _load_suppression()
    skipped_supp = _filter_suppression(new_by_cat, unique, suppression)
    if skipped_supp:
        print(f"[skip] A群 known_no_image で {skipped_supp} 件除外 "
              f"→ {SUPPRESSION_JSON.name}")

    # 3. category 別に依頼書投入
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().strftime("%Y-%m-%d")
    processed_now: list[dict] = []

    for category, rows in sorted(new_by_cat.items()):
        out_path = REQUESTS_DIR / f"{today}_auto_catalog_add_{category}.md"
        if out_path.exists():
            print(f"[skip] {out_path.name} 既存 (= 翌日新規 file 待ち)")
            continue
        _write_request(out_path, category, rows)
        processed_now.extend(rows)
        print(f"[create] {out_path.name} ({len(rows)} models)")

    if processed_now:
        _append_processed(processed_now)

    # 4. missing_models.csv を dedup 後の内容で rewrite (= 容量管理)
    _rewrite_missing(unique)

    if not new_by_cat:
        print("no new missing models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
