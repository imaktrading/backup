# -*- coding: utf-8 -*-
"""CLAUDE.md が実装とズレたら commit を止める (2026-08-15)。

★なぜ要るか (ユーザー指示「実態に合わせよう」→「それもやろうよ」):
  2026-08-15 に実機照合したら **13か所**がズレていた。4月のフォルダ移行、6月の役割分担、
  8月の相場停止を、どれも文書に反映していなかった。直しても**同期する仕組みが無い**ので
  必ずまた古くなる。→ 「実装を見れば分かること」は**テストで縛る**。

ここで縛るのは **実装から機械的に確かめられる事実だけ**。方針や運用の意図は縛らない
(それは人が決めること)。落ちたら文書か実装のどちらかが古い。
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess

_ROOT = r"C:\dev\iMak"
_GLOBAL = r"C:\Users\imax2\.claude\CLAUDE.md"


def _docs():
    """検査対象の CLAUDE.md 一式 (グローバル + 各プロジェクト)。"""
    out = [_GLOBAL] if os.path.exists(_GLOBAL) else []
    out += sorted(glob.glob(os.path.join(_ROOT, "*", "CLAUDE.md")))
    return out


def _lines(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return [(i, l.rstrip()) for i, l in enumerate(f.read().splitlines(), 1)]


def test_no_v5_shipping_profile_names():
    """送料 Policy は `DDP-{group}-P{tier}`。V5 時代の `<39, 40-60, …` を手順として書かない。

    実CSV: DDP-A-P19 (TCG/G-shock/一番くじ) / DDP-B-P16 (Porter) / DDP-C-P06 (Tシャツ)。
    """
    bad = []
    for p in _docs():
        for i, l in _lines(p):
            if re.search(r"ShippingProfileName[^\n]*<39|価格帯に応じた\s*ShippingProfileName", l):
                if "訂正" in l or "V5" in l:      # 経緯として言及するのは可
                    continue
                bad.append(f"{os.path.basename(os.path.dirname(p))}:{i}: {l.strip()[:70]}")
    assert not bad, "V5 時代の送料 Policy 名が手順として残っている:\n" + "\n".join(bad)


def test_no_onedrive_path_as_instruction():
    """作業ルートは C:\\dev\\iMak (2026-04-25 移行)。OneDrive 側の **iMak_workspace** には
    同名の旧ファイルが残っており、読むと実装と食い違う。

    ★縛るのは `OneDrive\\...\\iMak_workspace\\` を指す行だけ。OneDrive 上にしか無い資産
      (店舗ロゴ等) や、移行の経緯としての言及は対象外 (実在するものを禁止しない)。
    """
    bad = []
    for p in _docs():
        for i, l in _lines(p):
            if "iMak_workspace" not in l:
                continue
            if any(k in l for k in ("参照しない", "訂正", "旧パス", "当面保持", "削除はユーザー")):
                continue
            bad.append(f"{os.path.basename(os.path.dirname(p))}:{i}: {l.strip()[:70]}")
    assert not bad, "OneDrive の旧プロジェクトパスが指示として残っている:\n" + "\n".join(bad)


def test_market_gate_docs_match_the_switch():
    """相場が止まっているなら、文書に「NO-GO 行を CSV から削除してから入稿」を残さない。"""
    y = os.path.join(_ROOT, "iMakeBayAPI", "config", "global.yaml")
    src = open(y, encoding="utf-8").read()
    m = re.search(r"market_lookup:\s*\n\s*enabled:\s*(\w+)", src)
    assert m, "global.yaml に market_lookup が無い"
    if m.group(1).lower() == "true":
        return                                   # 相場を戻したなら手順も戻ってよい
    bad = []
    for p in _docs():
        for i, l in _lines(p):
            if "NO-GO" in l and "物理削除" in l and "停止" not in l:
                bad.append(f"{os.path.basename(os.path.dirname(p))}:{i}: {l.strip()[:70]}")
    assert not bad, "相場は停止中なのに、市場ゲートの手順が残っている:\n" + "\n".join(bad)


def test_worktree_table_matches_git():
    """グローバルの worktree 表の branch が実機と一致する。"""
    out = subprocess.run(["git", "worktree", "list"], cwd=_ROOT, capture_output=True,
                         text=True, encoding="utf-8", errors="replace").stdout
    live = dict(re.findall(r"^(\S+)\s+\S+\s+\[([^\]]+)\]", out, re.M))
    live = {os.path.basename(k.rstrip("/\\")).lower(): v for k, v in live.items()}
    doc = open(_GLOBAL, encoding="utf-8", errors="replace").read()
    checks = {"imak_catalog": "Catalog", "imak_inventory": "Inventory",
              "imak_harvest": "Harvest", "imak_revise": "Revise", "imak_dedupe": "Dedupe"}
    bad = []
    for folder, label in checks.items():
        br = live.get(folder)
        if br and br not in doc:
            bad.append(f"{label}: 実機 branch '{br}' が文書に無い")
    assert not bad, "worktree 表が実機とズレている:\n" + "\n".join(bad)


def test_paths_referenced_by_docs_exist():
    """文書が名指しする道具が実在する (消えた道具を手順に残さない)。"""
    must = [
        os.path.join(_ROOT, "iMakHQ", "tools", "status_now.py"),
        os.path.join(_ROOT, "iMakHQ", "tools", "claim.py"),
        os.path.join(_ROOT, "iMakAudit", "gemini_verifier.py"),
        os.path.join(_ROOT, "iMakKeywords"),
        r"C:\Users\imax2\.claude\agents\implementation-auditor.md",
    ]
    missing = [p for p in must if not os.path.exists(p)]
    assert not missing, "文書が指す道具が無い:\n" + "\n".join(missing)


def test_audit_doc_mentions_second_pass():
    """監査は Claude → Gemini の2段階。監査部隊自身の文書に手順が無いと一次で終わる
    (2026-08-15: 実際に抜けていた)。"""
    p = os.path.join(_ROOT, "iMakAudit", "CLAUDE.md")
    src = open(p, encoding="utf-8", errors="replace").read()
    assert "gemini_verifier.py" in src, "iMakAudit の文書に Gemini 二次監査が書かれていない"


def test_tcg_description_claim_matches_code():
    """TCG の Description に Specs ブロックを入れるかどうか、文書と実装を一致させる。"""
    code = open(os.path.join(_ROOT, "iMakTCG", "psa_to_csv.py"),
                encoding="utf-8", errors="replace").read()
    inserts = "insert_tcg_specs(" in code
    doc = open(_GLOBAL, encoding="utf-8", errors="replace").read()
    says_none = "Specificationsブロック挿入はなし" in doc
    assert not (inserts and says_none), "実装は Specs を挿入しているのに、文書は『挿入なし』"
