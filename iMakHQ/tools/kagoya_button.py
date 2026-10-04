"""神風のボタンを KAGOYA で動かす (2026-10-02 KAGOYA 移管 段階B・組①②)。

ユーザー確定「神風 (画面) はこの PC、ボタンの裏の処理は KAGOYA」。
ボタン1回ごとに、家の控えを送る → KAGOYA で動かす → KAGOYA で変わったファイルだけを家に取り込む。

  - 正本は家のまま (夜の束・急ぎの探索の取り込みも家に書く)。送った時点の写し (base) と
    KAGOYA の結果と家の今を3つ比べて、KAGOYA で変わった所だけ家に書く
    (ボタンが走っている間に家で書かれた分を消さない)
  - KAGOYA に届かない / 席が取れない時は **家で今までどおり動かす** (出品を止めない)
  - 目視の画面は KAGOYA が決まった番号 (18765) で出し、ssh -L の中継でこの PC のブラウザで開く
    (「ブラウザで確認してください →」の行を神風が見て開く)

使い方 (家・神風から):
  python kagoya_button.py --cwd <dir> [--env K=V ...] -- <script.py> [args...]
KAGOYA の側 (ssh 越しに上の手順が呼ぶ):
  python kagoya_button.py remote-run --cwd <dir> --out <dir> [--env K=V ...] -- <script.py> [args...]
"""
import datetime
import io
import json
import os
import subprocess
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kagoya_offload as K  # noqa: E402

DEV = r"C:/dev"
# 送る控え (家 → KAGOYA)。どれも家が正本で、合計 15MB ほど (2026-10-02 実測)
PUSH_DIRS = [
    r"C:/dev/iMak_data/hq",
    r"C:/dev/iMak_data/dedupe",
    r"C:/dev/iMak/iMakHQ/tools",
    r"C:/dev/iMak/iMakHQ/review_logs",
    r"C:/dev/iMak/iMakTCG/data",
]
PUSH_EXT = (".json", ".jsonl", ".txt", ".csv")   # txt/csv: 除外リスト等 (2026-10-02 補充の除外4件が KAGOYA で効かなかった)
FUNNEL_DIR = r"C:/dev/iMak/iMakHQ/funnel_output"     # 並び順に使う最新のファネル (1本だけ)
# 下の階層で読む物 (2026-10-02 試走で家と食い違った: 市場で売れた実績の台帳が無く並び順が変わった)
PUSH_EXTRA = [
    r"C:/dev/iMak_data/hq/market_sold/ledger.csv",
    r"C:/dev/iMak_data/hq/exposure_watch/swap_priority.json",
    r"C:/dev/iMak_data/hq/night_state/hoju.json",
    r"C:/dev/iMak_data/hq/night_state/psawarm.json",
    r"C:/dev/iMak_data/hq/night_state/weekly.json",
]
# 読むだけの控えの山 (eBay から取った出品の控え 約2,200本・65MB)。初回に全部、あとは増えた・変わった分だけ送る
MIRROR_DIRS = [r"C:/dev/iMak_data/hq/market_sold/getitem",
               # ★2026-10-03 PSA 新規: PSA の cert の控え (約2,500本・1.3MB)。KAGOYA で足された分は SCAN_ROOTS で戻る
               r"C:/dev/iMak/iMakeBayAPI/cache/psa_certs"]
# 絵柄の照合などが読む鍵 (KAGOYA の鍵は credentials に置いてある・中身は家と同じを確認済)
REMOTE_KEY_COPY = (r"C:\dev\iMak_data\credentials\api_key.txt", r"C:\dev\iMak\iMakTCG\API key.txt")
# 取り込む場所 (KAGOYA でボタンの間に変わったファイルを探す)。抽出くん等の置き場は入れない
# ★2026-10-02: 家のデスクトップを名指しで書く道具がある (03_PSA再仕入れ候補_*.csv 等)。
#   KAGOYA にも同じ場所を作って書かせ、書いた物は家の同じ場所に戻す (C:\dev の外は "ABS/C/..." で運ぶ)
HOME_DESK = r"C:\Users\imax2\OneDrive\デスクトップ"
SCAN_ROOTS = [
    r"C:\dev\iMak_data\hq",
    r"C:\dev\iMak_data\dedupe",
    r"C:\dev\iMak\iMakHQ",
    r"C:\dev\iMak\iMakTCG\data",
    r"C:\dev\iMak\iMakeBayAPI\cache",
    HOME_DESK,
]
SKIP_EXT = (".py", ".pyc", ".log", ".tgz", ".tmp", ".lock")
SKIP_DIR_WORDS = ("__pycache__", "profile", "offload_work", "run_logs", ".git")
MAX_PULL_BYTES = 50 * 1024 * 1024
REMOTE_OUT = K.REMOTE_ROOT + r"\button"
BTN_NEED_GB = 1.2
BTN_SEAT = "BUTTON"


