# E2E 测试目录

本目录存放 Playwright 端到端测试，覆盖完整用户流程（前端 + 后端联通）。

## 运行方式

```powershell
# 需先启动 dev server
$env:VERIFY_E2E = "1"
./scripts/verify.ps1
```

## 目录结构

```
e2e/
  smoke/          # 冒烟测试（verify.ps1 L3 层自动执行）
  flows/          # 完整玩法流程（手动执行）
```

> 当前状态：目录结构已就绪，Playwright 测试待补充。
