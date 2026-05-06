# Tool Contracts

## 原则

业务 Graph 不能硬编码 Tavily、MCP 或具体数据库查询实现。Graph 只能提出 capability 请求，统一工具层负责 provider 选择、权限判断、执行、审计和结果标准化。

## ToolCapability

首批 capability：

- `notebook_retrieve`
- `web_search`
- `web_extract`
- `sql_read`
- `code_execute`
- `file_parse`

## ToolRegistry

职责：

- 根据 capability 查找可用工具。
- 支持 provider，例如 `tavily`、`internal`、`postgres`、`notebook`。
- 支持 enabled / disabled。
- 预留 tenant scope。

## ToolPolicyResolver

职责：

- 根据 `source_policy`、tenant policy、risk level、capability 判断是否允许调用工具。
- 不允许模型绕过工具权限。
- 测试模式禁止写生产数据类工具。

默认规则：

- `notebook_only`：允许 `notebook_retrieve`，禁止 `web_search` 和 `web_extract`。
- `notebook_plus_external`：允许 `notebook_retrieve`、`web_search`、`web_extract`，禁止 `sql_read`、`code_execute`、`file_parse`。
- `open_tools`：允许白名单内 capability，但仍必须通过 provider policy、risk、tenant 和 test mode 检查。

`ToolExecutor` 必须以 `ToolRegistration.risk_level` 作为请求风险等级下限，避免业务 Graph 低报风险。

## ToolAdapter

职责：

- 把现有项目工具转成 LangChain tool 或内部 callable。
- 把 provider 返回值标准化成统一 `ToolResult`。

## ToolResult

字段：

- `tool_id`
- `provider`
- `capability`
- `status`
- `input_summary`
- `output`
- `evidence`
- `latency_ms`
- `error`

## Tavily 约束

Tavily 只能作为：

```text
capability = web_search
provider = tavily
```

未来 QAGraph 不应调用 `tavily_web_search` 这个具体工具名，而应请求 `web_search` capability。