_MISSING = object()


# ---------------------------------------------------------------------------
# 3つ比べて取り込む (純関数)
# ---------------------------------------------------------------------------
def merge_dict(base, srv, home):
    """KAGOYA で変わった項目だけを home に当てる。返り値 (結果, 当てた数, ぶつかった数)。

    - KAGOYA で足された / 変わった項目 → 書く (家でも同じ項目が別の値に変わっていたら KAGOYA を優先し、数える)
    - KAGOYA で消された項目 → 家でその項目が送った時のままなら消す (家で書き換えていたら残す)
    """
    base, srv, out = base or {}, srv or {}, dict(home or {})
    applied = conflicts = 0
    for k, v in srv.items():
        if k in base and base[k] == v:
            continue
        if k in out and out[k] != v and out[k] != base.get(k, _MISSING):
            conflicts += 1                         # 家でも同じ項目が別の値に変わっていた
        if out.get(k, object()) != v:
            out[k] = v
            applied += 1
    for k in base:
        if k not in srv and k in out and out[k] == base[k]:
            del out[k]
            applied += 1
    return out, applied, conflicts


def merge_bytes(base, srv, home):
    """ファイル丸ごとの比べ方。返り値 (書く中身 or None=家のまま, ぶつかったか)。

    base / home は None = 無い。家が送った時のまま → KAGOYA の物。KAGOYA が送った時のまま → 家のまま。
    両方変わっていたら KAGOYA を優先する (ボタンでユーザーが決めた結果) が、ぶつかったと返す。
    """
    if srv == base or srv == home:
        return None, False
    if home == base:
        return srv, False
    return srv, True


def merge_jsonl(base, srv, home):
    """追記型の控え。KAGOYA で後ろに足された行だけを家の後ろに足す。書き直されていたら丸ごとの比べ方。"""
    b = base or b""
    if srv.startswith(b):
        extra = srv[len(b):]
        if not extra:
            return None, False
        h = home if home is not None else b
        if h and not h.endswith(b"\n"):
            h += b"\n"
        return h + extra, False
    return merge_bytes(base, srv, home)


def _loads(b):
    return json.loads(b.decode("utf-8-sig"))


def merge_file(path, base, srv, home):
    """1ファイル分の取り込み。返り値 (書く中身 or None, 表示用の一言, ぶつかったか)。"""
    if path.lower().endswith(".jsonl"):
        out, c = merge_jsonl(base, srv, home)
        # 後ろに足されただけなら「追記」、KAGOYA で書き直されていたら (目視待ちを消した等)「丸ごと」
        return out, ("追記" if srv.startswith(base or b"") else "丸ごと"), c
    if path.lower().endswith(".json"):
        try:
            bj = _loads(base) if base is not None else {}
            sj, hj = _loads(srv), (_loads(home) if home is not None else {})
        except ValueError:
            out, c = merge_bytes(base, srv, home)
            return out, "丸ごと", c
        if isinstance(sj, dict) and isinstance(bj, dict) and isinstance(hj, dict):
            out, n, c = merge_dict(bj, sj, hj)
            if not n:
                return None, "変化なし", False
            indent = 1 if b"\n " in srv[:4000] else None
            return (json.dumps(out, ensure_ascii=False, indent=indent).encode("utf-8"),
                    f"{n}項目", c > 0)
    out, c = merge_bytes(base, srv, home)
    return out, "丸ごと", c


