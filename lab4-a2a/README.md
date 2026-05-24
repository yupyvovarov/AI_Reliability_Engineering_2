# Lab 4 — A2A Agent Communication

Реалізація двох A2A-сумісних агентів та демонстрація міжагентної комунікації за протоколом [A2A](https://a2a-protocol.org).

**Агенти:**
- `time-agent` — повертає поточний час для вказаного міста/таймзони
- `orchestrator-agent` — приймає запит від користувача, делегує до `time-agent` через A2A `message/send`

**Рівень:** Досвідчені

---

## A2A агенти vs Kagent агенти

Наші `time-agent` і `orchestrator-agent` існують у двох формах:

| | A2A (Deployment) | Kagent (CRD) |
|---|---|---|
| Протокол | A2A JSON-RPC (`message/send`) | AutoGen runtime |
| Як викликати | `curl POST /` або будь-який A2A клієнт | Kagent UI / API |
| Визначення | Kubernetes Deployment + Service | `kagent.dev/v1alpha2 Agent` CRD |
| Видимість | Не в Kagent UI, не в Inventory | Kagent UI + Inventory |

Щоб агенти з'явились у **Kagent UI та Inventory**, потрібно застосувати kagent Agent CRDs:

```bash
kubectl apply -f lab4-a2a/k8s/kagent-agents.yaml
kubectl get agents -n kagent
```

---

## Передумови

Розгортання відбувається в **GitHub Codespaces** (де є Docker, kind, kubectl).
Abox кластер підіймається як в Lab 2 (KinD, cluster name `abox`).

> MacBook/локально: агентів можна перевірити через venv (див. розділ 1), але розгортання на abox потребує Codespaces.

---

## 1. Локальна перевірка (venv)

### Створити virtual environment

```bash
cd lab4-a2a
python3 -m venv .venv
source .venv/bin/activate
pip install -r time-agent/requirements.txt -r orchestrator-agent/requirements.txt
```

### Запустити time-agent

```bash
uvicorn time-agent.main:app --port 8081 --reload
```

Перевірити Agent Card:

```bash
curl http://localhost:8081/.well-known/agent.json | jq
```

Перевірити A2A endpoint:

```bash
curl -s http://localhost:8081/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
      "message": {
        "messageId": "m1",
        "role": "user",
        "parts": [{"kind": "text", "text": "Kyiv"}]
      }
    }
  }' | jq
```

### Запустити orchestrator-agent (в окремому терміналі)

```bash
cd lab4-a2a
source .venv/bin/activate
TIME_AGENT_URL=http://localhost:8081 uvicorn orchestrator-agent.main:app --port 8082 --reload
```

Перевірити A2A комунікацію між агентами:

```bash
curl -s http://localhost:8082/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
      "message": {
        "messageId": "m1",
        "role": "user",
        "parts": [{"kind": "text", "text": "What time is it in Kyiv?"}]
      }
    }
  }' | jq
```

---

## 2. Розгортання на abox (GitHub Codespaces)

### Запустити abox кластер

```bash
cd lab2-abox/abox
make run
```

### Встановити kind CLI (якщо немає)

```bash
curl -Lo /tmp/kind https://kind.sigs.k8s.io/dl/v0.31.0/kind-linux-amd64
chmod +x /tmp/kind && sudo mv /tmp/kind /usr/local/bin/kind
```

### 2a. A2A Deployment (перевірка протоколу в кластері)

Збілдити образи та завантажити в kind:

```bash
cd lab4-a2a
docker build -t time-agent:latest time-agent/
docker build -t orchestrator-agent:latest orchestrator-agent/
kind load docker-image time-agent:latest orchestrator-agent:latest --name abox
```

Застосувати A2A Deployments:

```bash
kubectl apply -f lab4-a2a/k8s/time-agent.yaml
kubectl apply -f lab4-a2a/k8s/orchestrator-agent.yaml
kubectl get pods -n kagent
```

Перевірити A2A в кластері:

```bash
kubectl port-forward svc/orchestrator-agent 8082:8080 -n kagent

curl -s http://localhost:8082/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
      "message": {
        "messageId": "m1",
        "role": "user",
        "parts": [{"kind": "text", "text": "What time is it in Kyiv?"}]
      }
    }
  }' | jq '.result.status.message.parts[0].text'
```

### 2b. Kagent Agent CRDs (інтеграція з Kagent UI + Inventory)

> **Важливо:** A2A Deployments з namespace `kagent` конфліктують з kagent Agent CRDs (однакові імена, різні лейбли). Перед застосуванням CRDs видали A2A Deployments:
>
> ```bash
> kubectl delete deployment time-agent orchestrator-agent -n kagent
> kubectl delete service time-agent orchestrator-agent -n kagent
> ```

Застосувати kagent Agent CRDs:

```bash
kubectl apply -f lab4-a2a/k8s/kagent-agents.yaml
kubectl get agents -n kagent
```

Обидва агенти мають показати `ACCEPTED: True`. Після цього вони з'являться в Kagent UI та Inventory.

---

## 3. Inventory — перелік AI ресурсів кластера

[agentregistry-inventory](https://github.com/den-vasyliev/agentregistry-inventory) — контрол плейн для AI інфраструктури.
Автоматично сканує кластер і каталогізує MCP servers, агентів, моделі. UI на порті 8080, MCP server на 8083.

### Встановити CRDs та Helm chart

```bash
kubectl apply -f https://raw.githubusercontent.com/den-vasyliev/agentregistry-inventory/main/config/crd/agentregistry.dev_agentcatalogs.yaml \
  -f https://raw.githubusercontent.com/den-vasyliev/agentregistry-inventory/main/config/crd/agentregistry.dev_mcpservercatalogs.yaml \
  -f https://raw.githubusercontent.com/den-vasyliev/agentregistry-inventory/main/config/crd/agentregistry.dev_modelcatalogs.yaml \
  -f https://raw.githubusercontent.com/den-vasyliev/agentregistry-inventory/main/config/crd/agentregistry.dev_skillcatalogs.yaml \
  -f https://raw.githubusercontent.com/den-vasyliev/agentregistry-inventory/main/config/crd/agentregistry.dev_discoveryconfigs.yaml \
  -f https://raw.githubusercontent.com/den-vasyliev/agentregistry-inventory/main/config/crd/agentregistry.dev_registrydeployments.yaml

git clone https://github.com/den-vasyliev/agentregistry-inventory.git /tmp/inventory
helm install agentregistry-inventory /tmp/inventory/charts/agentregistry -n agentregistry --create-namespace
```

### Застосувати DiscoveryConfig

Конфігурує Inventory сканувати namespace `kagent` де живуть наші агенти та MCP servers:

```bash
kubectl apply -f lab4-a2a/k8s/discoveryconfig.yaml
```

### Відкрити UI

```bash
kubectl port-forward svc/agentregistry-inventory-api -n agentregistry 8083:8080
```

Відкрити у браузері через вкладку Ports в Codespaces на порті 8083.

### Перевірити список AI ресурсів

```bash
kubectl get agentcatalogs,mcpservercatalogs -n agentregistry
```

---

## 4. MCPG — MCP Security Governance

[mcp-security-governance](https://github.com/techwithhuz/mcp-security-governance) — Kubernetes-native security monitoring для MCP інфраструктури.
Скануює MCP servers і виставляє security score (0-100, grades A-F) по 7 категоріях (AgentGateway, Auth, RBAC, CORS, TLS, Tool Scope, Hardened Deployment).
Dashboard на порті 3000.

### Встановити Helm chart

```bash
# Оновити CRD до актуальної версії
kubectl apply -f https://raw.githubusercontent.com/techwithhuz/mcp-security-governance/main/deploy/crds/governance-crds.yaml

# Встановити без sample policy (sample несумісний з CRD схемою v0.22.2)
helm install mcp-governance \
  oci://ghcr.io/techwithhuz/charts/mcp-governance \
  --version 0.22.2 \
  --namespace mcp-governance \
  --create-namespace \
  --set samples.install=false
```

### Застосувати Governance Policy

```bash
kubectl apply -f lab4-a2a/k8s/governance-policy.yaml
```

### Відкрити Dashboard

```bash
kubectl port-forward svc/mcp-governance-dashboard -n mcp-governance 3001:3000
```

Відкрити у браузері через вкладку Ports в Codespaces на порті 3001.

---

## 5. Qdrant — Vector Database

[qdrant-helm](https://github.com/qdrant/qdrant-helm) — Helm chart для розгортання Qdrant vector database на Kubernetes.

### Встановити Helm chart

```bash
helm repo add qdrant https://qdrant.github.io/qdrant-helm
helm repo update
helm upgrade -i qdrant qdrant/qdrant \
  --namespace qdrant \
  --create-namespace
```

### Перевірити розгортання

```bash
kubectl get pods -n qdrant
kubectl get svc -n qdrant
```

### Перевірити REST API

```bash
kubectl port-forward svc/qdrant -n qdrant 6333:6333
curl http://localhost:6333/healthz
```

---

## Структура файлів

```
lab4-a2a/
├── time-agent/
│   ├── main.py              # FastAPI + A2A endpoint + timezone logic
│   ├── requirements.txt
│   └── Dockerfile
├── orchestrator-agent/
│   ├── main.py              # FastAPI + A2A endpoint + викликає time-agent
│   ├── requirements.txt
│   └── Dockerfile
└── k8s/
    ├── time-agent.yaml           # A2A Deployment + Service (для тестування протоколу)
    ├── orchestrator-agent.yaml   # A2A Deployment + Service (для тестування протоколу)
    ├── kagent-agents.yaml        # MCPServer + kagent Agent CRDs (для Kagent UI + Inventory)
    ├── discoveryconfig.yaml      # Inventory DiscoveryConfig для kagent namespace
    └── governance-policy.yaml    # MCPGovernancePolicy для abox кластера
```
