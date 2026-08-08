# MCP 决策记录

## 结论

Step 04 不交付自制 MCP Wire Server，也不把 MCP 写成已实现能力。内部 Tool Catalog 已补充
版本、数据域和只读/幂等/非破坏性注解，可作为未来协议适配输入；所有调用仍必须经过现有
Gateway、Policy、Budget、Evidence 和 Audit。

原因有三点：

1. 当前没有明确的 MCP 消费端，直接增加常驻服务没有业务收益；
2. 2026-07-28 版 Streamable HTTP 已改为单端点、单请求 POST，并移除了现代路径上的协议会话，
   手写旧式 JSON-RPC/SSE Adapter 很容易制造“看起来像 MCP”的错误实现；
3. 官方 Python SDK 正处于大版本迁移期，应在确认目标客户端和稳定 SDK 版本后显式锁版本。

参考：

- [MCP 2026-07-28 Streamable HTTP 规范](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/streamable-http.mdx)
- [官方 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

## 后续启用条件

只有同时满足以下条件才实现：

- 已确定 Claude Code、Codex 或其他具体客户端；
- 用官方 SDK 和 Streamable HTTP，不自行维护协议状态机；
- 独立 Docker Profile，默认关闭；
- 只暴露稳定的只读 Tool；
- 认证身份映射到 Run、租户、用户、Policy 和 Budget；
- 越权、任意网络、任意 SQL、代码执行、Sampling、A2A 和交易能力保持关闭；
- Inspector/真实客户端验证 Tool List、Call、错误、并发与审计后才写入简历。

因此当前专业表述是“Tool Schema 与 MCP 适配边界已预留”，不是“已接入 MCP”。

