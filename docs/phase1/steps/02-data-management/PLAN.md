# Step 02 — 数据管理基础

## 目标

建立正式数据进入Agent前的统一管理框架：批次、标准化、质量、来源、表管理和Simulation隔离。

## 依赖

- Step 01完成。

## 任务

1. 定义`IngestionBatch`、`DataQualityResult`和`SourceMetadata`接口规范；
2. 建立`market`、`financial`、`metadata`、`simulation`命名规范；
3. 配置PyIceberg SQLite Catalog和file Warehouse；
4. 定义单写者、批量append和小文件控制规则；
5. 定义行级拒绝与批次状态规则；
6. 建立数据源字段映射版本；
7. 记录batch_id、source、时间范围、输入/输出/拒绝数量和snapshot；
8. 定义Raw、Standardized、Curated、Derived、Simulation分级；
9. 建立Repository只读边界；
10. 编写数据管理接口一致性测试。

## 交付物

- Metadata模型和存储方案；
- Catalog/Warehouse配置；
- 数据质量规则接口；
- Repository基类；
- 数据分级和Simulation隔离测试。

## 验收标准

- 能创建并读取测试表；
- 每次写入都有batch元数据；
- 失败行不会进入Curated表；
- Simulation表不能被正式Repository访问；
- 重复batch_id处理策略明确。

## 风险

- SQLite Catalog不适合并发写：第一阶段强制单写者；
- 逐行append产生小文件：只允许批量写入。
