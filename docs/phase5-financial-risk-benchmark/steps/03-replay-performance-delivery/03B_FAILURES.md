# 03-B 失败与处置记录

## Docker 合并回归无法加载 pytest 文件

首次命令：

```text
docker compose --profile risk-cached run --rm risk-step01-cached-eval
python -m unittest tests.test_retrieval_cache tests.test_risk_foundation -v
```

关键原始输出：

```text
test_retrieval_cache (unittest.loader._FailedTest.test_retrieval_cache) ... ERROR
ModuleNotFoundError: No module named 'pytest'

Ran 15 tests
FAILED (errors=1)
```

同一次运行中，`tests.test_risk_foundation` 的14个用例全部通过。失败发生在测试模块导入阶段：
`test_retrieval_cache.py` 使用 pytest 标记，而 `risk-step01-cached-eval` 复用生产评测镜像，生产核心依赖不包含
pytest。

处置：

- 不把 pytest 加入生产运行依赖；
- 风险适配层通过 Docker 03-B 完整 Gate 验证；
- `test_retrieval_cache.py` 使用本地开发环境的 pytest 执行；
- 该问题不记为缓存功能失败，但保留记录，避免把“测试未运行”误写成“测试通过”。

## 开发环境回归暴露固定日期夹具过期

关键输出：

```text
test_web_tool_indexes_versions_and_returns_traceable_evidence FAILED
WEB_SEARCH_EMPTY: public web search returned no traceable documents
1 failed, 3 passed
```

原因：测试查询窗口固定在2026-08-01至2026-08-15，但伪造文档的发布时间使用运行时当前时间。当前日期已晚于
查询窗口，文档被正确过滤，导致原本用于验证索引的测试失去输入。

修正：伪造 Provider 将文档发布时间绑定到请求的 `end_date`，使夹具表达固定业务条件，不再依赖执行当天。
该修正未放宽生产筛选逻辑。
