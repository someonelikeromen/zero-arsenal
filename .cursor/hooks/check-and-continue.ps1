# check-and-continue.ps1 — stop hook：验证后决定是否续跑
# 从 stdin 读 hook JSON，跑 verify.ps1，失败则返回 followup_message

$input_json = $input | Out-String
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

# 跑验证
$result = & "$Root\scripts\verify.ps1" 2>&1
$exitCode = $LASTEXITCODE
$output = $result -join "`n"

# 读取 GAP_ANALYSIS 未完成项
$gapFile = "$Root\GAP_ANALYSIS.md"
$openItems = @()
if (Test-Path $gapFile) {
    $gapContent = Get-Content $gapFile -Raw
    $openItems = [regex]::Matches($gapContent, '- \[ \] .+') | ForEach-Object { $_.Value }
}

if ($exitCode -eq 0 -and $openItems.Count -eq 0) {
    # 全部完成
    @{
        status = "done"
    } | ConvertTo-Json
    exit 0
}

# 构造 followup_message
$failSummary = if ($exitCode -ne 0) {
    $lines = ($output -split "`n") | Where-Object { $_ -match "FAILED|ERROR|error TS|assert" } | Select-Object -First 15
    "验证失败：`n" + ($lines -join "`n")
} else { "" }

$gapSummary = if ($openItems.Count -gt 0) {
    "`n尚有 $($openItems.Count) 个 GAP 项未完成：`n" + (($openItems | Select-Object -First 8) -join "`n")
} else { "" }

$followup = @"
请继续工作，直到所有检查通过。

$failSummary
$gapSummary

步骤：
1. 读取上方错误/未完成项
2. 修复或实现对应代码
3. 确保 ./scripts/verify.ps1 通过
4. 在 GAP_ANALYSIS.md 中勾选已完成项（- [x]）
"@

@{
    followup_message = $followup.Trim()
} | ConvertTo-Json -Compress