# ---------------------------------------------------------------------------
# 家の側
# ---------------------------------------------------------------------------
def _read(p):
    try:
        with open(p, "rb") as f:
            return f.read()
    except OSError:
        return None


def _push_files():
    files = []
    for d in PUSH_DIRS:
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if f.endswith(PUSH_EXT) and os.path.isfile(p):
                files.append(p)
    files += [p for p in PUSH_EXTRA if os.path.isfile(p)]
    try:
        hits = [os.path.join(FUNNEL_DIR, f) for f in os.listdir(FUNNEL_DIR)
                if f.startswith("funnel_") and f.endswith(".csv")]
        if hits:
            files.append(max(hits, key=os.path.getmtime))
    except OSError:
        pass
    return files


def carry_name(p):
    """KAGOYA から運ぶ時の名前 (純関数)。C:\\dev の下は相対、それ以外は "ABS/C/..."。"""
    p = os.path.normpath(p)
    dev = os.path.normpath(DEV)
    if p.lower().startswith(dev.lower() + os.sep):
        return os.path.relpath(p, dev).replace(os.sep, "/")
    drive, rest = os.path.splitdrive(p)
    return "ABS/" + drive.rstrip(":") + rest.replace(os.sep, "/")


def home_path(name):
    """carry_name の逆 (純関数)。"""
    if name.startswith("ABS/"):
        d, rest = name[4:].split("/", 1)
        return os.path.normpath(d + ":/" + rest)
    return os.path.normpath(os.path.join(DEV, name))


def _rel(p):
    return os.path.relpath(p, DEV).replace(os.sep, "/")


def mirror_todo(sent, files):
    """前に送った時から増えた・変わった物だけ (純関数)。sent / files は {名前: mtime}。"""
    return sorted(k for k, m in files.items() if sent.get(k) != m)


SYNC_TOKENS = [r"C:/dev/iMak_data/credentials/ebay_oauth_token_sell.json"]


def token_fingerprint(data):
    """鍵ファイルの「認可の版」(refresh_token の要約)。読めなければ None (純関数)。"""
    import hashlib
    try:
        rt = json.loads(data.decode("utf-8-sig")).get("refresh_token") or ""
    except Exception:                                          # noqa: BLE001
        return None
    return hashlib.sha256(rt.encode()).hexdigest()[:16] if rt else None


def push(cfg, run_dir, st=None):
    """家の控えを送る。送った中身は run_dir/base に残す (取り込みの比べる元)。"""
    base_dir = os.path.join(run_dir, "base")
    tgz = os.path.join(run_dir, "push.tgz")
    n = 0
    st = st if st is not None else {}
    with tarfile.open(tgz, "w:gz") as tf:
        for d in MIRROR_DIRS:
            if not os.path.isdir(d):
                continue
            files = {f: os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d)
                     if os.path.isfile(os.path.join(d, f))}
            sent = st.setdefault("button_mirror", {}).setdefault(_rel(d), {})
            for f in mirror_todo(sent, files):
                tf.add(os.path.join(d, f), arcname=_rel(os.path.join(d, f)))
                sent[f] = files[f]
        for p in _push_files():
            data = _read(p)
            if data is None:
                continue
            rel = _rel(p)
            bp = os.path.join(base_dir, rel)
            os.makedirs(os.path.dirname(bp), exist_ok=True)
            with open(bp, "wb") as f:
                f.write(data)
            ti = tarfile.TarInfo(rel)
            ti.size = len(data)
            ti.mtime = os.path.getmtime(p)         # 展開した時に今の時刻や 1970 にしない
            tf.addfile(ti, io.BytesIO(data))
            n += 1
        # eBay の鍵 (認可をやり直すと中身の refresh_token が変わる)。変わった時だけ KAGOYA にも送る。
        # 家に戻すことはしない (KAGOYA が自分で取り直す使い捨ての access_token は家に要らない)
        for p in SYNC_TOKENS:
            fp = token_fingerprint(_read(p))
            if fp and st.get("token_sent:" + os.path.basename(p)) != fp:
                tf.add(p, arcname=_rel(p))
                st["token_sent:" + os.path.basename(p)] = fp
    if K._scp_to(cfg, tgz, K.REMOTE_ROOT + r"\button_push.tgz") != 0:
        raise RuntimeError("控えを送れなかった")
    src, dst = REMOTE_KEY_COPY
    rc, out = K._ssh(cfg, rf'tar -xzf {K.REMOTE_ROOT}\button_push.tgz -C C:\dev; '
                          rf'if (-not (Test-Path "{dst}")) {{ Copy-Item "{src}" "{dst}" }}; "ok"')
    if rc != 0 or "ok" not in out:
        raise RuntimeError(f"控えの展開に失敗: {out[:200]}")
    return n


