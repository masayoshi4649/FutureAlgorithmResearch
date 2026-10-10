<#
機能: 共有フォルダーから未取得のファイルだけを、速度を抑えて手動取得します。
引数: Source [string] コピー元、Destination [string] 保存先、MaxMbps [double] 転送速度の目安。
返り値: プロセス終了コード [int]。0 は成功、1 は一部失敗、2 は準備失敗です。
使用例: .\未取得ファイルを取得.ps1 -MaxMbps 10
#>
[CmdletBinding()]
param(
    [string]$Source = '\\10.10.100.1\log',
    [string]$Destination = '',
    [ValidateRange(4.2, 100000)]
    [double]$MaxMbps = 10
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$exitCode = 2
$mutex = $null
$hasLock = $false
$summaryPath = $null
$copied = 0
$skipped = 0
$failed = 0
[long]$copiedBytes = 0

# ----------------------------------------
function Assert-OrdinaryPath {
    <#
    機能: パスの既存部分にリンク・接合点・マウントポイントがないことを確認します。
    引数: Path [string] 確認する絶対パス。
    返り値: [void]。該当するパスがある場合は例外です。
    #>
    param([string]$Path)
    $current = $Path
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "リンクまたは接合点を含むため処理できません: $current"
            }
        }
        $parent = [IO.Directory]::GetParent($current)
        if ($null -eq $parent) { break }
        $current = $parent.FullName
    }
}

function Write-Record {
    <#
    機能: ファイルごとの処理結果を日本語の記録に追記します。
    引数: Status [string] 結果、RelativePath [string] 相対パス、Bytes [long] サイズ、Detail [string] 補足。
    返り値: [void]。
    #>
    param([string]$Status, [string]$RelativePath, [long]$Bytes, [string]$Detail)
    [ordered]@{
        '日時' = (Get-Date).ToString('o')
        '結果' = $Status
        '相対パス' = $RelativePath
        'バイト数' = $Bytes
        '補足' = $Detail
    } | ConvertTo-Json -Compress | Add-Content -LiteralPath $script:recordPath -Encoding UTF8
}

