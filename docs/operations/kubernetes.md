# Kubernetes部署

`deploy/k8s/base`是通用Kustomize Base，`deploy/k8s/kind`是本地资源缩减Overlay。

## 资源

- Deployment：Gateway、API、Worker；
- Job：数据库迁移；
- CronJob：湖命名空间幂等初始化；
- HPA、PDB、readiness/liveness和NetworkPolicy；
- 非root、只读根文件系统、最小capability和独立ServiceAccount；
- ConfigMap管理非敏感配置，Secret由部署环境创建，不进入Git。

## 本地Kind

```bash
/tmp/kind create cluster \
  --config deploy/k8s/kind/cluster.yaml \
  --name financial-agent
kubectl create namespace financial-agent --dry-run=client -o yaml | kubectl apply -f -
```

创建`financial-agent-secrets`后：

```bash
kubectl apply -k deploy/k8s/kind
kubectl -n financial-agent wait --for=condition=complete job/db-migrate --timeout=300s
kubectl -n financial-agent rollout status deployment/job-api --timeout=300s
kubectl -n financial-agent rollout status deployment/job-worker --timeout=300s
kubectl -n financial-agent rollout status deployment/backend-gateway --timeout=300s
```

仓库中的`deploy/k8s/base/secret.example.yaml`只描述字段，不包含值。

## 生产差异

- RWO湖PVC替换为对象存储；
- 本地PostgreSQL和Redis替换为托管持久化服务；
- 使用External Secrets或云Secret Manager；
- 安装metrics-server或云监控后重新验证HPA；
- 配置Ingress、TLS、多可用区和备份恢复；
- 湖初始化CronJob不能冒充完整的定时增量采集任务。
