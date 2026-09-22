# 03-C 失败与处置记录

## Spark Zstd JNI 无法从加固容器的 `/tmp` 加载

首次10万行 Smoke 在 Parquet 写入阶段失败，尚未进入聚合或 Iceberg 提交。

关键原始输出：

```text
SparkException: [TASK_WRITE_FAILED] Task failed while writing rows
Caused by: java.lang.UnsatisfiedLinkError:
/tmp/libzstd-jni-1.5.7-7....so: failed to map segment from shared object
Unsupported OS/arch, cannot find /linux/aarch64/libzstd-jni-1.5.7-7.so
```

根因并非架构不受支持，而是安全配置下 `/tmp` 为不可执行 tmpfs；Zstd JNI 将动态库释放到该目录后无法映射。

处置：Spark 合成源 Parquet 改用 Gzip。没有把 `/tmp` 改成可执行，也没有增加容器权限。PyIceberg 后续仍
按自身 Arrow 写入路径管理数据文件。修正后同一个10万行Smoke通过，随后500万行正式Gate通过。
