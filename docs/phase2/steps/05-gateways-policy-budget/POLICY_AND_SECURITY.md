# Step 05 Policy与安全边界

## 1. 当前Policy版本

当前版本为`financial_read_only_v1`。每个允许或拒绝决定都有：

- Run和Node；
- Model/Tool动作；
- 资源名；
- Allow/Deny；
- 稳定Reason Code；
- Policy版本；
- 安全详情；
- 完整上下文的规范化Hash。

数据库不保存API Key。完整参数只用于计算Hash，Policy审计详情只保留版本、数据域、
只读标志和操作类型。

## 2. Model规则

仅允许三类操作：

| 操作 | 用途 |
|---|---|
| `plan` | 生成结构化Analysis Plan |
| `generate_report` | 根据当前Run Evidence生成报告 |
| `revise_report` | 根据Validator错误做一次受控修订 |

未知操作、未配置模型或缺少Base URL/API Key均拒绝。模型没有Shell、SQL、数据库或
文件系统权限。

## 3. Tool规则

一次Tool调用必须同时满足：

1. Tool在正式Registry中；
2. Tool声明为只读；
3. 数据域不是`simulation`；
4. Tool在当前Run Skill Snapshot的有效白名单中；
5. 输入通过对应Pydantic模型；
6. 股票属于Query；
7. 日期不扩展到Query之外；
8. 行数、周期数或Top K不超过Tool上限。

Policy只负责授权边界，Plan Validator和Skill Validator仍然保留。多层校验不是重复，
而是分别防止结构错误、Skill越权和执行前参数越权。

## 4. 脱敏策略

- `.env`不进入镜像，也不写入响应；
- Authorization Header不进入数据库；
- Model Call只保存Request Hash和安全摘要；
- Tool Call只保存Input Hash；
- Policy保存Context Hash；
- 原始Tool异常文本不返回、不持久化；
- DeepSeek思考模式默认关闭，因此正式结构化调用不保存`reasoning_content`。

若以后启用思考模式和模型原生多轮Tool Calls，必须完整回传当前轮
`reasoning_content`以满足DeepSeek协议，但仍不得把它写入Graph State、Event或日志。

## 5. 当前不包含的边界

项目当前是单用户本地研究系统，因此尚未实现租户、RBAC和用户级数据授权。现有
Policy接口保留Run/Node/Resource维度；引入登录与多租户后再增加Identity Context，
不在本Step虚构尚不存在的权限体系。