def _q(s):
    return "'" + str(s).replace("'", "''") + "'"


def remote_ssh_cmd(cfg, cwd, envs, args):
    """KAGOYA で remote-run を起こす ssh のコマンド (list)。目視の画面の番号を中継する。"""
    script = rf"{K.REMOTE_CODE_ROOT}\iMakHQ\tools\kagoya_button.py"
    env_args = " ".join("--env " + _q(e) for e in envs)
    remote = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
              "$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUNBUFFERED='1'; "
              f"& {_q(K.REMOTE_PY)} -X utf8 -u {_q(script)} remote-run --cwd {_q(cwd.replace('/', chr(92)))} "
              f"--out {_q(REMOTE_OUT)} {env_args} -- " + " ".join(_q(a) for a in args)
              # ★2026-10-03: PowerShell は python の終了コードをそのまま返さない → 「席が取れない (75)」が
              #   家に届かず、家で動かす代わりに失敗で止まった。明示して返す
              + "; exit $LASTEXITCODE")
    port = 18765
    return ["ssh", "-i", cfg["key"], "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "LogLevel=ERROR",
            "-o", "ServerAliveInterval=30", "-o", "ExitOnForwardFailure=yes",
            "-L", f"{port}:127.0.0.1:{port}",
            # 一番くじの再仕入れ① は自前の画面を決まった番号 (8766) で出す (ichibankuji_restock.PORT)
            "-L", "8766:127.0.0.1:8766", f"{cfg['user']}@{cfg['host']}", remote]


def pull_and_merge(cfg, run_dir):
    """KAGOYA で変わったファイルを取りに行き、家に当てる。返り値 (manifest, 当てた本数, ぶつかり)。"""
    lt = os.path.join(run_dir, "out.tgz")
    if K._scp_from(cfg, REMOTE_OUT + r"\out.tgz", lt) != 0:
        raise RuntimeError("結果を受け取れなかった")
    srv_dir = os.path.join(run_dir, "srv")
    with tarfile.open(lt) as tf:
        tf.extractall(srv_dir)
    man = json.load(open(os.path.join(srv_dir, "manifest.json"), encoding="utf-8"))
    wrote, conflicts = [], []
    for rel in man.get("files", []):
        srv = _read(os.path.join(srv_dir, "files", rel))
        if srv is None:
            continue
        home_p = home_path(rel)
        base = None if rel.startswith("ABS/") else _read(os.path.join(run_dir, "base", rel))
        home = _read(home_p)
        out, how, c = merge_file(home_p, base, srv, home)
        if c:
            conflicts.append(rel)
            if home is not None:
                with open(os.path.join(run_dir, "home_" + rel.replace("/", "__")), "wb") as f:
                    f.write(home)
        if out is None:
            continue
        os.makedirs(os.path.dirname(home_p), exist_ok=True)
        tmp = home_p + ".kagoya_tmp"
        with open(tmp, "wb") as f:
            f.write(out)
        os.replace(tmp, home_p)
        wrote.append(f"{rel} ({how})")
    return man, wrote, conflicts


KEEP_RUNS = 5          # 1回 約20MB (送った写し + 戻ってきた物)。ぶつかった時の家の分もここに残る


def prune_runs(root, keep=KEEP_RUNS):
    """古い回の作業フォルダを消す (新しい keep 回は残す)。"""
    import shutil
    try:
        names = sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)))
    except OSError:
        return
    for n in names[:-keep] if keep else names:
        shutil.rmtree(os.path.join(root, n), ignore_errors=True)


