#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""有料 API (Anthropic) の呼び出しを1回ずつ記録する (2026-10-10)。

★ユーザー「出品・メンテ作業をするたびに API コストが掛かるのを何とか減らさないと」。
  API を呼んでいるプログラムは約18本あるが、どれがいくら使っているかが分からなかった
  (Anthropic の請求画面はキー単位で、プログラムの内訳が無い)。まず数える。

仕組み: Python の起動時に読まれる usercustomize.py から install_hook() を呼ぶ。anthropic が
import された時だけ Messages.create を包み、戻ってきた使用量 (トークン) をこのファイルの LOG に1行足す。
各プログラム (psa_to_csv など触れない物を含む) は1行も変えない。記録に失敗しても本体の処理は止めない。

    python api_cost_log.py            # 今日と直近7日の合計を、プログラム別に出す
    python api_cost_log.py install    # この PC の usercustomize.py に仕込む (KAGOYA でも同じ)
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time

_DEFAULT_LOG = r"C:/dev/iMak_data/hq/api_cost_log.jsonl"
LOG = os.environ.get("IMAK_API_COST_LOG") or _DEFAULT_LOG

# 100万トークンあたりのドル (入力, 出力)。モデル名の頭で当てる。無い物は金額を出さずトークンだけ残す
PRICES = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-sonnet-5": (3.0, 15.0),
}


def price_of(model):
    m = str(model or "")
    for k, v in PRICES.items():
        if m.startswith(k):
            return v
    return None


def cost_usd(model, usage):
    """使用量 → ドル (純関数)。単価が分からなければ None。キャッシュの読み=入力の1割・書き=1.25倍。"""
    p = price_of(model)
    if not p or not usage:
        return None
    pin, pout = p
    inp = usage.get("input_tokens") or 0
    out = usage.get("output_tokens") or 0
    cr = usage.get("cache_read_input_tokens") or 0
    cw = usage.get("cache_creation_input_tokens") or 0
    return round((inp * pin + cr * pin * 0.1 + cw * pin * 1.25 + out * pout) / 1e6, 6)


def _usage_dict(u):
    if u is None:
        return {}
    out = {}
    for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        v = getattr(u, k, None)
        if isinstance(v, int):
            out[k] = v
    return out


def caller_of(skip=("/anthropic/", "/api_cost_log.py", "/httpx/", "/functools.py")):
    """API を呼んだ側の「ファイル名:関数名」(何の処理か)。分からなければ ""。"""
    try:
        f = sys._getframe(1)
        while f is not None:
            fn = f.f_code.co_filename.replace("\\", "/")
            if not any(s in fn for s in skip):
                return "%s:%s" % (os.path.basename(fn), f.f_code.co_name)
            f = f.f_back
    except Exception:                                          # noqa: BLE001
        pass
    return ""


def count_images(messages):
    """送った画像の枚数 (純関数)。画像は高いので、何枚送っているかを残す。"""
    n = 0
    try:
        for m in messages or []:
            c = m.get("content") if isinstance(m, dict) else None
            for b in (c if isinstance(c, list) else []):
                if isinstance(b, dict) and b.get("type") == "image":
                    n += 1
    except Exception:                                          # noqa: BLE001
        pass
    return n


def record(model, usage, secs=None, where="", images=0):
    """1回分を LOG に足す (I/O)。失敗しても例外を出さない。テスト中は本物の LOG に書かない。"""
    if os.environ.get("PYTEST_CURRENT_TEST") and LOG == _DEFAULT_LOG:
        return
    try:
        prog = os.path.basename(sys.argv[0] or "") or "?"
        rec = {"at": _dt.datetime.now().isoformat(timespec="seconds"), "prog": prog,
               "args": " ".join(sys.argv[1:3])[:60], "model": str(model or ""),
               **usage, "usd": cost_usd(model, usage)}
        if secs is not None:
            rec["s"] = round(secs, 1)
        if where:
            rec["where"] = where
        if images:
            rec["img"] = images
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:                                          # noqa: BLE001
        pass


