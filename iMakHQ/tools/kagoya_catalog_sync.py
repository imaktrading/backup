"""カタログ DB の正本を KAGOYA に置いた後の、家との行き来 (2026-10-03 KAGOYA 移管 段階C)。

ユーザー確定 (10/3)「完全移行 OK」。この PC は1日7〜10回落ち、書いたファイルが化ける
(カタログ DB は 9/29〜10/3 に4回壊れた)。だから DB に**書く**のは KAGOYA だけにし、
家には読むだけの写しを置く。段取りはカタログ担当と合意済み
(catalog/requests/2026-10-03_catalog_db_master_switch_plan_response.md)。

1時間おき (kagoya_offload.py cycle の中) に:
  1. DB: KAGOYA で sqlite の backup を取り quick_check → 変わっていれば家に運び、quick_check ok なら差し替え
     (家で誰かが開いていて差し替えられない時は次の回。止めない)
  2. requests/ と catalog 直下の小さいファイル: 両方向に写す (後から変わった方が勝つ・消したのも伝える)
  3. 家の控え _replica_pending_writes.jsonl (写しに書こうとした分) を KAGOYA に運ぶ (KAGOYA で正本に流す)

offload.json の "db_master": "kagoya" の時だけ動く。それまでは今までどおり家 → KAGOYA に DB を送る。
"""
import datetime
import io
import json
import os
import sqlite3
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kagoya_offload as K  # noqa: E402

CAT = r"C:\dev\iMak_data\catalog"
LOCAL_DB = os.path.join(CAT, "products.sqlite")
REMOTE_DB = K.REMOTE_DB
REMOTE_SNAP = K.REMOTE_ROOT + r"\products_snapshot.sqlite"
PENDING = "_replica_pending_writes.jsonl"
REMOTE_PENDING_DIR = r"C:\dev\iMak_data\catalog\_replica_pending_writes_inbox"
MARKER = "_REPLICA_READ_ONLY"          # 家だけに置く印 (KAGOYA に写してはいけない)
SYNC_DIRS = ["requests", ""]           # "" = catalog 直下
MAX_SYNC_BYTES = 20 * 1024 * 1024
MTIME_SLACK = 2.0                      # 運んだ時の時刻の丸めの差は同じとみなす


def db_master_is_kagoya(cfg=None):
    return (cfg if cfg is not None else K._cfg()).get("db_master") == "kagoya"


# ---------------------------------------------------------------------------
# 純関数
# ---------------------------------------------------------------------------
def skip_name(name):
    """両方向の写しに入れないファイルか (純関数)。DB 本体と控え・家だけの印・控えの受け箱。"""
    n = name.lower()
    return (n.startswith("products.sqlite") or n == MARKER.lower() or n == PENDING.lower()
            or ".bak" in n or n.endswith((".tmp", ".lock", ".incoming", "-wal", "-shm", "-journal")))


def same(a, b):
    """同じ中身とみなすか (純関数)。a, b = [mtime, size] or None。"""
    if not a or not b:
        return False
    return a[1] == b[1] and abs(a[0] - b[0]) <= MTIME_SLACK


def plan_twoway(local, remote, last):
    """両方向の写しの段取り (純関数)。

    local / remote / last = {名前: [mtime, size]}。last = 前回そろえた時の状態 (両側同じ)。
    返り値 dict: push (家→KAGOYA) / pull (KAGOYA→家) / del_local / del_remote / conflicts
      - 片方だけ変わった → そちらを写す
      - 両方変わった → 新しい方を写し、conflicts に入れる (負けた方は呼び手が控えに残す)
      - 前回あった物が片方で消え、もう片方が前回のまま → 消したのを伝える
      - 前回に無く片方にだけある → 新しい物として写す
    """
    out = {"push": [], "pull": [], "del_local": [], "del_remote": [], "conflicts": []}
    for n in sorted(set(local) | set(remote)):
        if skip_name(n):
            continue
        lo, re, b = local.get(n), remote.get(n), last.get(n)
        if lo and re:
            if same(lo, re):
                continue
            lc, rc = not same(lo, b), not same(re, b)
            if lc and not rc:
                out["push"].append(n)
            elif rc and not lc:
                out["pull"].append(n)
            else:
                (out["push"] if lo[0] >= re[0] else out["pull"]).append(n)
                if b is not None:
                    out["conflicts"].append(n)
        elif lo:
            if b is None or not same(lo, b):
                out["push"].append(n)              # 新しい物 / KAGOYA で消されたが家で書き換えた
            else:
                out["del_local"].append(n)          # KAGOYA で消された (家は前回のまま)
        else:
            if b is None or not same(re, b):
                out["pull"].append(n)
            else:
                out["del_remote"].append(n)
    return out


