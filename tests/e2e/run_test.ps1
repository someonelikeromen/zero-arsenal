#!/usr/bin/env pwsh
# 运行浏览器实测，设置正确的编码环境
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Set-Location "E:\plu\zero-arsenal"
& "C:\Python313\python.exe" -u "tests\e2e\browser_live_test.py" 2>&1
