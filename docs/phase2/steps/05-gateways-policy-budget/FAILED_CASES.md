# Step 05 失败与限制记录

## 1. 本次验证失败

本次107项全量测试和真实DeepSeek V4 Pro链路均通过，没有网络失败产物。

首次执行全量命令时，Zsh将未加引号的`?sslmode=disable`解释为文件通配符，测试尚未
启动。给该环境变量参数加单引号后正常完成。这不是代码或网络失败。

## 2. 非阻塞警告

- FastAPI测试提示`on_event`未来应迁移到Lifespan；
- TestClient提示Starlette/httpx兼容接口未来会变化；
- 个别异步测试出现约100ms的Debug慢Task提示；
- 以上均未造成用例失败，不在Step 05扩展范围内修改。

## 3. 已知设计限制

### Token/费用硬上限

当前Provider返回后才能得到精确Usage，因此Token和费用默认记录但不配置Run硬上限。
如果后续启用严格硬上限，必须请求前按Prompt和`max_tokens`Reserve保守上界，返回后
按真实Usage核销。不能把事后统计描述成请求前的费用保证。

### 单用户Policy

当前Policy覆盖模型操作、Skill Tool权限、只读、数据域、股票、日期和行数，不含
用户/租户RBAC。项目当前无登录和多租户，相关Identity Context应与Job API阶段共同
设计。

### DeepSeek思考模式

正式结构化调用默认关闭思考模式。已验证开启参数格式，但没有把模型改为原生多轮
Tool Caller；因此当前不处理`reasoning_content`多轮回传。

### Legacy兼容路径

旧版Legacy Runtime和纯内存单元测试保留直接组件调用，用于回归对照。正式
LangGraph + PostgreSQL路径已通过双Gateway集成测试。
