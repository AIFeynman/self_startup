---
name: wealth
description: 理财板块：一年收益目标（QQQ / 谷歌 / 微软 / 红利低波ETF + 低回撤债基底仓）各标的增持 / 持有 / 减持的结论和理由、稳健 / 进取配比（稳妥方案压力回撤上限可调）、红利低波估值择时、按资金生成的挂单；美团减持阶梯（目标均价、达标概率、费用、换 QQQ 对比、回测）、登记成交；信号变化和每日汇总提醒的记录。用于「QQQ / 谷歌 / 微软 / 红利低波现在该加还是拿着，为什么」「美团今天该卖多少」「目标 12% 的话怎么配」「最近有哪些理财提醒」「登记一笔美团成交」。统计估算，不构成投资建议。
---

# 理财

数据在本地平台（默认 `http://127.0.0.1:8780`，环境变量 `SELF_STARTUP_API` 覆盖；下文 `$API` 指它）。
代码：`app/modules/wealth.py`（接口 / 后台 / 提醒）、`_wealth_service.py`（持仓、行情存取、计划组装）、`_wealth_target_plan.py`（收益目标模型、估值择时、挂单）、`_wealth_valuation.py`（各标的估值数据和分档表）、`_wealth_sell_plan.py`（减持阶梯）、`_wealth_switch_plan.py`（换 QQQ 对比）、`_wealth_sell_backtest.py`、`_wealth_market.py`（Yahoo 行情 / 新闻）、`_wealth_alerts.py`（信号快照和变化）。
数据：`data/wealth/positions.json`（持仓配置）、回测缓存 JSON、`alerts.json`（上次信号快照）；`app.db` 的 `wealth_*` 表（K 线、报价、新闻、估值、成交）。

## 链路

1. **刷新**：后台每 `wealth.refresh_minutes`（60）分钟拉五个标的的 K 线、报价、新闻；手动 `POST /refresh`。目标计划回测每天补一次，减持回测每周一次。
2. **信号**：每次刷新后重算目标计划和美团减持计划，和 `alerts.json` 的上次快照比：标的结论变化（增持 / 持有 / 减持）、红利低波估值区间变化、美团建议现卖股数变化、价格穿过挂单档、换仓比例变化 → 每条一个通知，带理由。
3. **汇总**：每天 `wealth.summary_time`（16:30）之后第一次检查发一条「每日信号汇总」。
4. **通知**：走通用 `app.notify.notify()` —— 写 `notifications` 表（页面右下角弹出、通知页可查），`notify.system` 打开时同时发 Mac 系统通知。

估值分档表（`assets[].val_timing`、减持计划的 `timing`）：QQQ 用纳指 100 指数 PE + 美债利差，谷歌 / 微软用 SEC 财报算滚动 PE + 美债利差，红利低波用指数 PE + 国债利差，美团亏损期用市销率，债基用 10 年国债收益率。`levels` 是盈利不变时分界线对应的价格（债基给收益率）。只有红利低波的表会调节奏和挂单，其他只作参考，不改概率、挂单和提醒。数据缓存在 `data/wealth/asset_valuation.json`，过期后台刷新，某个源失败时留旧副本并标 `stale`。

回答时先给结论（加 / 拿着 / 减、卖多少股），再给理由（概率、估值、回测证据），最后写「统计估算，不构成投资建议」。不要替用户下单，只给计划里的数。

## API

```bash
curl -s "$API/api/wealth/target-plan?target=0.1&shape=balanced&delay=1&drawdown=0.05"   # 目标计划：assets[].action / reasons / timing、modes（稳健 / 进取配比、挂单）；drawdown 是稳妥方案的压力回撤上限（1%–40%，默认 5%）
curl -s "$API/api/wealth/sell-plan?symbol=3690.HK"                        # 减持计划；可加 target_avg / horizon_days(0=不限) / now_shares / shape / compare_days / qqq_return
curl -s -X POST $API/api/wealth/positions -H 'Content-Type: application/json' -d '{"symbol":"3690.HK","target_avg":88,"horizon_days":126}'
curl -s -X POST $API/api/wealth/trades -H 'Content-Type: application/json' -d '{"symbol":"3690.HK","shares":500,"price":80.5,"note":"限价成交"}'
curl -s -X DELETE $API/api/wealth/trades/3
curl -s -X POST $API/api/wealth/refresh                                   # 刷新行情和新闻（同步，十几秒）
curl -s -X POST $API/api/wealth/backtest/target                           # 重跑回测（后台）：target | sell
curl -s "$API/api/wealth/alerts?limit=20"                                 # 提醒记录 + 当前信号快照
curl -s -X POST $API/api/wealth/alerts/check -H 'Content-Type: application/json' -d '{"summary":true}'   # 立刻重算；summary=true 必发汇总
curl -s -X POST $API/api/wealth/alerts/test                               # 测试通知
curl -s "$API/api/wealth/status"                                          # 上次刷新、上次检查、设置
```

设置（`PUT /api/settings`）：`wealth.alerts`（true）、`wealth.target`（0.10）、`wealth.summary_time`（"16:30"）、`wealth.refresh_minutes`（60）；`notify.system`（true，Mac 系统通知）。
