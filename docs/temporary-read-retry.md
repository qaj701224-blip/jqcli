# 临时只读重试入口

仅在需要时使用独立包装，不替换 `jqcli.exe`，不修改 DNS、代理、hosts、认证配置或策略。

```powershell
& 'F:\A股复刻\jqcli\scripts\jqcli-read-retry.ps1' --non-interactive --timeout 10 --format json strategy ls --limit 3
```

参数与原 CLI 相同；原来的当前目录 `.env` 和配置读取规则不变。通过仓库内的虚拟环境执行，无需安装新依赖。停止使用这个入口、换回 `jqcli.exe` 即停用包装。

## 重试边界

- 白名单：`strategy ls/show`，`backtest ls/show/stats/result/logs`。
- 同时要求当前请求为 GET 或 HEAD，且异常根因为 HTTPX 的连接、读取或写入网络超时。
- **首次请求之外最多额外重试 3 次**；整个 CLI 调用共享这 3 次额度，分页或多个请求不会重置额度。
- 等待依次为 1、2、3 秒；`--timeout` 仍是 HTTPX 各阶段超时参数，不是整条命令的总时限。
- 只重发失败的只读请求，不从头重跑整个命令。
- 认证失败、HTTP 错误、连接拒绝、证书错误、连接池超时、解析错误均不重试。
- `backtest run`、`strategy new/edit/rm`、`backtest rm`、登录、克隆及所有不在白名单内的命令仍按原 CLI 执行一次。**包括这些命令的前置 GET，也绝不重试。** 包装器不是禁止写入的沙箱；调用写命令仍会按原逻辑执行。
- stdout 保留原输出（包括 JSON），重试提示只写 stderr，不记录凭据或请求参数，最终退出码保持原 CLI 语义。

这是网络波动时的有限缓解，不保证访问成功，也不重新登录。不要再套用整条写命令的外部重试循环。

## 验证

`tests/test_read_retry_wrapper.py` 使用离线传输模拟超时、认证错误和写入命令，验证次数上限、共享额度、只读边界、输出及恢复原方法。在线验收仅使用 `strategy ls`，不运行策略。