def install():
    """anthropic の Messages.create を包む (何度呼んでも1回だけ)。"""
    try:
        from anthropic.resources import messages as _m
    except Exception:                                          # noqa: BLE001
        return False
    cls = getattr(_m, "Messages", None)
    if cls is None or getattr(cls.create, "_imak_cost", False):
        return False
    orig = cls.create

    def create(self, *a, **kw):
        t0 = time.time()
        resp = orig(self, *a, **kw)
        try:
            record(getattr(resp, "model", None) or kw.get("model"), _usage_dict(getattr(resp, "usage", None)),
                   time.time() - t0, where=caller_of(), images=count_images(kw.get("messages")))
        except Exception:                                      # noqa: BLE001
            pass
        return resp

    create._imak_cost = True
    cls.create = create
    return True


class _AfterAnthropicImport:
    """anthropic が import された直後に install() を呼ぶ (それまで何もしない = 他のプログラムを遅くしない)。"""

    def find_spec(self, name, path=None, target=None):
        if name != "anthropic":
            return None
        try:
            sys.meta_path.remove(self)
        except ValueError:
            pass
        import importlib.util
        spec = importlib.util.find_spec(name)
        if spec is None or spec.loader is None:
            return spec
        orig_exec = spec.loader.exec_module

        def exec_module(module):
            orig_exec(module)
            install()

        spec.loader.exec_module = exec_module
        return spec


def install_hook():
    """usercustomize.py から呼ぶ。"""
    if "anthropic" in sys.modules:
        install()
    elif not any(isinstance(f, _AfterAnthropicImport) for f in sys.meta_path):
        sys.meta_path.insert(0, _AfterAnthropicImport())


USERCUSTOMIZE = '''# iMak: 有料 API の呼び出しを記録する (iMakHQ/tools/api_cost_log.py)。失敗しても何もしない
try:
    import sys as _s
    _s.path.append(r"%s")
    import api_cost_log as _acl
    _acl.install_hook()
    _s.path.remove(r"%s")
except Exception:
    pass
'''


def write_usercustomize():
    import site
    d = site.getusersitepackages()
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "usercustomize.py")
    here = os.path.dirname(os.path.abspath(__file__))
    body = USERCUSTOMIZE % (here, here)
    if os.path.exists(p):
        cur = open(p, encoding="utf-8").read()
        if "api_cost_log" in cur:
            print("既に仕込んである:", p)
            return p
        body = cur.rstrip() + "\n\n" + body
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    print("仕込んだ:", p)
    return p


def summarize(rows, since, by="prog"):
    """{prog (by="where" なら 処理): [回数, ドル, 金額不明の回数]} (純関数)。"""
    out = {}
    for r in rows:
        if (r.get("at") or "") < since:
            continue
        s = out.setdefault(r.get(by) or r.get("prog") or "?", [0, 0.0, 0])
        s[0] += 1
        if r.get("usd") is None:
            s[2] += 1
        else:
            s[1] += r["usd"]
    return out


def load(path=LOG):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:                              # noqa: BLE001
                    pass
    except OSError:
        pass
    return rows


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "install":
        write_usercustomize()
        return 0
    rows = load()
    today = _dt.date.today().isoformat()
    week = (_dt.date.today() - _dt.timedelta(days=6)).isoformat()
    for label, since in (("今日", today), ("直近7日", week)):
        s = summarize(rows, since, by="where")
        tot = sum(v[1] for v in s.values())
        print(f"💸 有料 API {label}: ${tot:.2f} / {sum(v[0] for v in s.values())}回")
        for prog, (n, usd, unk) in sorted(s.items(), key=lambda kv: -kv[1][1]):
            print(f"   {prog:28s} ${usd:7.2f}  {n}回" + (f" (単価不明 {unk}回)" if unk else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    sys.exit(main())
