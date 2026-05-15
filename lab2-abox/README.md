# Lab 2 — Agentic Box (abox)

Розгортання повного agentic-стеку: KinD + Flux GitOps + agentgateway + kagent.

## Стек

| Компонент | Версія | Призначення |
|---|---|---|
| [abox](https://github.com/den-vasyliev/abox) | main | Bootstrap-обгортка над усім стеком |
| KinD | latest | Локальний Kubernetes (1 control-plane + 2 workers) |
| Flux CD | 2.x | GitOps-оркестрація через OCI artifacts |
| agentgateway | v2.2.1 | AI-aware API Gateway |
| kagent | 0.7.23 | Agent runtime для Kubernetes |
| OpenAI | GPT-4o-mini | LLM-провайдер |

## Структура директорії

```
lab2-abox/
├── abox/           # Git submodule — форк https://github.com/den-vasyliev/abox
├── k8s/            # Beginner: declarative MCP-сервер та агент (kubectl apply)
├── releases/       # Advanced: GitOps-розгортання через Flux OCI
└── README.md
```

---

## Завдання 1 — Розгортання abox

> Виконується у **GitHub Codespaces**. Рекомендований розмір машини: **4-core / 16 GB**.

### Підготовка Codespaces

Встанови секрет `OPENAI_API_KEY` у налаштуваннях Codespaces перед стартом:
`Settings → Secrets and variables → Codespaces → New repository secret`

### Клонування репо з submodule

```bash
git clone --recurse-submodules https://github.com/<your-org>/AI_Reliability_Engineering_2.git
cd AI_Reliability_Engineering_2/lab2-abox
```

Якщо репо вже клоновано без submodule:

```bash
git submodule update --init --recursive
```

### Розгортання

```bash
cd abox

# Встановлює tofu, k9s, cloud-provider-kind,
# ініціалізує та застосовує OpenTofu (KinD + Flux bootstrap)
make run

# Переконайся що kubeconfig налаштований
export KUBECONFIG=~/.kube/config
kubectl get nodes
```

Очікуваний результат — 3 вузли зі статусом `Ready`:

```
NAME                 STATUS   ROLES           AGE
abox-control-plane   Ready    control-plane   ...
abox-worker          Ready    <none>          ...
abox-worker2         Ready    <none>          ...
```

### Перевірка Flux

```bash
flux get all -A
```

Всі ресурси мають бути `Ready: True`.

---

## Завдання 2 — Доступ до UI

### Kagent UI + agentgateway (через LoadBalancer)

```bash
# Отримай IP agentgateway LoadBalancer
kubectl get svc -n agentgateway-system

# Kagent UI
open http://<EXTERNAL-IP>/

# kagent API
open http://<EXTERNAL-IP>/api
```

### agentgateway Admin UI

```bash
kubectl port-forward -n agentgateway-system deploy/agentgateway 15000:15000
open http://localhost:15000
```

### Flux (перегляд reconciliation)

```bash
# Стан усіх Flux ресурсів
flux get all -A

# Події reconciliation
kubectl get events -n flux-system --sort-by='.lastTimestamp'
```

---

## Завдання 3 — MCP-сервер та агент у Kagent (Beginner)

### 3.1 Підключення моделі

Kagent вже налаштований на OpenAI GPT-4o-mini через `OPENAI_API_KEY` з env-змінної.
Перевір що секрет існує:

```bash
kubectl get secret kagent-openai -n kagent
```

Якщо немає — створи вручну:

```bash
kubectl create secret generic kagent-openai \
  --from-literal=OPENAI_API_KEY=$OPENAI_API_KEY \
  -n kagent
```

### 3.2 Створення MCP-сервера та агента

```bash
# Застосуй declarative конфігурацію з k8s/
kubectl apply -k k8s/

# Перевір ресурси
kubectl get mcpservers,agents -n kagent
kubectl get pods -n kagent
```

### 3.3 Тест агента

Відкрий Kagent UI → вибери агента `k8s-monitor-agent` → запит:

```
What pods are running in the cluster?
```

---

## Завдання 4 — GitOps-розгортання (Advanced)

> MCP-сервер та агент розгортаються через Flux OCI artifacts, а не через прямий `kubectl apply`.

### 4.1 Додай ресурси до releases/

Скопіюй файли з `k8s/` у `abox/releases/`:

```bash
cp k8s/mcp-k8s-server.yaml abox/releases/
cp k8s/kagent-agent.yaml   abox/releases/
```

Додай їх до `abox/releases/kustomization.yaml`:

```yaml
resources:
  - agentgateway.yaml
  - kagent.yaml
  - mcp-k8s-server.yaml    # +
  - kagent-agent.yaml      # +
```

### 4.2 Налаштуй OCI registry на свій fork

У `abox/bootstrap/variables.tf`:

```hcl
variable "oci_registry" {
  default = "oci://ghcr.io/yupyvovarov/abox"
}
```

### 4.3 Тригер reconciliation

```bash
cd abox

# Перевір що flux get all -A показує Ready перед пушем
flux get all -A

# Bump patch version, tag і push → CI публікує OCI artifact → Flux reconciles
make push
```

Слідкуй за reconciliation:

```bash
flux get kustomizations -A --watch
```

---

## Корисні команди

```bash
# Логи kagent controller
kubectl logs -n kagent deploy/kagent-controller -f

# Перегляд усіх Flux ресурсів
flux get all -A

# Форс-reconciliation (без очікування таймера)
flux reconcile kustomization releases -n flux-system

# Знищити кластер
cd abox && make down
```
