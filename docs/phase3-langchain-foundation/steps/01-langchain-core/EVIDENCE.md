# Step 01 Evidence

## 依赖结果

临时隔离环境解析出的核心版本：

```text
langchain==1.3.14
langchain-core==1.5.1
langchain-openai==1.4.1
langgraph==1.2.9
```

现有`langgraph-checkpoint-postgres==3.1.0`与该组合可共同解析，
其要求的`langgraph-checkpoint>=4.1.0,<5.0.0`得到满足。

## 本地核心冒烟

执行：

```text
PYTHONPATH=src python -m unittest tests.test_langchain_core -v
```

结果：

```text
test_factory_and_structured_plan_use_langchain_runnable ... ok
test_tool_gateway_executes_structured_tool_and_returns_artifact ... ok
Ran 2 tests
OK
```

覆盖：

- Provider Factory选择LangChainModelProvider；
- Runnable生成并校验AnalysisPlan和ResearchReport；
- 模型Usage和标准AIMessage被保留；
- 实际ToolGateway执行StructuredTool；
- ToolMessage artifact保留完整ToolResult和数据域；
- 底层FinancialTool只被调用一次。

## 真实DeepSeek验证

使用`.env`当前模型配置执行一次LangChain Structured Output规划调用。

安全摘要：

```json
{
  "framework": "LangChainModelProvider",
  "model": "deepseek-v4-pro",
  "request_id_present": true,
  "task_names": [
    "market_query",
    "indicator_calculator"
  ],
  "total_tokens": 721,
  "message_type": "ai"
}
```

模型正确生成显式依赖计划，原始API Key未输出或写入证据文档。

## 发现并修复的问题

首次真实调用返回：

```text
400 Prompt must contain the word 'json' in some form to use
response_format of type 'json_object'.
```

原因是DeepSeek JSON模式要求Prompt显式声明JSON输出，而LangChain的
`with_structured_output(method="json_mode")`不会为该Provider自动补充提示语。

修复：在统一ChatPromptTemplate系统指令中加入“Return only one valid JSON object”。
修复后同一调用成功。

## 静态质量

```text
Ruff: All checks passed
compileall: passed
```

本Step未运行全量Regression、稳定性和Docker测试，符合三步计划；
Docker守护进程当前保持停止，集中验收留到Step 03。