def next_last(local, remote, plan):
    """そろえた後の状態 (純関数)。写した物は写し元の値、消した物は無し。"""
    res = {}
    for n in set(local) | set(remote):
        if skip_name(n) or n in plan["del_local"] or n in plan["del_remote"]:
            continue
        if n in plan["push"]:
            res[n] = local[n]
        elif n in plan["pull"]:
            res[n] = remote[n]
        elif n in local and n in remote:
            res[n] = local[n]
    return res


# ---------------------------------------------------------------------------
# 家の側
# ---------------------------------------------------------------------------
def _list_local(sub):
    d = os.path.join(CAT, sub) if sub else CAT
    out = {}
    if not os.path.isdir(d):
        return out
    for f in os.listdir(d):
        p = os.path.join(d, f)
        if os.path.isfile(p) and not skip_name(f):
            s = os.stat(p)
            if s.st_size <= MAX_SYNC_BYTES:
                out[f] = [round(s.st_mtime, 1), s.st_size]
    return out


def _list_remote(cfg, sub):
    d = CAT + ("\\" + sub if sub else "")
    ps = (f"if (Test-Path '{d}') {{ Get-ChildItem -LiteralPath '{d}' -File | ForEach-Object {{ "
          "($_.Name, ([DateTimeOffset]$_.LastWriteTimeUtc).ToUnixTimeMilliseconds(), $_.Length) -join [char]9 } }")
    rc, out = K._ssh(cfg, "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + ps, timeout=120)
    if rc != 0:
        raise RuntimeError(f"KAGOYA の一覧が取れない: {out[:200]}")
    res = {}
    for line in out.splitlines():
        parts = line.rstrip("\r").split("\t")
        if len(parts) != 3 or not parts[2].isdigit():
            continue
        name, ms, size = parts
        if skip_name(name) or int(size) > MAX_SYNC_BYTES:
            continue
        res[name] = [round(int(ms) / 1000.0, 1), int(size)]
    return res


def _tar_files(paths_arc, tgz):
    with tarfile.open(tgz, "w:gz", format=tarfile.PAX_FORMAT) as tf:
        for p, arc in paths_arc:
            tf.add(p, arcname=arc)


def _py_remote(cfg, code, timeout=600):
    """KAGOYA の python で短いコードを動かす (引用符で壊れないように一度ファイルに置く)。"""
    local = os.path.join(K.WORK, "catalog_sync_remote.py")
    os.makedirs(K.WORK, exist_ok=True)
    with open(local, "w", encoding="utf-8") as f:
        f.write(code)
    remote = K.REMOTE_ROOT + r"\catalog_sync_remote.py"
    if K._scp_to(cfg, local, remote) != 0:
        raise RuntimeError("KAGOYA に送れない")
    return K._ssh(cfg, f"& '{K.REMOTE_PY}' -X utf8 '{remote}'", timeout=timeout)


def sync_dir(cfg, st, sub, log=print):
    """requests/ や catalog 直下を両方向にそろえる。"""
    key = "catalog_sync_last:" + (sub or ".")
    last = st.get(key) or {}
    local, remote = _list_local(sub), _list_remote(cfg, sub)
    plan = plan_twoway(local, remote, last)
    ldir = os.path.join(CAT, sub) if sub else CAT
    rdir = CAT + ("\\" + sub if sub else "")
    os.makedirs(os.path.join(K.WORK, "catalog_sync"), exist_ok=True)
    work = os.path.join(K.WORK, "catalog_sync")
    # 負けた方を控えに残す (両方で書き換えた時)
    for n in plan["conflicts"]:
        if n in plan["pull"] and os.path.exists(os.path.join(ldir, n)):
            os.replace(os.path.join(ldir, n), os.path.join(ldir, n + f".conflict_home_{int(time.time())}"))
    if plan["push"]:
        tgz = os.path.join(work, "push.tgz")
        _tar_files([(os.path.join(ldir, n), n) for n in plan["push"]], tgz)
        if K._scp_to(cfg, tgz, K.REMOTE_ROOT + r"\catalog_push.tgz") != 0:
            raise RuntimeError("送れない")
        # Windows の tar は日本語の名前を通さない (カタログ担当 10/3) → python の tarfile で開く
        code = ("import tarfile, os\n"
                f"d = r'''{rdir}'''\n"
                "os.makedirs(d, exist_ok=True)\n"
                f"with tarfile.open(r'''{K.REMOTE_ROOT}\\catalog_push.tgz''') as tf:\n"
                "    tf.extractall(d)\n"
                "print('ok')\n")
        rc, out = _py_remote(cfg, code, timeout=300)
        if rc != 0 or "ok" not in out:
            raise RuntimeError(f"KAGOYA で展開できない: {out[:200]}")
    if plan["pull"]:
        names = json.dumps(plan["pull"], ensure_ascii=False)
        code = ("import tarfile, os, json\n"
                f"d = r'''{rdir}'''\n"
                f"names = json.loads(r'''{names}''')\n"
                f"with tarfile.open(r'''{K.REMOTE_ROOT}\\catalog_pull.tgz''', 'w:gz', format=tarfile.PAX_FORMAT) as tf:\n"
                "    for n in names:\n"
                "        p = os.path.join(d, n)\n"
                "        if os.path.isfile(p):\n"
                "            tf.add(p, arcname=n)\n"
                "print('ok')\n")
        rc, out = _py_remote(cfg, code)
        if rc != 0 or "ok" not in out:
            raise RuntimeError(f"KAGOYA で固められない: {out[:200]}")
        tgz = os.path.join(work, "pull.tgz")
        if K._scp_from(cfg, K.REMOTE_ROOT + r"\catalog_pull.tgz", tgz) != 0:
            raise RuntimeError("受け取れない")
        os.makedirs(ldir, exist_ok=True)
        with tarfile.open(tgz) as tf:
            tf.extractall(ldir)
    for n in plan["del_local"]:
        try:
            os.remove(os.path.join(ldir, n))
        except OSError:
            pass
    if plan["del_remote"]:
        names = json.dumps(plan["del_remote"], ensure_ascii=False)
        code = ("import os, json\n"
                f"d = r'''{rdir}'''\n"
                f"for n in json.loads(r'''{names}'''):\n"
                "    try:\n        os.remove(os.path.join(d, n))\n    except OSError:\n        pass\n"
                "print('ok')\n")
        _py_remote(cfg, code)
    st[key] = next_last(_list_local(sub), _list_remote(cfg, sub), {"push": [], "pull": [], "del_local": [],
                                                                   "del_remote": [], "conflicts": []})
    n = {k: len(v) for k, v in plan.items() if v}
    if n:
        log(f"  🔁 catalog/{sub or '.'}: " + " / ".join(f"{k} {v}" for k, v in n.items()))
    return plan


def local_db_healthy(path):
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        try:
            return c.execute("pragma quick_check").fetchone()[0] == "ok"
        finally:
            c.close()
    except Exception:                                          # noqa: BLE001
        return False


def pull_db(cfg, st, log=print):
    """KAGOYA の正本の写しを家に持ってくる (変わった時だけ)。返り値: 差し替えたか。"""
    code = ("import sqlite3, os, json, hashlib\n"
            f"db = r'''{REMOTE_DB}'''\n"
            f"snap = r'''{REMOTE_SNAP}'''\n"
            # 読むだけでも -wal の時刻は動く (開いた時に作られる) → 本体の時刻と大きさ + -wal の大きさで見る
            "s = os.stat(db)\n"
            "try:\n    w = os.stat(db + '-wal').st_size\n"
            "except OSError:\n    w = 0\n"
            "sig = [round(s.st_mtime, 1), s.st_size, w]\n"
            "src = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=60)\n"
            "ver = src.execute('select count(*), max(rowid) from products').fetchone()\n"
            "print('SIG', json.dumps([sig, ver]))\n")
    rc, out = _py_remote(cfg, code, timeout=300)
    line = next((x for x in out.splitlines() if x.startswith("SIG ")), None)
    if rc != 0 or not line:
        raise RuntimeError(f"KAGOYA の DB を見られない: {out[:300]}")
    sig = json.loads(line[4:])
    if st.get("catalog_db_pulled_sig") == sig and os.path.exists(LOCAL_DB):
        return False
    code = ("import sqlite3, os\n"
            f"db = r'''{REMOTE_DB}'''\n"
            f"snap = r'''{REMOTE_SNAP}'''\n"
            "try:\n    os.remove(snap)\nexcept OSError:\n    pass\n"
            "src = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=60)\n"
            "dst = sqlite3.connect(snap)\n"
            "src.backup(dst)\n"
            "dst.execute('pragma journal_mode=delete')\n"
            "ok = dst.execute('pragma quick_check').fetchone()[0]\n"
            "n = dst.execute('select count(*) from products').fetchone()[0]\n"
            "dst.close(); src.close()\n"
            "print('SNAP', ok, n)\n")
    rc, out = _py_remote(cfg, code, timeout=900)
    line = next((x for x in out.splitlines() if x.startswith("SNAP ")), "")
    if rc != 0 or " ok " not in line + " ":
        raise RuntimeError(f"KAGOYA の DB の写しが取れない / quick_check NG: {out[-300:]}")
    n_remote = int(line.split()[-1])
    inc = LOCAL_DB + ".incoming"
    if K._scp_from(cfg, REMOTE_SNAP, inc, timeout=1800) != 0:
        raise RuntimeError("DB を受け取れない")
    if not local_db_healthy(inc):
        os.remove(inc)
        raise RuntimeError("受け取った DB の quick_check が NG (運ぶ途中で化けた) → 次の回にやり直す")
    try:
        os.replace(inc, LOCAL_DB)
    except PermissionError:
        log("  ⏸ 家の DB を誰かが開いているので差し替えは次の回 (受け取った物は .incoming に残した)")
        return False
    for ext in ("-wal", "-shm"):
        try:
            os.remove(LOCAL_DB + ext)          # 前の DB の名残 (新しい DB に当たると壊す)
        except OSError:
            pass
    st["catalog_db_pulled_sig"] = sig
    st["catalog_db_pulled_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    log(f"  📥 カタログ DB の写しを KAGOYA から取った ({n_remote}行・quick_check ok)")
    return True


def push_pending(cfg, log=print):
    """家で写しに書こうとした分 (控え) を KAGOYA の受け箱へ。送れたら家の控えは空にする。"""
    p = os.path.join(CAT, PENDING)
    if not os.path.isfile(p) or os.path.getsize(p) == 0:
        return 0
    tmp = p + f".sending_{int(time.time())}"
    os.replace(p, tmp)                      # 送っている間に足された分は新しいファイルへ
    name = f"home_{datetime.datetime.now():%Y%m%d_%H%M%S}.jsonl"
    K._ssh(cfg, f"New-Item -ItemType Directory -Force '{REMOTE_PENDING_DIR}' | Out-Null; 'ok'")
    if K._scp_to(cfg, tmp, REMOTE_PENDING_DIR + "\\" + name) != 0:
        # 送れなければ戻す (前に足す)
        with open(tmp, "rb") as f:
            data = f.read()
        if os.path.exists(p):
            with open(p, "rb") as f:
                data += f.read()
        with open(p, "wb") as f:
            f.write(data)
        os.remove(tmp)
        raise RuntimeError("控えを送れない")
    n = sum(1 for _ in open(tmp, encoding="utf-8", errors="replace"))
    os.remove(tmp)
    log(f"  📤 写しへの書き込みの控え {n}件を KAGOYA へ ({name})")
    return n


def catalog_sync(cfg, st, log=print):
    """1時間おきの本体。どこかで失敗しても他は続ける。"""
    if not db_master_is_kagoya(cfg):
        return
    for name, fn in (("DB", lambda: pull_db(cfg, st, log)),
                     ("依頼書", lambda: sync_dir(cfg, st, "requests", log)),
                     ("データ", lambda: sync_dir(cfg, st, "", log)),
                     ("控え", lambda: push_pending(cfg, log))):
        try:
            fn()
        except Exception as e:                                 # noqa: BLE001
            log(f"  ⚠️要対応: カタログの{name}の行き来に失敗 ({type(e).__name__}: {e})")
            st.setdefault("catalog_sync_errors", []).append(
                f"{datetime.datetime.now():%m/%d %H:%M} {name}: {str(e)[:120]}")
            st["catalog_sync_errors"] = st["catalog_sync_errors"][-20:]


def main():
    cfg, st = K._cfg(), K._state()
    if "--force" not in sys.argv and not db_master_is_kagoya(cfg):
        print("db_master が kagoya ではない → 何もしない")
        return 0
    catalog_sync(dict(cfg, db_master="kagoya"), st)
    K._save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
