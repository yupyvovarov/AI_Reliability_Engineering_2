# Лаб 1 — Basic Agentic Infrastructure (Max Track)

Розгортання **agentgateway** + **kagent** у Kubernetes кластері через **Gateway API**.

- Namespace: `yuriip-ai-reliability-engineering-2`
- LLM провайдер: OpenAI (`gpt-4o-mini`)
- Gateway API CRDs: `v1.5.1`
- agentgateway Helm chart: `1.1.0`
- kagent Helm chart: `0.9.2`

---

## Передумови

- `kubectl` налаштований для доступу до EKS кластера
- `helm`

---

## Крок 1 — Налаштувати Secrets та ConfigMap для API ключів та конфігурації

Створити namespace:

```bash
kubectl apply -f k8s/namespace.yaml
```

Створити секрет для **agentgateway** (ключ `Authorization`, agentgateway сам додає `Bearer` для OpenAI):

```bash
kubectl create secret generic openai-agentgateway-secret \
  --namespace yuriip-ai-reliability-engineering-2 \
  --from-literal=Authorization="$OPENAI_API_KEY"
```

Створити секрет для **kagent** (ключ `OPENAI_API_KEY`):

```bash
kubectl create secret generic kagent-openai \
  --namespace yuriip-ai-reliability-engineering-2 \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY"
```

> Встановити змінну перед запуском: `export OPENAI_API_KEY=sk-...`

---

## Крок 2 — Встановити agentgateway як Helm deployment

Документація: https://agentgateway.dev/docs/kubernetes/main/about/gateway-api/

Встановити Gateway API CRDs (перевірити чи вже є в кластері):

```bash
kubectl get crd gateways.gateway.networking.k8s.io 2>/dev/null \
  && echo "вже встановлено" \
  || kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/standard-install.yaml
```

Встановити agentgateway (чарт автоматично створить GatewayClass `agentgateway`):

```bash
helm upgrade -i agentgateway-crds \
  oci://cr.agentgateway.dev/charts/agentgateway-crds \
  --version 1.1.0 \
  --namespace yuriip-ai-reliability-engineering-2

helm upgrade -i agentgateway \
  oci://cr.agentgateway.dev/charts/agentgateway \
  --version 1.1.0 \
  --namespace yuriip-ai-reliability-engineering-2 \
  --values helm/agentgateway-values.yaml
```

> Перевірити структуру values та зробити dry-run перед застосуванням:
> ```bash
> helm show values oci://cr.agentgateway.dev/charts/agentgateway --version 1.1.0
>
> helm upgrade -i agentgateway \
>   oci://cr.agentgateway.dev/charts/agentgateway \
>   --version 1.1.0 \
>   --namespace yuriip-ai-reliability-engineering-2 \
>   --values helm/agentgateway-values.yaml \
>   --dry-run
> ```

---

## Крок 3 — Налаштувати маршрут моделі через agentgateway (Gateway API)

Застосувати `AgentgatewayBackend` CRD (визначає OpenAI як upstream з авторизацією через Secret):

```bash
kubectl apply -f k8s/agentgateway-backend.yaml
```

Застосувати Gateway та HTTPRoute (`k8s/gateway.yaml` використовує GatewayClass `agentgateway`, створений чартом):

```bash
kubectl apply -f k8s/gateway.yaml
kubectl apply -f k8s/model-httproute.yaml
```

Перевірити що маршрут прийнятий:

```bash
kubectl get gateway -n yuriip-ai-reliability-engineering-2
kubectl get httproute -n yuriip-ai-reliability-engineering-2
kubectl get agentgatewaybackend -n yuriip-ai-reliability-engineering-2
```

Отримати зовнішню адресу Gateway (controller створює Service `agentgateway-proxy` з AWS LoadBalancer):

```bash
export INGRESS_GW_ADDRESS=$(kubectl get svc agentgateway-proxy \
  -n yuriip-ai-reliability-engineering-2 \
  -o jsonpath="{.status.loadBalancer.ingress[0]['hostname','ip']}")

echo $INGRESS_GW_ADDRESS
```

