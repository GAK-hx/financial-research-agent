# Step 06 Memory实现

## 1. 分层与边界

系统将Session Memory、Preference Memory、Evidence和LangGraph Checkpoint分开：

- Session Memory仅保存同一会话已确认的标的与时间范围，默认TTL为30天；
- Preference Memory仅保存用户显式确认的语言、篇幅和风险关注偏好；
- Evidence仍由正式Tool产生并带Source Locator与Snapshot，Memory不能替代取数；
- Checkpoint保存运行状态，不自动升级为长期用户事实。

模型只能提出候选内容，实际写入统一经过Memory Manager的字段白名单、身份范围、
敏感信息、TTL和版本校验。Preference未显式确认时返回422，不会落库。

## 2. 隔离与生命周期

Memory使用`tenant_id + user_id + session_id`复合范围。Session Memory要求三个字段
完全一致；Preference在同一租户与用户下跨Session可见，但不会跨用户或跨租户。

写入采用乐观版本控制；读取、更新、删除、过期和拒绝均记录审计事件。用户可通过
API查询、删除或触发过期清理。API Key、Bearer Token、密码和私钥文本会被拒绝。

## 3. LangGraph接入

正式StateGraph增加`load_memory`与`remember_query`节点：

```text
START → load_memory → interpret → remember_query → select_skill → …
```

`load_memory`只加载当前范围允许的记录；`interpret`可用Session Memory消解“它”
或“继续”等指代；`remember_query`只保存已解析的结构化实体。后续Plan、Tool和
Evidence流程不会因命中Memory而被跳过。

## 4. API

- `GET /memory`：按身份范围和类型查询；
- `POST /memory/preferences`：显式确认后写入Preference；
- `DELETE /memory/{memory_id}`：在所属范围内删除；
- `POST /memory/cleanup`：清理已过期记录。

同Session实测中，第二轮“继续分析它的最近三个月走势”恢复为`600519`，返回
`SESSION_REFERENCE_RESOLVED`警告，并重新执行行情及指标工具。
