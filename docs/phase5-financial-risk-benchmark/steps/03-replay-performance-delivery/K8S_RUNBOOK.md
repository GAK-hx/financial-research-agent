# Kubernetes 本地部署与故障演练手册

## 运行边界

本手册使用 Kind 的1个control-plane和2个worker容器。它们共享同一台Mac的CPU、内存、磁盘和Docker
Daemon，只用于验证Kubernetes资源、调度和恢复流程，不等价于三台生产服务器。

通用Base位于 `deploy/k8s/base/`；本地依赖和资源缩减位于 `deploy/k8s/kind/`。仓库只提供
`secret.example.yaml`，实际Secret不得提交Git。

Base不是可直接照搬的云上生产拓扑：当前湖文件使用共享PVC；正式多节点环境应替换为对象存储，并继续使用
PostgreSQL或REST Catalog，不能把单机SQLite Catalog作为多副本共享元数据服务。

## 预计资源

- Kind节点镜像：约1 GiB级别，实际以官方镜像为准；
- 项目镜像：复用本地已构建镜像，合计约9 GiB，节点内部导入会增加Docker存储；
- 运行内存：建议至少8 GiB可用，本地Overlay只启动1副本API、Worker和Gateway；
- 临时PostgreSQL与Redis：约768 MiB上限；
- 本地湖与Artifact：默认2 GiB以内。

## 1. 安装Kind

本轮查询到的稳定版为v0.33.0。Apple Silicon使用官方`kind-darwin-arm64`：

```bash
curl -Lo /tmp/kind https://github.com/kubernetes-sigs/kind/releases/download/v0.33.0/kind-darwin-arm64
chmod +x /tmp/kind
/tmp/kind version
```

本项目已使用该版本完成一次本地三逻辑节点实测。版本号仍应在升级前从Kind官方Release复核。

## 2. 创建三节点逻辑集群

使用与Kind v0.33.0对应的官方节点镜像：

```bash
/tmp/kind create cluster \
  --config deploy/k8s/kind/cluster.yaml \
  --image kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5
kubectl get nodes -o wide
```

预期为1个control-plane与2个worker，全部Ready。

## 3. 导入本地镜像

若当前源码晚于本地镜像，先只重建API镜像（Worker复用同一镜像）：

```bash
docker compose --profile harness build --provenance=false job-api
```

```bash
/tmp/kind load docker-image financial-research-agent-job-api:latest --name financial-agent
/tmp/kind load docker-image financial-research-agent-db-migrate:latest --name financial-agent
/tmp/kind load docker-image financial-research-agent-backend-gateway:latest --name financial-agent
```

PostgreSQL和Redis镜像也可预先导入，避免集群再次联网拉取：

```bash
docker buildx build --platform linux/arm64 --provenance=false --load \
  --build-arg BASE_IMAGE=postgres:17.10-alpine3.23 \
  -t financial-agent-postgres-kind:17.10 \
  -f deploy/k8s/kind/Dockerfile.local-base deploy/k8s/kind
docker buildx build --platform linux/arm64 --provenance=false --load \
  --build-arg BASE_IMAGE=redis:8.4-alpine \
  -t financial-agent-redis-kind:8.4 \
  -f deploy/k8s/kind/Dockerfile.local-base deploy/k8s/kind
/tmp/kind load docker-image financial-agent-postgres-kind:17.10 --name financial-agent
/tmp/kind load docker-image financial-agent-redis-kind:8.4 --name financial-agent
```

本地重标记用于绕开Containerd导入多平台证明层的已知问题，不改变上游镜像内容；Kind Overlay引用本地标签，
通用Base仍引用官方PostgreSQL和Redis镜像。

## 4. 创建Secret

先创建Namespace：

```bash
kubectl create namespace financial-agent --dry-run=client -o yaml | kubectl apply -f -
```

先在当前终端设置随机的本地演练口令与连接串；不要写入仓库：