# ----------------------------------------
try {
    if ([string]::IsNullOrWhiteSpace($Destination)) {
        $Destination = [IO.Directory]::GetParent($PSScriptRoot).FullName
    }
    $sourceRoot = [IO.Path]::GetFullPath($Source).TrimEnd('\')
    $destinationRoot = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
    if ($destinationRoot -notmatch '^[A-Za-z]:\\.+') {
        throw '保存先にはローカルドライブ内のフォルダーを指定してください。'
    }
    if ($sourceRoot -eq $destinationRoot -or
        $destinationRoot.StartsWith($sourceRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
        $sourceRoot.StartsWith($destinationRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'コピー元と保存先は、互いに含まれない別のフォルダーにしてください。'
    }
    if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
        throw "コピー元を開けません。VPN・共有名・読み取り権限を確認してください: $sourceRoot"
    }
    Assert-OrdinaryPath -Path $destinationRoot
    $robocopy = (Get-Command robocopy.exe -ErrorAction Stop).Source
    $helpText = & $robocopy /? | Out-String
    if ($helpText -notmatch '(?i)/IoRate:') {
        throw 'このWindowsのRobocopyは速度制限に対応していません。無制限のコピーは実行しません。'
    }
    [long]$rateBytes = [Math]::Floor($MaxMbps * 1000000 / 8)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($destinationRoot.ToUpperInvariant()))
        $lockKey = ([BitConverter]::ToString($digest)).Replace('-', '').Substring(0, 24)
    } finally { $sha.Dispose() }
    $mutex = New-Object Threading.Mutex($false, ('Local\ManualFileReceive_' + $lockKey))
    try { $hasLock = $mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $hasLock = $true }
    if (-not $hasLock) { throw '同じ保存先への取得処理がすでに動いています。' }

    # ----------------------------------------
    $helperName = '取得ツール'
    $reservedSourcePath = Join-Path $sourceRoot $helperName
    if (Test-Path -LiteralPath $reservedSourcePath) {
        throw "コピー元に補助フォルダーと同名の項目があります。補助ツールの配置変更が必要です: $helperName"
    }
    $helperRoot = Join-Path $destinationRoot $helperName
    $logRoot = Join-Path $helperRoot '実行記録'
    Assert-OrdinaryPath -Path $logRoot
    [void][IO.Directory]::CreateDirectory($logRoot)
    $runName = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
    $recordPath = Join-Path $logRoot ($runName + '-ファイル結果.jsonl')
    $robocopyLog = Join-Path $logRoot ($runName + '-転送詳細.log')
    $summaryPath = Join-Path $logRoot ($runName + '-集計.json')
    $stateRoot = Join-Path ([IO.Directory]::GetParent($destinationRoot).FullName) ('.取得途中-' + $lockKey)
    Assert-OrdinaryPath -Path $stateRoot
    [void][IO.Directory]::CreateDirectory($stateRoot)
    $stateInfo = Join-Path $stateRoot '取得元.json'
    if (Test-Path -LiteralPath $stateInfo) {
        $previous = Get-Content -LiteralPath $stateInfo -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($previous.'コピー元' -ne $sourceRoot -or $previous.'保存先' -ne $destinationRoot) {
            throw '同じ保存先に別のコピー元の途中データがあります。別の保存先を指定してください。'
        }
    } else {
        [ordered]@{'コピー元' = $sourceRoot; '保存先' = $destinationRoot} |
            ConvertTo-Json | Set-Content -LiteralPath $stateInfo -Encoding UTF8
    }
    $stageRoot = Join-Path $stateRoot '受信中'
    [void][IO.Directory]::CreateDirectory($stageRoot)
    Write-Host "コピー元: $sourceRoot"
    Write-Host "保存先: $destinationRoot"
    Write-Host "速度の目安: $MaxMbps Mbps。単一転送で、既存ファイルは上書きしません。"
    Write-Host 'ファイル一覧を確認しています。既存ファイルの内容は読み込みません。'

    # ----------------------------------------
    $pending = New-Object 'Collections.Generic.List[object]'
    $directories = New-Object 'Collections.Generic.Stack[string]'
    $directories.Push($sourceRoot)
    [long]$requiredBytes = 0
    while ($directories.Count -gt 0) {
        $directory = $directories.Pop()
        foreach ($item in Get-ChildItem -LiteralPath $directory -Force) {
            $relative = $item.FullName.Substring($sourceRoot.Length + 1)
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "リンクまたは接合点は対象外です。実フォルダーを指定してください: $relative"
            }
            $target = Join-Path $destinationRoot $relative
            Assert-OrdinaryPath -Path $target
            if ($item.PSIsContainer) {
                [void][IO.Directory]::CreateDirectory($target)
                $directories.Push($item.FullName)
            } elseif (Test-Path -LiteralPath $target) {
                if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
                    throw "ファイルの保存位置にフォルダーがあり衝突しています: $relative"
                }
                $skipped++
                Write-Record '既存のため省略' $relative $item.Length ''
            } else {
                $pending.Add([pscustomobject]@{Path = $item.FullName; Relative = $relative; Length = $item.Length})
                $requiredBytes += $item.Length
            }
        }
    }
    $driveInfo = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($destinationRoot))
    if ($requiredBytes -gt $driveInfo.AvailableFreeSpace) {
        throw "空き容量が不足しています。未取得データは $requiredBytes バイトです。"
    }
    Write-Host ("未取得: {0} 件 / {1:N2} MiB、既存: {2} 件" -f $pending.Count, ($requiredBytes / 1MB), $skipped)

    # ----------------------------------------
    $index = 0
    foreach ($entry in $pending) {
        $index++
        $relative = $entry.Relative
        $target = Join-Path $destinationRoot $relative
        Write-Host ("[{0}/{1}] {2}" -f $index, $pending.Count, $relative)
        try {
            Assert-OrdinaryPath -Path $target
            if (Test-Path -LiteralPath $target) {
                $skipped++
                Write-Record '既存のため省略' $relative $entry.Length '一覧確認後に作成された項目'
                continue
            }
            $before = Get-Item -LiteralPath $entry.Path -Force
            if (($before.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw '取得直前にコピー元がリンクへ変わりました。'
            }
            [long]$beforeLength = $before.Length
            [long]$beforeTicks = $before.LastWriteTimeUtc.Ticks
            $stageFile = Join-Path $stageRoot $relative
            $stageDirectory = [IO.Path]::GetDirectoryName($stageFile)
            Assert-OrdinaryPath -Path $stageFile
            [void][IO.Directory]::CreateDirectory($stageDirectory)
            $resumeInfo = Join-Path (Join-Path $stateRoot '受信状態') $relative
            Assert-OrdinaryPath -Path $resumeInfo
            [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($resumeInfo))
            $canResume = $false
            if (Test-Path -LiteralPath $resumeInfo -PathType Leaf) {
                $oldInfo = Get-Content -LiteralPath $resumeInfo -Raw -Encoding UTF8 | ConvertFrom-Json
                $canResume = ($oldInfo.'サイズ' -eq $beforeLength -and $oldInfo.'更新日時' -eq $beforeTicks)
            }
            if ((Test-Path -LiteralPath $stageFile) -and -not $canResume) {
                if (-not (Test-Path -LiteralPath $stageFile -PathType Leaf)) {
                    throw '途中データの保存位置にフォルダーがあります。'
                }
                Remove-Item -LiteralPath $stageFile -Force
            }
            [ordered]@{'サイズ' = $beforeLength; '更新日時' = $beforeTicks} |
                ConvertTo-Json | Set-Content -LiteralPath $resumeInfo -Encoding UTF8
            if ($beforeLength -gt $driveInfo.AvailableFreeSpace) {
                throw '取得途中でローカルの空き容量が不足しました。'
            }
            $roboArgs = @(
                ($before.DirectoryName.TrimEnd('\') + '\.'),
                ($stageDirectory.TrimEnd('\') + '\.'),
                $before.Name,
                '/Z', '/IS', '/IT', '/COPY:DAT', '/NODCOPY', '/R:2', '/W:3',
                "/IORATE:$rateBytes", '/THRESHOLD:0', '/NP', '/NJH', '/NJS', '/BYTES', '/FP', '/TS',
                "/UNILOG+:$robocopyLog"
            )
            & $robocopy @roboArgs | Out-Null
            $roboCode = $LASTEXITCODE
            if ($roboCode -lt 0 -or $roboCode -gt 7) {
                throw "転送が完了しませんでした。Robocopy終了コード: $roboCode"
            }
            $after = Get-Item -LiteralPath $entry.Path -Force
            $staged = Get-Item -LiteralPath $stageFile -Force
            if ($beforeLength -ne $after.Length -or $beforeTicks -ne $after.LastWriteTimeUtc.Ticks -or
                $staged.Length -ne $beforeLength -or $staged.LastWriteTimeUtc.Ticks -ne $beforeTicks) {
                throw '取得中にコピー元が変化したか、受信後のサイズ・更新日時が一致しません。途中データを保留します。'
            }
            Assert-OrdinaryPath -Path $target
            Assert-OrdinaryPath -Path $stageFile
            [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
            try {
                [IO.File]::Move($stageFile, $target)
            } catch [IO.IOException] {
                if (Test-Path -LiteralPath $target -PathType Leaf) {
                    $skipped++
                    Write-Record '既存のため省略' $relative $beforeLength '転送中に保存先ファイルが作成されたため保護'
                    continue
                }
                throw
            }
            $copied++
            $copiedBytes += $beforeLength
            Write-Record '取得完了' $relative $beforeLength '転送成功とサイズ・更新日時を確認'
        } catch {
            $failed++
            Write-Record '失敗・次回再取得' $relative $entry.Length $_.Exception.Message
            Write-Warning ("{0}: {1}" -f $relative, $_.Exception.Message)
        }
    }
    if ($failed -eq 0) { $exitCode = 0 } else { $exitCode = 1 }
} catch {
    Write-Warning $_.Exception.Message
    $exitCode = 2
} finally {
    # ----------------------------------------
    if ($summaryPath) {
        [ordered]@{
            '終了日時' = (Get-Date).ToString('o')
            'コピー元' = $Source
            '保存先' = $Destination
            '速度目安Mbps' = $MaxMbps
            '取得件数' = $copied
            '取得バイト数' = $copiedBytes
            '既存のため省略した件数' = $skipped
            '転送失敗件数' = $failed
            '終了コード' = $exitCode
        } | ConvertTo-Json | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    }
    if ($hasLock) { $mutex.ReleaseMutex() }
    if ($null -ne $mutex) { $mutex.Dispose() }
}
Write-Host ("取得: {0} 件 / {1:N0} バイト、既存省略: {2} 件、転送失敗: {3} 件" -f $copied, $copiedBytes, $skipped, $failed)
if ($summaryPath) { Write-Host "実行記録: $summaryPath" }
if ($exitCode -eq 0) { Write-Host '完了しました。' }
else { Write-Warning '未完了の項目があります。記録を確認し、原因を解消して同じツールを再実行してください。' }
exit $exitCode
