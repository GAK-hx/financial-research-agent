# Step 02 Evidence

## 实现结果

本Step形成四类标准适配入口：

```text
MilvusReportStore -> BaseRetriever -> Document -> Evidence
ContextBuilder -> RunnableLambda -> BuiltContext + Context Manifest
MemoryManager -> LangGraph BaseStore
SkillSelection -> Agent Context + StructuredTool可见范围
```

`ResearchRuntimeContext`在每次新运行中注入`tenant_id`、`user_id`、
`session_id`和`run_id`。运行身份放在LangGraph Runtime中，业务状态仍保留原字段；
进入记忆节点时会检查两者一致，避免通过调用参数切换数据范围。

## 增强能力组合冒烟

执行：

```text
pytest -q tests/test_langchain_enhancements.py
```

结果：

```text
1 passed in 1.81s
```

单条组合测试覆盖：

- Fake Milvus检索返回标准`Document`；
- `Document`转换为保留机构、页码和Locator的`Evidence`；
- `StructuredTool`返回标准`ToolMessage`，artifact中同时存在`ToolResult`和`Document`；
- `ContextBuilder Runnable`压缩100行批量数据；
- 压缩后`Evidence`保护校验通过，Token估算下降；
- Skill映射继续限制`report_search`可见范围并携带研报Evidence要求；
- LangGraph Store写入Session Memory，TTL生效；
- 不同Tenant无法读取该Session Memory；
- Runtime身份一致时通过，不一致时返回`RUNTIME_CONTEXT_SCOPE_MISMATCH`。

## 收口回归

执行：

```text
pytest -q \
  tests/test_langchain_enhancements.py \
  tests/test_langchain_core.py \
  tests/test_langgraph_runtime.py
```

结果：

```text
7 passed in 2.79s
```

另以`agent_framework=langchain`运行一次现有完整StateGraph受控样例：

```json
{
  "success": true,
  "tool_calls": 1,
  "stage": "completed"
}
```

这确认了Runtime Context和新适配入口没有破坏已有图节点、条件路由、
Tool执行、报告生成及终态写入语义。

## 静态质量

```text
Ruff: All checks passed
compileall: passed
```

## 验证中的非项目问题

最初临时环境使用Python 3.14，而项目声明的最低生产版本为Python 3.11。
由于`pyarrow<22`没有对应的Python 3.14预编译包，安装尝试进入本地源码编译并因缺少CMake失败。
随后改用本机Python 3.11建立隔离环境，依赖正常安装，全部测试通过。

该问题属于测试解释器选型，不是项目代码或Docker镜像缺陷。

## 延后项

Docker守护进程继续保持停止。本Step未启动PostgreSQL、API、Worker、SSE和Milvus生产服务；
这些基础设施链路将在Step 03与完整Regression一起集中验收。