Протестувати LLM маршрут через Gateway:

```bash
curl http://$INGRESS_GW_ADDRESS/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Hello!"}]}'
```

---

## Крок 4 — Розгорнути kagent

Документація: https://kagent.dev/docs/kagent/getting-started/quickstart

```bash
helm upgrade -i kagent-crds \
  oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
  --version 0.9.2 \
  --namespace yuriip-ai-reliability-engineering-2

helm upgrade -i kagent \
  oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --version 0.9.2 \
  --namespace yuriip-ai-reliability-engineering-2 \
  --values helm/kagent-values.yaml \
  --values helm/kagent-values-cluster.yaml
```

> `helm/kagent-values-cluster.yaml` — cluster-specific overrides (tolerations, storageClass, вимкнені агенти).
> Файл у `.gitignore`. Шаблон: `helm/kagent-values-cluster.yaml` (не комітити).

> Перевірити структуру values та зробити dry-run перед застосуванням:
> ```bash
> helm show values oci://ghcr.io/kagent-dev/kagent/helm/kagent --version 0.9.2
>
> helm upgrade -i kagent \
>   oci://ghcr.io/kagent-dev/kagent/helm/kagent \
>   --version 0.9.2 \
>   --namespace yuriip-ai-reliability-engineering-2 \
>   --values helm/kagent-values.yaml \
>   --values helm/kagent-values-cluster.yaml \
>   --dry-run
> ```

> **Примітка (sandbox-apps):** після install запустити cluster-specific post-install скрипт
> (не в git): `bash cluster-sandbox-post-install.sh`

---

## Крок 5 — Перевірити роботу вбудованого агента

Перевірити що всі поди запущені:

```bash
kubectl get pods -n yuriip-ai-reliability-engineering-2
```

Відкрити UI agentgateway для ознайомлення з Backends і Policy (admin-порт 15000 доступний через port-forward):

```bash
kubectl port-forward deployment/agentgateway-proxy 15000:15000 \
  -n yuriip-ai-reliability-engineering-2
```

Відкрити http://localhost:15000/ui/

Відкрити UI kagent та запустити вбудованого агента (наприклад, Kubernetes assistant):

```bash
kubectl port-forward svc/kagent-ui 8080:8080 \
  -n yuriip-ai-reliability-engineering-2
```

Відкрити http://localhost:8080

Переглянути доступних агентів:

```bash
kubectl get agents.kagent.dev -n yuriip-ai-reliability-engineering-2
```

---

## Видалення ресурсів

```bash
helm uninstall kagent -n yuriip-ai-reliability-engineering-2
helm uninstall kagent-crds -n yuriip-ai-reliability-engineering-2
kubectl delete -f k8s/model-httproute.yaml
kubectl delete -f k8s/gateway.yaml
kubectl delete -f k8s/agentgateway-backend.yaml
helm uninstall agentgateway -n yuriip-ai-reliability-engineering-2
helm uninstall agentgateway-crds -n yuriip-ai-reliability-engineering-2
kubectl delete namespace yuriip-ai-reliability-engineering-2
```

> Не видаляти Gateway API CRDs якщо їх використовують інші команди в кластері.

---

## Структура файлів

```
lab1-eks/
├── k8s/
│   ├── namespace.yaml              # Namespace
│   ├── agentgateway-backend.yaml   # AgentgatewayBackend CRD — OpenAI upstream + auth
│   ├── gateway.yaml                # Gateway "agentgateway-proxy" (GatewayClass "agentgateway" з чарту)
│   └── model-httproute.yaml        # HTTPRoute → AgentgatewayBackend (group: agentgateway.dev)
├── helm/
│   ├── agentgateway-values.yaml        # Helm values для agentgateway
│   ├── kagent-values.yaml              # Helm values для kagent (в git)
│   └── kagent-values-cluster.yaml      # Cluster-specific overrides — tolerations, storageClass (.gitignore)
└── cluster-sandbox-post-install.sh     # Post-install патч для postgres (.gitignore)
```