def run_local(cwd, envs, args):
    """家で動かす (KAGOYA に届かない・席が無い時)。

    ★2026-10-03: subprocess.call で出力をそのまま受け継がせていたら、神風の画面と記録に何も出なかった
      (PSA 自動 27件出品・補URL③ 30分の走行がどちらも始まりと終わりだけ)。KAGOYA の時と同じく1行ずつ中継する。
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
               **dict(e.split("=", 1) for e in envs))
    p = subprocess.Popen([sys.executable, "-X", "utf8", "-u"] + args, cwd=cwd, env=env, creationflags=K.NOWIN,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", bufsize=1)
    for line in p.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
    return p.wait()


def home_main(cwd, envs, args):
    try:
        cfg = K._cfg()
        rc, out = K._ssh(cfg, 'Write-Output ok', timeout=40)
        if rc != 0 or "ok" not in out:
            raise RuntimeError("KAGOYA に届かない")
        st = K._state()
        K.sync_code_and_db(cfg, st)
        K._save_state(st)
        prune_runs(os.path.join(K.WORK, "button"))
        run_dir = os.path.join(K.WORK, "button", datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.makedirs(run_dir, exist_ok=True)
        n = push(cfg, run_dir, st)
        K._save_state(st)
    except Exception as e:                                     # noqa: BLE001
        print(f"🏠 KAGOYA で動かせないので家で動かします ({e})", flush=True)
        return run_local(cwd, envs, args)
    print(f"🛰 KAGOYA で動かします (控え {n}本を送った)", flush=True)
    p = subprocess.Popen(remote_ssh_cmd(cfg, cwd, envs, args), stdout=subprocess.PIPE, creationflags=K.NOWIN,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
    seen = []
    for line in p.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        seen.append(line)
    rc = p.wait()
    if rc == 75:
        print("🏠 KAGOYA の席が空いていないので家で動かします", flush=True)
        return run_local(cwd, envs, args)
    try:
        man, wrote, conflicts = pull_and_merge(cfg, run_dir)
    except Exception as e:                                     # noqa: BLE001
        print(f"⚠️要対応: KAGOYA の結果を家に取り込めなかった ({e})。"
              f"KAGOYA の {REMOTE_OUT} に残っています", flush=True)
        return rc or 1
    print(f"📥 家に取り込んだ {len(wrote)}本" + (": " + " / ".join(wrote) if wrote else ""), flush=True)
    if conflicts:
        print(f"⚠️ 家でも同じ時に書かれていた {len(conflicts)}本 (KAGOYA を優先・家の分は {run_dir} に保存): "
              + " / ".join(conflicts), flush=True)
    # ★2026-10-04: KAGOYA で作った画面 (HTML・スプシ) を、取り込んだ後に家のブラウザで開く (home_open)
    try:
        import home_open as HO
        HO.open_targets(HO.targets_in(seen))
    except Exception as e:                                     # noqa: BLE001
        print(f"⚠️ 画面を家で開けませんでした ({type(e).__name__})", flush=True)
    return man.get("rc", rc)


# ---------------------------------------------------------------------------
# KAGOYA の側
# ---------------------------------------------------------------------------
def changed_since(roots, t0):
    out = []
    for r in roots:
        for dp, dn, fn in os.walk(r):
            dn[:] = [d for d in dn if not any(w in d.lower() for w in SKIP_DIR_WORDS)]
            for f in fn:
                if f.lower().endswith(SKIP_EXT):
                    continue
                p = os.path.join(dp, f)
                try:
                    s = os.stat(p)
                except OSError:
                    continue
                if s.st_mtime >= t0 and s.st_size <= MAX_PULL_BYTES:
                    out.append(p)
    return out


def _kill_previous_remote_runs():
    """前のボタンの残り (神風で止めた・回線が切れた) を、子のプロセスごと閉じる。

    ボタンは一度に1つしか動かない (神風が1つずつ流す) ので、残っている remote-run は全部 前の回の物。
    残すと目視の画面の番号 (18765) と席を握ったままになり、次のボタンが動けない。
    """
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'kagoya_button.py.+remote-run' "
          f"-and $_.ProcessId -ne {os.getpid()} -and $_.ProcessId -ne {os.getppid()} }} | "
          "ForEach-Object { taskkill /T /F /PID $_.ProcessId | Out-Null }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=60, capture_output=True)
    except Exception:                                          # noqa: BLE001
        pass
    try:
        K.release_server_seat(BTN_SEAT)
    except Exception:                                          # noqa: BLE001
        pass


def seat_gb_from_envs(envs, default):
    """--env IMAK_SEAT_GB=0.3 → 0.3。無い・読めなければ default (純関数)。"""
    for e in envs or []:
        if e.startswith("IMAK_SEAT_GB="):
            try:
                v = float(e.split("=", 1)[1])
                return v if v > 0 else default
            except ValueError:
                return default
    return default


def remote_main(cwd, out_dir, envs, args):
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(HOME_DESK, exist_ok=True)
    _kill_previous_remote_runs()
    try:
        os.remove(os.path.join(out_dir, "out.tgz"))   # 前の回の結果を取り込まないように
    except OSError:
        pass
    # ★2026-10-04: API とシートだけの軽いボタンは小さい席で入る (offload.json の button_seat_gb → --env IMAK_SEAT_GB)。
    #   KAGOYA は抽出くんの Chrome 等で空き 1.4GB 前後のことが多く、一律 1.2GB だと軽いボタンも家に戻っていた
    need = seat_gb_from_envs(envs, BTN_NEED_GB)
    if not K.acquire_server_seat(BTN_SEAT, need_gb=need):
        print("[KAGOYA] 席が取れない (空きメモリ不足)", flush=True)
        return 75
    t0 = time.time() - 2
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", IMAK_HEADLESS="1",
                   IMAK_NO_BROWSER="1", IMAK_REVIEW_PORT="18765",
                   # ★2026-10-03 PSA 新規: KAGOYA には Cloudflare を押す人がいない → 先取り済みの cert だけで進む
                   PSA_CACHED_ONLY="1", **dict(e.split("=", 1) for e in envs))
        rc = subprocess.call([sys.executable, "-X", "utf8", "-u"] + args, cwd=cwd, env=env)
    finally:
        K.release_server_seat(BTN_SEAT)
    files = changed_since(SCAN_ROOTS, t0)
    rels = [carry_name(p) for p in files]
    tgz = os.path.join(out_dir, "out.tgz")
    with tarfile.open(tgz, "w:gz") as tf:
        man = json.dumps({"rc": rc, "files": rels}, ensure_ascii=False).encode("utf-8")
        ti = tarfile.TarInfo("manifest.json")
        ti.size = len(man)
        tf.addfile(ti, io.BytesIO(man))
        for p, rel in zip(files, rels):
            tf.add(p, arcname="files/" + rel)
    print(f"[KAGOYA] 終了 rc={rc} / 変わったファイル {len(rels)}本", flush=True)
    return rc


def _parse(a):
    cwd = out = None
    envs = []
    i = 0
    while i < len(a) and a[i] != "--":
        if a[i] == "--cwd":
            cwd, i = a[i + 1], i + 2
        elif a[i] == "--out":
            out, i = a[i + 1], i + 2
        elif a[i] == "--env":
            envs.append(a[i + 1])
            i += 2
        else:
            raise SystemExit(f"不明な引数: {a[i]}")
    return cwd, out, envs, a[i + 1:]


def main():
    a = sys.argv[1:]
    if a and a[0] == "remote-cleanup":                 # KAGOYA の側: 残っているボタンを閉じる
        _kill_previous_remote_runs()
        print("[KAGOYA] 残っていたボタンを閉じた", flush=True)
        return 0
    if a and a[0] == "cleanup":                        # 家の側: 神風で止めた時
        cfg = K._cfg()
        script = rf"{K.REMOTE_CODE_ROOT}\iMakHQ\tools\kagoya_button.py"
        rc, out = K._ssh(cfg, f"& {_q(K.REMOTE_PY)} {_q(script)} remote-cleanup", timeout=120)
        print(out.strip()[-200:])
        return rc
    if a and a[0] == "remote-run":
        cwd, out, envs, args = _parse(a[1:])
        return remote_main(cwd, out or REMOTE_OUT, envs, args)
    cwd, _out, envs, args = _parse(a)
    if not args:
        print(__doc__)
        return 2
    return home_main(cwd or os.getcwd(), envs, args)


if __name__ == "__main__":
    sys.exit(main())
