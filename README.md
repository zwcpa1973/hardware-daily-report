# 硬件日报

每日自动采集 **京东 / 淘宝** 的硬件报价并生成走势图，每天 **17:00** 发送到邮箱，
同时归档到本仓库（走势图 + 历史日报 + GitHub Pages）。

## 监控范围

| 分组 | 商品（持续积累走势） |
|---|---|
| 整机·迷你主机 | Mac mini M4、零刻 SER9（AMD）、极摩客 K8 Plus（AMD）、铭凡 NUC5（Intel Ultra） |
| 整机·笔记本 | MacBook Air M4、拯救者 Y7000P（Intel）、华硕天选 Pro（AMD） |
| 整机·台式机 | 拯救者刃 7000K（Intel）、华硕天选X（AMD）、联想 GeekPro（Intel） |
| DDR5 内存 | 金百达 / 光威 / 金士顿 DDR5 6000 16G×2 |
| 手机 | iQOO Neo10、Neo10 Pro、Neo11 |

清单可在 `products.yaml` 中自由增删（关键词 + 命中规则 + 价格区间）。

## 为什么在本地跑（而不是 GitHub Actions）

2026 年起京东与淘宝对**未登录用户完全隐藏价格**（商品页价格混淆、搜索强制登录），
且对海外 IP 风控严格。因此每日抓取在本机完成：

```
Windows 计划任务 17:00
  └─ run_daily.bat
      ├─ scripts/scrape.py    Edge 无头浏览器 + 登录态，搜索京东/淘宝取价
      ├─ scripts/report.py    生成 3 张走势图 + HTML 日报
      ├─ scripts/emailer.py   QQ 邮箱 SMTP 发送（走势图内嵌正文）
      └─ scripts/publish.py   更新 README/index.html 并推送 GitHub
```

云端 GitHub Actions（`.github/workflows/rebuild.yml`）只负责从 `data/prices.csv`
重算图表并发布 Pages，不接触电商网站。

## 首次部署（三步）

```bat
cd /d W:\codexplaceoffice\其他\硬件日报

:: 1. 安装依赖（仅首次）
pip install -r requirements.txt

:: 2. 扫码登录京东（必选）与淘宝（可选），登录态存于 auth/，约 1 个月失效后重新执行
python scripts/login.py

:: 3. .env 填入 QQ 邮箱授权码（QQ邮箱网页版 -> 设置 -> 账号 -> 开启SMTP -> 生成授权码）
::    然后手动跑一次，验证全链路
run_daily.bat
```

计划任务已注册：每天 17:00 自动执行（见下文"计划任务"）。

## 计划任务

已通过 PowerShell 注册（`Register-ScheduledTask`）：

- 名称：`硬件日报`
- 触发：每天 17:00（错过则登录后尽快补跑）
- 动作：`W:\codexplaceoffice\其他\硬件日报\run_daily.bat`
- 日志：`output/daily_log.txt`

管理命令（管理员 PowerShell）：

```powershell
Get-ScheduledTask -TaskName '硬件日报'          # 查看
Start-ScheduledTask  -TaskName '硬件日报'        # 立即执行
Unregister-ScheduledTask -TaskName '硬件日报'    # 删除
```

## 维护

- **登录态过期**：邮件会提示"京东/淘宝登录态已失效"，重新运行 `python scripts/login.py`。
- **某商品总是未命中**：查看 `output/debug/` 下当日截图与 HTML，调整 `products.yaml`
  里的 `keyword / must_include / price_range`。
- **授权码更换**：更新 `.env` 的 `SMTP_AUTH_CODE`（`.env` 已被 gitignore，不会提交）。

## 目录结构

```
products.yaml            监控商品清单
data/prices.csv          历史价格（核心资产）
output/charts/*.png      三张走势图（本 README 引用）
output/reports/*.html    历史日报存档
output/daily_log.txt     每日运行日志（不入库）
auth/                    京东/淘宝登录态（不入库）
scripts/                 全部脚本
```

<!-- AUTO:BEGIN -->
<!-- AUTO:END -->