```bash
read -s POSTGRES_PASSWORD; export POSTGRES_PASSWORD
read -s REDIS_PASSWORD; export REDIS_PASSWORD
export CHECKPOINT_DATABASE_URL="postgresql://agent:${POSTGRES_PASSWORD}@postgres:5432/financial_agent?sslmode=disable"
export BUSINESS_DATABASE_URL="postgresql+asyncpg://agent:${POSTGRES_PASSWORD}@postgres:5432/financial_agent"
export ICEBERG_CATALOG_URI="postgresql+psycopg://agent:${POSTGRES_PASSWORD}@postgres:5432/financial_agent"
export REDIS_URL="redis://:${REDIS_PASSWORD}@redis:6379/0"
```

再从本机环境变量创建Secret。命令只引用变量名，不要把真实值写进文档或Git：

```bash
kubectl -n financial-agent create secret generic financial-agent-secrets \
  --from-literal=MODEL_API_KEY="$MODEL_API_KEY" \
  --from-literal=AGENT_API_KEY="$AGENT_API_KEY" \
  --from-literal=GATEWAY_INTERNAL_API_KEY="$AGENT_API_KEY" \
  --from-literal=GATEWAY_SECURITY_EXTERNAL_API_KEY="$GATEWAY_EXTERNAL_API_KEY" \
  --from-literal=GATEWAY_SECURITY_API_CLIENTS="$GATEWAY_API_CLIENTS" \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  --from-literal=REDIS_PASSWORD="$REDIS_PASSWORD" \
  --from-literal=CHECKPOINT_DATABASE_URL="$CHECKPOINT_DATABASE_URL" \
  --from-literal=BUSINESS_DATABASE_URL="$BUSINESS_DATABASE_URL" \
  --from-literal=ICEBERG_CATALOG_URI="$ICEBERG_CATALOG_URI" \
  --from-literal=REDIS_URL="$REDIS_URL"
```

这些本地数据库密码只用于一次性Kind集群；生产应由External Secrets或云Secret Manager注入。

## 5. 部署

先启动本地依赖并等待健康，再应用完整Overlay：

```bash
kubectl apply -f deploy/k8s/kind/dependencies.yaml -n financial-agent
kubectl -n financial-agent rollout status deployment/postgres --timeout=180s
kubectl -n financial-agent rollout status deployment/redis --timeout=180s
kubectl apply -k deploy/k8s/kind
kubectl -n financial-agent wait --for=condition=complete job/db-migrate --timeout=300s
kubectl -n financial-agent rollout status deployment/job-api --timeout=300s
kubectl -n financial-agent rollout status deployment/job-worker --timeout=300s
kubectl -n financial-agent rollout status deployment/backend-gateway --timeout=300s
```

若迁移Job在PostgreSQL就绪前失败，应删除Job后重新应用，不要修改数据库内容绕过迁移。

## 6. 健康检查

```bash
kubectl -n financial-agent port-forward service/backend-gateway 18080:8080
curl -fsS http://127.0.0.1:18080/actuator/health/readiness
kubectl -n financial-agent get pods,job,cronjob,hpa,pdb,networkpolicy
```

随后用已有API client提交一条最小任务，确认Gateway、Job API、PostgreSQL Job和Worker完整贯通。

## 7. 故障演练

必须保存每项命令、时间、Job状态和事件序列：

1. 滚动更新：修改无业务影响的ConfigMap版本注解，观察Gateway和API滚动期间健康端点可用；
2. Worker驱逐：任务处于running后删除Worker Pod，等待租约到期，由新Worker接管；
3. Redis降级：删除Redis Pod，已有Job事实仍可由PostgreSQL读取；Redis恢复后热状态重建；
4. Job重试：运行湖初始化Job，失败修复后重新运行，确认命名空间初始化幂等；
5. SSE重连：记录Last-Event-ID，在Gateway重启后续传，终态只出现一次。

硬门槛：任务丢失0、重复终态0、跨租户读取0、未授权Tool 0。任何一项失败都不能把03-D标记完成。

本地Kind未默认安装metrics-server，因此HPA的资源、上下限和目标值可验证，但`TARGETS`会显示`unknown`，
不能把该环境写成已经完成动态扩缩容压测。云上部署还需补对象存储、托管数据库、多可用区与真实容量测试。

## 8. 清理

```bash
/tmp/kind delete cluster --name financial-agent
```

删除集群不会删除宿主机项目镜像。确认不再使用后再单独清理，禁止批量删除项目外Docker资源。
