# DeepSeek V4 Pro 1M接入说明

## 1. 官方调用配置

本项目使用DeepSeek官方OpenAI格式Chat Completions：

```text
Base URL: https://api.deepseek.com
Model: deepseek-v4-pro
Context: 1,000,000 tokens
Maximum output capability: 384,000 tokens
```

项目单次规划和报告仍分别限制为4096和8192输出Token。模型能力上限不是应用应默认
用满的生成长度。

## 2. 结构化输出

规划和报告请求设置：

```json
{
  "response_format": {"type": "json_object"},
  "thinking": {"type": "disabled"}
}
```

Prompt中明确要求JSON、提供Pydantic Schema和结构示例，并在返回后再次执行
Pydantic和领域Validator。JSON Output只能保证JSON语法，不能替代业务校验。

## 3. 为什么默认关闭思考模式

当前模型只做一次规划或一次报告生成，不负责直接执行Tool。非思考模式：

- 更适合稳定获取结构化JSON；
- 不需要保存或回传隐藏推理；
- 减少上下文和审计复杂度；
- `temperature=0`可继续用于当前确定性结构化请求。

若启用思考模式，使用：

```json
{
  "thinking": {"type": "enabled"},
  "reasoning_effort": "high"
}
```

思考模式不依赖`temperature`。若未来采用模型原生多轮Tool Calls，发生Tool Call的
轮次必须完整回传`reasoning_content`，否则DeepSeek会返回400。

## 4. 当前人民币价格配置

按2026-07-26官方中文价格页，V4 Pro每百万Token：

| 类型 | 人民币 |
|---|---:|
| 输入缓存命中 | 0.025元 |
| 输入缓存未命中 | 3元 |
| 输出 | 6元 |

价格可能变化，因此通过环境变量配置，不硬编码到Provider。

## 5. Provider命名

`MODEL_PROVIDER=openai_compatible`描述的是项目内部Adapter协议，不表示使用
OpenAI服务。DeepSeek官方明确支持OpenAI格式接口，因此这种命名和实现是合理的；
真实供应商和模型仍由`MODEL_BASE_URL`与`MODEL_NAME`明确记录。
