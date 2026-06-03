# verify.ps1 — ZeroArsenal 项目统一验收门禁
# 用途：自动迭代循环的退出条件判断
# 用法：./scripts/verify.ps1
#       exit 0 = 全通过，exit 1 = 有失败
# 环境变量：
#   VERIFY_SKIP_TSC=1  跳过前端 TypeScript 检查
#   VERIFY_SKIP_E2E=1  跳过 Playwright（默认跳过）

param(
    [switch]$SkipTsc,
    [switch]$SkipE2e
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Failed = @()

Write-Host "`n══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  ZeroArsenal Verify" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════`n" -ForegroundColor Cyan

# ── L0: Python 语法批量检查 ──────────────────────────────────────────────────
Write-Host "[L0] Python 语法检查..." -ForegroundColor Yellow
$pyScript = Join-Path $Root "scripts\_syntax_check.py"
@'
import ast, glob, sys, os
root = os.environ.get("VERIFY_ROOT", ".")
errors = []
files = list(glob.glob(root + "/backend/**/*.py", recursive=True))
for f in files:
    try:
        ast.parse(open(f, encoding="utf-8").read())
    except SyntaxError as e:
        errors.append(f"{f}:{e.lineno}: {e.msg}")
if errors:
    print("SYNTAX ERRORS:")
    for e in errors:
        print(" ", e)
    sys.exit(1)
else:
    print(f"OK ({len(files)} files)")
'@ | Set-Content -Encoding UTF8 $pyScript
$env:VERIFY_ROOT = $Root
$syntaxResult = python $pyScript 2>&1
Write-Host $syntaxResult
Remove-Item $pyScript -ErrorAction SilentlyContinue
if ($LASTEXITCODE -ne 0) { $Failed += "L0:python-syntax" }

# ── L1: pytest ──────────────────────────────────────────────────────────────
Write-Host "`n[L1] pytest..." -ForegroundColor Yellow
Push-Location "$Root"
python -m pytest tests/ -q --tb=short --no-header 2>&1
$pytestExit = $LASTEXITCODE
Pop-Location
if ($pytestExit -ne 0) { $Failed += "L1:pytest" }

# ── L2: TypeScript 类型检查 ──────────────────────────────────────────────────
if (-not $SkipTsc -and -not $env:VERIFY_SKIP_TSC) {
    Write-Host "`n[L2] TypeScript 检查..." -ForegroundColor Yellow
    Push-Location "$Root\frontend"
    npx tsc --noEmit 2>&1 | Select-String "error TS" | Select-Object -First 20
    $tscExit = $LASTEXITCODE
    Pop-Location
    if ($tscExit -ne 0) { $Failed += "L2:tsc" }
} else {
    Write-Host "`n[L2] TypeScript 检查跳过" -ForegroundColor DarkGray
}

# ── L3: Playwright smoke（默认跳过，CI 或手动开启）──────────────────────────
if (-not $SkipE2e -and $env:VERIFY_E2E -eq "1") {
    Write-Host "`n[L3] Playwright smoke..." -ForegroundColor Yellow
    Push-Location "$Root\frontend"
    npx playwright test --project=chromium tests/e2e/smoke/ 2>&1
    $e2eExit = $LASTEXITCODE
    Pop-Location
    if ($e2eExit -ne 0) { $Failed += "L3:playwright" }
} else {
    Write-Host "`n[L3] Playwright 跳过（设 VERIFY_E2E=1 启用）" -ForegroundColor DarkGray
}

# ── 结果 ─────────────────────────────────────────────────────────────────────
Write-Host "`n══════════════════════════════════════════" -ForegroundColor Cyan
if ($Failed.Count -eq 0) {
    Write-Host "  ALL PASS" -ForegroundColor Green
    Write-Host "══════════════════════════════════════════`n" -ForegroundColor Cyan
    exit 0
} else {
    Write-Host "  FAILED: $($Failed -join ', ')" -ForegroundColor Red
    Write-Host "══════════════════════════════════════════`n" -ForegroundColor Cyan
    exit 1
}
