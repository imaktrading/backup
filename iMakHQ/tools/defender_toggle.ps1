# Windows Defender の検査の対象外 (C:\dev) を ON / OFF する。管理者で動かす (神風のボタン・デスクトップの .bat から)。
# 2026-10-04 ユーザー「ここにボタン付けてくれない？ON/OFFで。わすれちゃうから」
# 結果 (実際に対象外に入っているか) を C:\dev\iMak_data\hq\defender_exclusion.json に書く
# (管理者でない神風からは Defender の設定を読めないため)
param([ValidateSet('on','off')][string]$Mode = 'on')
$path = 'C:\dev'
if ($Mode -eq 'on') { Add-MpPreference -ExclusionPath $path } else { Remove-MpPreference -ExclusionPath $path }
$now = @((Get-MpPreference).ExclusionPath) -contains $path
$state = @{ on = $now; at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss'); path = $path } | ConvertTo-Json -Compress
[IO.File]::WriteAllText('C:\dev\iMak_data\hq\defender_exclusion.json', $state, (New-Object Text.UTF8Encoding $false))
