# Lab 4 — A2A Agent Communication

Реалізація двох A2A-сумісних агентів та демонстрація міжагентної комунікації за протоколом [A2A](https://a2a-protocol.org).

**Агенти:**
- `time-agent` — повертає поточний час для вказаного міста/таймзони
- `orchestrator-agent` — приймає запит від користувача, делегує до `time-agent` через A2A `message/send`

**Рівень:** Досвідчені

---

## Передумови

Розгортання відбувається в **GitHub Codespaces** (де є Docker, k3d, kubectl).
Abox кластер підіймається як в Lab 2.

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

### Збілдити образи

```bash
cd lab4-a2a
docker build -t time-agent:latest time-agent/
docker build -t orchestrator-agent:latest orchestrator-agent/
```

### Встановити kind CLI (якщо немає)

```bash
curl -Lo /tmp/kind https://kind.sigs.k8s.io/dl/v0.31.0/kind-linux-amd64
chmod +x /tmp/kind && sudo mv /tmp/kind /usr/local/bin/kind
```

### Завантажити образи в kind кластер

```bash
kind load docker-image time-agent:latest orchestrator-agent:latest --name abox
```

### Застосувати маніфести

```bash
kubectl apply -f k8s/
kubectl get pods -n kagent
```

### Перевірити в кластері

```bash
# Port-forward до orchestrator
kubectl port-forward svc/orchestrator-agent 8082:8080 -n kagent

# Agent Card
curl http://localhost:8082/.well-known/agent.json | jq

# A2A запит через orchestrator → time-agent
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
    ├── time-agent.yaml      # Deployment + Service
    └── orchestrator-agent.yaml
```
