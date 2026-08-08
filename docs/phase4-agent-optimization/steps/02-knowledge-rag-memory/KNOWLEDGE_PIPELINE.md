# 外部事件知识流水线

## 1. 为什么需要单独的知识流水线

行情和财务数据可以通过确定性 Tool 精确查询；公告、新闻和公司事件则带有来源、发布时间、
转载、修订和冲突。它们不能直接写进用户记忆，也不能抓到后立刻交给模型使用。

本实现把“原始事件”和“可用于报告的知识”分开：

```text
来源适配器
  → 读取 PostgreSQL 游标
  → 原始 JSON 追加到 Iceberg knowledge.raw_events_v1
  → 标准化为 CANDIDATE
  → 校验来源、时间、股票实体和证据
      ├─ 通过：ACTIVE
      └─ 失败：REJECTED
  → ACTIVE 才能进入在线 Context 和查询接口
```

## 2. 当前来源边界

当前没有把未确认授权和稳定性的外部接口写成“实时新闻源”。首个适配器读取项目自带的可分发
演示事件，目的是验证协议、游标、落湖、状态机、冲突和检索链路。

替换为真实来源时，适配器必须给出：

- 稳定的 `source_record_id`；
- 原始 URL 和使用许可；
- `event_time`、`published_at`、`available_at`；
- 正文和股票实体依据；
- 翻页游标或高水位；
- 修订、删除和限流规则。

来源不满足这些字段时只能作为候选实验，不能进入正式报告。

## 3. 数据放置

| 数据 | 位置 | 作用 |
|---|---|---|
| 原始来源载荷 | Iceberg `knowledge.raw_events_v1` | 不可变回溯、批处理和快照定位 |
| 来源游标/高水位 | PostgreSQL `knowledge_source_cursors` | 断点恢复 |
| 标准化事件 | PostgreSQL `knowledge_events` | 状态、过滤和在线查询 |
| 状态变化 | PostgreSQL `knowledge_event_transitions` | 证明 Candidate 未被直接使用 |

每条正式事件同时保留原始 Iceberg Locator 和来源 URL。Iceberg 原始层允许保留重复抓取痕迹，
标准化层通过 `source_id + source_record_id + raw_version` 保证有效事件幂等。

## 4. 时间和冲突

- `event_time`：事件发生时间；
- `published_at`：来源公开时间；
- `available_at`：系统或市场可获得时间；
- `ingested_at`：本项目采集时间。

回测或历史问答应使用 `available_at` 防止未来信息泄漏。相同规范事件如果出现不同正文，两个
来源都保留为 ACTIVE，并共享 `conflict_group`；系统不在入库阶段替用户“平均”冲突。

## 5. 在线边界

`GET /knowledge/events` 只返回 ACTIVE 事件。LangGraph 的 Context Builder 也只从
`KnowledgeStore.search_active` 读取；CANDIDATE、REJECTED 和 SUPERSEDED 不进入模型上下文。
Step 03 再在该查询层之上增加事件分析 Tool 和 Skill，不让模型直接访问数据库。
