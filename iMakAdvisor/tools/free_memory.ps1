# メモリを少し空ける (2026-10-05 ADV)
#
# ユーザー「メモリを開放するアプリで、軽くていいのない？」に対して、
# アプリを入れずに同じことをやる物。入れても取り返せるのは待機キャッシュだけで、
# 実測 0.6GB しか無かった (2026-10-05)。だから主役は **窓を閉じたのに残っている
# Chrome / Edge の残骸を落とす** 方。
#
# 安全のため: **窓が開いているブラウザには触らない**。
#   MainWindowTitle が1つでも在る = 今使っている → そのブラウザは丸ごと見送る。
#   (使用中に落とすとタブが消える。それは解放より高く付く)

$ErrorActionPreference = 'SilentlyContinue'

function Get-FreeGB {
    $o = Get-CimInstance Win32_OperatingSystem
    [math]::Round($o.FreePhysicalMemory / 1MB, 2)
}

$before = Get-FreeGB
Write-Host ("空き {0} GB から開始" -f $before)

# --- 1) 窓の無いブラウザの残骸を落とす -------------------------------------
foreach ($name in @('msedge', 'chrome')) {
    $ps = Get-Process -Name $name
    if (-not $ps) { continue }
    $open = $ps | Where-Object { $_.MainWindowTitle -ne '' }
    $mb = [int](($ps | Measure-Object WS -Sum).Sum / 1MB)
    if ($open) {
        # ★2026-10-05: 一度「閉じますか [y/N]」と聞く形にしたが、ユーザー
        #   「きかれてもわからないよ、どれが閉じ忘れなのか」。**聞くのをやめた**。
        #   機械にも人にも「閉じ忘れ」は判らないので、放置タブは
        #   **ブラウザ自身のスリープタブに返させる** (設定は別途 1回だけ)。
        #   ここは窓が開いている分には触らず、持っている量を知らせるだけにする。
        Write-Host ("  {0}: 窓が開いているので触りません ({1}個 / {2} MB)" -f $name, $ps.Count, $mb)
        continue
    }
    Write-Host ("  {0}: 窓なしの残骸 {1}個 / {2} MB を落とします" -f $name, $ps.Count, $mb)
    $ps | Stop-Process -Force
}

# --- 2) 待機キャッシュを空ける (管理者の時だけ) -----------------------------
# ★RAMMap や EmptyStandbyList.exe を落としてこなくても、Windows の
#   NtSetSystemInformation(SystemMemoryListInformation, MemoryPurgeStandbyList=4)
#   を直接呼べば同じことができる。外から実行ファイルを持って来ない方が安全。
$admin = ([Security.Principal.WindowsPrincipal] `
          [Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $admin) {
    Write-Host "  待機キャッシュ: 管理者で動いていないので飛ばします"
} else {
    try {
        # ★2026-10-05: 最初の版は 0xC0000061 (権限なし) で失敗した。
        #   原因は構造体の並び — int / long / int は既定だと long の前に 4バイトの
        #   詰め物が入り、API に渡る中身がズレて特権が有効にならない。
        #   **Pack=1 を付ける**のが要点 (この手の定番の落とし穴)。
        # ★-UsingNamespace は付けない。Add-Type は InteropServices を既定で取り込むので、
        #   重ねると「既に使用されています」でコンパイルが落ちる (2026-10-05 に踏んだ)
        Add-Type -ErrorAction Stop -Namespace IMak -Name Mem -MemberDefinition @'
[StructLayout(LayoutKind.Sequential, Pack = 1)]
public struct TokPriv1Luid { public int Count; public long Luid; public int Attr; }

[DllImport("ntdll.dll")]
public static extern int NtSetSystemInformation(int InfoClass, IntPtr Info, int Length);
[DllImport("advapi32.dll", SetLastError=true)]
public static extern bool OpenProcessToken(IntPtr h, int acc, out IntPtr tok);
[DllImport("advapi32.dll", SetLastError=true)]
public static extern bool LookupPrivilegeValue(string host, string name, out long luid);
[DllImport("advapi32.dll", SetLastError=true)]
public static extern bool AdjustTokenPrivileges(IntPtr tok, bool dis, ref TokPriv1Luid np,
                                                int len, IntPtr prev, IntPtr rel);
[DllImport("kernel32.dll")]
public static extern bool CloseHandle(IntPtr h);
'@
        # SeProfileSingleProcessPrivilege が無いと 0xC0000061 で弾かれる
        $tok = [IntPtr]::Zero
        $okT = [IMak.Mem]::OpenProcessToken([Diagnostics.Process]::GetCurrentProcess().Handle,
                                            0x20 -bor 0x8, [ref]$tok)
        if (-not $okT) { throw "トークンを開けません" }
        $luid = 0L
        if (-not [IMak.Mem]::LookupPrivilegeValue($null, 'SeProfileSingleProcessPrivilege', [ref]$luid)) {
            throw "特権の名前を引けません"
        }
        $tp = New-Object IMak.Mem+TokPriv1Luid
        $tp.Count = 1; $tp.Luid = $luid; $tp.Attr = 2   # SE_PRIVILEGE_ENABLED
        $okA = [IMak.Mem]::AdjustTokenPrivileges($tok, $false, [ref]$tp,
                                                 [Runtime.InteropServices.Marshal]::SizeOf($tp),
                                                 [IntPtr]::Zero, [IntPtr]::Zero)
        $le = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        [IMak.Mem]::CloseHandle($tok) | Out-Null
        if (-not $okA -or $le -ne 0) { throw ("特権を有効にできません (err={0})" -f $le) }

        $p = [Runtime.InteropServices.Marshal]::AllocHGlobal(4)
        [Runtime.InteropServices.Marshal]::WriteInt32($p, 4)   # MemoryPurgeStandbyList
        $rc = [IMak.Mem]::NtSetSystemInformation(0x50, $p, 4)  # SystemMemoryListInformation
        [Runtime.InteropServices.Marshal]::FreeHGlobal($p)
        if ($rc -eq 0) { Write-Host "  待機キャッシュ: 空けました" }
        else { Write-Host ("  待機キャッシュ: 空けられませんでした (0x{0:X})" -f $rc) }
    } catch {
        Write-Host ("  待機キャッシュ: 失敗 ({0})" -f $_.Exception.Message)
    }
}

# --- 3) 結果 ---------------------------------------------------------------
Start-Sleep -Milliseconds 800
$after = Get-FreeGB
Write-Host ""
Write-Host ("空き {0} GB → {1} GB ({2:+0.00;-0.00;0} GB)" -f $before, $after, ($after - $before))
Write-Host ""
Write-Host "上位10:"
Get-Process | Group-Object ProcessName | ForEach-Object {
    [PSCustomObject]@{ 名前 = $_.Name; 個 = $_.Count
                       MB = [int](($_.Group | Measure-Object WS -Sum).Sum / 1MB) }
} | Sort-Object MB -Descending | Select-Object -First 10 | Format-Table -AutoSize
