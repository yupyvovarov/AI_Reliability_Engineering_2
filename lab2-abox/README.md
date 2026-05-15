# Lab 2 — Agentic Box (abox)

## Передумови

У налаштуваннях Codespaces задай секрет `OPENAI_API_KEY`:
`Settings → Secrets and variables → Codespaces → New repository secret`

---

## 1. Запуск Codespace

Відкрий репозиторій у GitHub Codespaces (**4-core / 16 GB**).
`devcontainer.json` автоматично ініціалізує submodule.

---

## 2. Встановлення Flux CLI

```bash
curl -s https://fluxcd.io/install.sh | FLUX_INSTALL_PATH=$HOME/.local/bin bash
```

---

## 3. Розгортання abox

```bash
cd lab2-abox/abox
make run
```

Перевірка:

```bash
kubectl get nodes
flux get all -A
```

---

## 4. Фікс OpenAI ключа

Flux не успадковує env-змінні shell, тому потрібно задати секрет вручну:

```bash
kubectl create secret generic kagent-openai \
  --from-literal=OPENAI_API_KEY=$OPENAI_API_KEY \
  -n kagent --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/kagent-controller -n kagent
```

---

## 5. Відкрити Kagent UI

```bash
kubectl port-forward svc/agentgateway-external 8080:80 -n agentgateway-system
```

Codespaces автоматично запропонує відкрити порт 8080 у браузері (вкладка **Ports**).

---

## 6. Beginner — kubectl apply

```bash
cd lab2-abox
kubectl apply -k k8s/
kubectl get mcpservers,agents -n kagent
```

Kagent UI → вибери агента `time-agent` → запитай:

```
What time is it now in Kyiv?
```

---

## 7. Advanced — GitOps через Flux OCI

```bash
cd lab2-abox

# Підключити другий OCI-репозиторій до Flux
make apply

# Збампити версію, затегувати і запушити → CI публікує OCI artifact
make push

# Слідкуй за reconciliation
flux get kustomizations -A --watch
```

---

## Корисні команди

```bash
# Логи kagent controller
kubectl logs -n kagent deploy/kagent-controller -f

# Форс-reconciliation
flux reconcile kustomization lab2-releases -n flux-system

# Знищити кластер
cd lab2-abox/abox && make down
```
