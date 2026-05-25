# Lab 7 — Vin's Questions: AI Infrastructure Research

Дослідження та оцінка власного сетапу AI-інфраструктури на базі курсу AI Reliability Engineering 2.0.

**Стек:** kagent · kgateway (agentgateway) · A2A protocol · MCP · Qdrant · abox (KinD) · Flux GitOps

---

## 1. How could we handle 'agent got stuck' scenarios?

У нашому сетапі є кілька рівнів захисту від "застрягання":

**Kubernetes-рівень** (для kagent Agents):
- Liveness probe на Pod перезапускає зависший контейнер автоматично
- `terminationGracePeriodSeconds` обмежує час shutdown

**AutoGen runtime (kagent):**
- `max_consecutive_auto_reply` — максимальна кількість авто-відповідей перед зупинкою
- `max_turns` — hard limit на кількість ходів у multi-agent розмові

**A2A protocol layer (наші FastAPI агенти):**
- HTTP client timeout у `orchestrator-agent` при виклику `time-agent`
- Якщо `time-agent` не відповідає за N секунд — `orchestrator` повертає помилку клієнту

**Приклад фіксу для orchestrator-agent:**
```python
import httpx

async with httpx.AsyncClient(timeout=10.0) as client:  # 10s timeout
    response = await client.post(TIME_AGENT_URL, json=payload)
```

**Рекомендація для production:** додати dead-letter queue або retry-with-backoff на рівні оркестратора, та alert у Prometheus при аномальній тривалості inference.

---

## 2. Any automatic timeout/circuit breaker patterns coming out from this framework?

**kgateway (agentgateway)** підтримує нативні timeout та retry через Gateway API:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
spec:
  rules:
  - timeouts:
      request: 30s         # загальний timeout запиту
      backendRequest: 15s  # timeout до конкретного backend
    backendRefs:
    - name: openai-backend
      port: 443
```

**Circuit breaker** у kgateway реалізується через `BackendLBPolicy` з passive health checking:
- Eject нездорових backends після N consecutive failures
- Cooldown period перед повторним включенням

**kagent сам по собі** не має вбудованого circuit breaker — він делегує це Kubernetes і kgateway. Для повноцінного circuit breaker на рівні service mesh рекомендується Istio (з `DestinationRule` + `outlierDetection`), або реалізація на рівні коду агента (бібліотека `tenacity` для Python retry/circuit breaker).

---

## 3. How does kgateway handle model failover?

kgateway визначає кілька `LLMBackend` ресурсів і маршрутизує через `AIGatewayRoute`:

```yaml
apiVersion: aigateway.envoyproxy.io/v1alpha1
kind: AIGatewayRoute
spec:
  rules:
  - matches:
    - headers:
      - name: x-model-preference
        value: openai
    backendRefs:
    - name: openai-backend
      weight: 100
  - backendRefs:                    # fallback rule
    - name: openai-backend
      weight: 80
    - name: claude-backend          # 20% або failover
      weight: 20
```

**Як відбувається failover:**
1. kgateway (Envoy under the hood) відстежує health кожного `LLMBackend`
2. При HTTP 5xx або timeout — backend тимчасово виключається з ротації
3. Трафік автоматично перенаправляється на наступний backend за пріоритетом/вагою
4. Після cooldown backend знову включається (passive health check)

---

## 4. Can we automatically switch from OpenAI to Claude to local model?

Так, це нативний use case для kgateway. Конфігурація трьох провайдерів:

```yaml
# LLMBackend #1 — OpenAI (primary)
apiVersion: aigateway.envoyproxy.io/v1alpha1
kind: LLMBackend
metadata:
  name: openai-backend
spec:
  schema:
    name: OpenAI
  backendRef:
    name: openai-service
---
# LLMBackend #2 — Anthropic Claude
apiVersion: aigateway.envoyproxy.io/v1alpha1
kind: LLMBackend
metadata:
  name: claude-backend
spec:
  schema:
    name: OpenAI           # Claude via OpenAI-compatible API
  backendRef:
    name: claude-service
---
# LLMBackend #3 — local vLLM
apiVersion: aigateway.envoyproxy.io/v1alpha1
kind: LLMBackend
metadata:
  name: vllm-backend
spec:
  schema:
    name: OpenAI           # vLLM also exposes OpenAI-compatible API
  backendRef:
    name: vllm-service
```

**AIGatewayRoute** з priority-based failover: OpenAI → Claude → vLLM.

У **kagent** `modelConfig` вказує на конкретний `LLMBackend` через kgateway — змінюючи `default-model-config`, можна переключити всіх агентів одночасно.

---

## 5. Could we seamlessly handle the response formats from these providers?

**Так** — і це одна з ключових переваг kgateway.

Всі три провайдери нормалізуються до **OpenAI Chat Completions API формату**:

| Provider | Native format | kgateway обробляє |
|----------|--------------|-------------------|
| OpenAI | OpenAI format | прозоро |
| Claude (Anthropic) | Anthropic Messages API | конвертує → OpenAI |
| vLLM local | OpenAI-compatible | прозоро |
| AWS Bedrock | Bedrock format | конвертує → OpenAI |

kagent agents отримують уніфіковану відповідь незалежно від backend — переключення між провайдерами не потребує змін у коді агента.

**Застереження:** деякі Claude-специфічні можливості (extended thinking, vision з PDF) можуть не мати прямого маппінгу — для них потрібен нативний Anthropic SDK.

---

## 6. Can we version the agents built from kagent?

**Так**, через GitOps (Flux, як у Lab 2):

```
lab2-abox/
└── apps/
    └── time-agent/
        ├── v1/
        │   └── agent.yaml    # kagent Agent CRD v1
        └── v2/
            └── agent.yaml    # kagent Agent CRDs v2
```

**Механізм версіонування:**
1. Кожен `Agent` CRD — це Git commit → OCI artifact → Flux reconciles
2. Kubernetes labels: `app.kubernetes.io/version: "2.0.0"` на CRD metadata
3. Kustomize overlays для різних версій (`kustomization.yaml` з `namePrefix: v2-`)
4. Flux `Kustomization` з `suspend: true` для заморозки конкретної версії

**Важливо:** kagent CRD spec сам по собі не має `version` поля — версіонування відбувається через Git history та Kubernetes resource versioning (resourceVersion, generation).

---

## 7. Any blue/green or canary deployment patterns for agents?

Оскільки kagent `Agent` CRD створює Kubernetes `Deployment` під капотом, стандартні K8s патерни застосовні:

**Blue/Green:**
```yaml
# Blue (stable)
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: time-agent-blue
  labels:
    slot: blue
---
# Green (new version)
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: time-agent-green
  labels:
    slot: green
```
Перемикання: змінити selector у `Service` з `blue` → `green`.

**Canary через HTTPRoute:**
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
spec:
  rules:
  - backendRefs:
    - name: time-agent-stable
      weight: 90
    - name: time-agent-canary
      weight: 10        # 10% трафіку на нову версію
```

**Flagger** (з Flux) може автоматизувати canary: аналізує метрики (latency, error rate) і поступово збільшує вагу канарки або робить rollback.

---

## 8. What's the fastmcp-python framework mentioned?

[fastmcp](https://github.com/jlowin/fastmcp) — Python фреймворк для швидкого створення MCP серверів з декларативним API:

```python
from fastmcp import FastMCP

mcp = FastMCP("My Server")

@mcp.tool()
def get_current_time(timezone: str) -> str:
    """Returns current time for given timezone."""
    import pytz
    from datetime import datetime
    tz = pytz.timezone(timezone)
    return datetime.now(tz).isoformat()

@mcp.resource("config://settings")
def get_settings() -> dict:
    return {"version": "1.0"}

if __name__ == "__main__":
    mcp.run()  # auto-selects stdio or SSE transport
```

**Що дає fastmcp:**
- Автоматична генерація JSON Schema для tools з Python type hints
- Автоматичний вибір транспорту (stdio / SSE / streamable-http)
- Вбудована валідація аргументів (через Pydantic)
- З листопада 2024 — офіційна частина [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

---

## 9. Is it the easiest path to MCP?

**Так**, fastmcp — найнижчий поріг входу для Python MCP серверів на сьогодні.

| Підхід | Складність | Коли використовувати |
|--------|-----------|---------------------|
| **fastmcp** | низька | більшість Python MCP серверів |
| Raw MCP SDK (Python) | середня | потрібен повний контроль над протоколом |
| mcp-go | середня | Go сервіси |
| TypeScript MCP SDK | середня | Node.js екосистема |
| Ручна реалізація JSON-RPC | висока | специфічні транспорти |

У наших лабах ми використовували `mcp/time` (офіційний образ від Anthropic) — він теж побудований на fastmcp-підходах. Для кастомних MCP серверів у наступних проектах — fastmcp є першим вибором.

---

## 10. About finops: how much control I can have?

Контроль залежить від рівня стека:

**kgateway рівень** (найбільший контроль):
- `LLMRequestCost` — ліміт токенів per route:
```yaml
apiVersion: aigateway.envoyproxy.io/v1alpha1
kind: AIGatewayRoute
spec:
  llmRequestCosts:
  - inputCost: 0.03      # $/1K input tokens
    outputCost: 0.06     # $/1K output tokens
    budget: 100.0        # $ daily budget
```
- Rate limiting на рівні HTTPRoute (requests/хвилину)
- Prometheus metrics для відстеження витрат у Grafana

**kagent рівень:**
- `modelConfig` визначає який backend використовується — можна призначати дешевший model для конкретних агентів
- Немає вбудованого бюджет-трекера

**Агент-рівень (кастомний):**
- Middleware у FastAPI агентах для логування token usage з кожної відповіді
- Зберігання в Qdrant або time-series DB для аналізу

---

## 11. Token level / per agent level

**Token-level контроль:**
- kgateway: ліміти на `max_tokens` per route (HTTPRoute filter або `LLMPolicy`)
- AutoGen (kagent): `llm_config` з `max_tokens` параметром

**Per-agent level:**
- Кожен kagent `Agent` → окремий HTTPRoute → окремі ліміти
- Різні агенти можуть мати різні `modelConfig` → різні бекенди з різними ціновими моделями

```yaml
# Дорогий агент (orchestrator) — gpt-4o
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: orchestrator-agent
spec:
  declarative:
    modelConfig: gpt4o-model-config   # дорогий, але розумний

---
# Дешевий агент (time lookup) — gpt-4o-mini
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: time-agent
spec:
  declarative:
    modelConfig: gpt4o-mini-config    # дешевший для простих задач
```

---

## 12. Can I implement custom cost controls?

Так. Три підходи від простого до складного:

**1. kgateway LLMPolicy** (без коду):
```yaml
apiVersion: aigateway.envoyproxy.io/v1alpha1
kind: LLMPolicy
metadata:
  name: cost-control
spec:
  targetRef:
    kind: HTTPRoute
    name: agent-route
  tokenRateLimit:
    requestsPerUnit: 1000    # tokens/minute
    unit: Minute
```

**2. FastAPI middleware** (у наших A2A агентах):
```python
@app.middleware("http")
async def track_tokens(request: Request, call_next):
    response = await call_next(request)
    # parse response body, extract usage.total_tokens
    # store to Prometheus counter or Qdrant
    return response
```

**3. Prometheus + Grafana alerting:**
- Метрика `ai_tokens_used_total{agent="orchestrator"}` 
- Alert при перевищенні бюджету → webhook → автоматичне `kubectl patch` для зміни rate limit

---

## 13. Per-agent budgets or depth of Token limits

**Depth limit** (кількість ходів у ланцюжку):

AutoGen (kagent runtime) підтримує:
```python
# У kagent Agent CRD через systemMessage або кастомний runtime config:
max_consecutive_auto_reply = 5    # зупинити після 5 авто-відповідей
max_turns = 10                    # або після 10 ходів загалом
```

**Per-agent budget** (кумулятивний):
Поки не реалізовано нативно у kagent. Підходи:
1. **kgateway per-route rate limit** — найпростіше, але per-request, не кумулятивно
2. **External budget tracker** — Redis/Qdrant зберігає `{agent_name: tokens_used_today}`, агент перевіряє перед кожним LLM call
3. **Kubernetes ResourceQuota** — не для токенів, але обмежує CPU/Memory для Pod агента

**Roadmap:** kagent та kgateway активно розвиваються — per-agent token budgets очікуються у майбутніх релізах.

---

## 14. vLLM suitable for agents with many back-and-forth tool calls, or is it better for single shot inference?

**vLLM добре підходить для обох**, але з нюансами:

**Single-shot inference** — де vLLM максимально ефективний:
- Continuous batching: 100+ паралельних запитів в одному GPU batch
- PagedAttention: ефективне використання GPU пам'яті
- High throughput > low latency priority

**Agentic workloads (багато tool calls)** — vLLM також підходить, з умовами:
- **Prefix caching** (`--enable-prefix-caching`): system prompt кешується між turns → значна економія часу для агентів з довгим system prompt
- **Speculative decoding**: зменшує latency для коротких відповідей (tool call JSON)
- **KV cache reuse**: між запитами від одного агента — ефективно якщо контекст не змінюється

**Проблема** для довгих agentic chains: KV cache фрагментується при кожному новому tool result → cache miss зростає. Тут допомагає llm-d (питання 15).

**Висновок:** vLLM + prefix caching = хороший вибір для агентів з повторюваними system prompts. Для максимальної ефективності agentic chains — поєднувати з llm-d.

---

## 15. llm-d's scheduler — helps when agents make 15 LLM calls?

**Так**, і це один з ключових use cases для llm-d.

**Що таке llm-d:**
[llm-d](https://github.com/llm-d/llm-d) — Kubernetes-native distributed inference scheduler від Red Hat/IBM. Реалізує **disaggregated prefill/decode** та **KV-cache aware routing**.

**Як допомагає при 15 LLM calls:**

```
Agent call #1:  System prompt (2000 tokens) + message → prefill всього → decode
Agent call #2:  Same system prompt → llm-d routes to node with warm KV cache!
Agent call #3:  Same context prefix → cache HIT → skip prefill → тільки decode
...
Agent call #15: Majority of prefill from cache → ~3-5x faster than cold
```

**Ключові можливості llm-d для агентів:**
1. **KV Cache Router**: відстежує який inference node має який KV cache → routing на "теплий" вузол
2. **Disaggregated prefill**: prefill виконується на окремих вузлах (CPU-heavy), decode — на GPU → паралелізм
3. **Prefix-aware scheduling**: агентські ланцюжки з спільним prefix роутяться на той самий pod

**Порівняння:**

| Сценарій | без llm-d | з llm-d |
|---------|-----------|---------|
| 15 calls, same system prompt | 15x full prefill | 1x prefill + 14x cache hit |
| Latency per call | ~2-3s | ~0.3-0.5s (cached) |
| GPU utilization | низька (sequential) | висока (batched prefill) |

**У нашому abox сетапі:** llm-d можна розгорнути поруч з vLLM як scheduler layer — агенти продовжують звертатись до OpenAI-compatible endpoint, але llm-d оптимізує routing між GPU вузлами.

---

## Підсумок

| # | Питання | Відповідь у нашому сетапі |
|---|---------|--------------------------|
| 1 | Agent got stuck | K8s liveness probe + AutoGen max_turns + HTTP timeout |
| 2 | Timeout/circuit breaker | kgateway HTTPRoute timeouts + passive health check |
| 3 | Model failover | kgateway AIGatewayRoute з weighted/priority backends |
| 4 | Auto-switch OpenAI→Claude→local | kgateway LLMBackend failover chain |
| 5 | Response format normalization | kgateway конвертує все до OpenAI format |
| 6 | Agent versioning | GitOps (Flux) + Kubernetes labels/Kustomize |
| 7 | Blue/green / canary | K8s Deployment patterns + HTTPRoute weights + Flagger |
| 8 | fastmcp-python | Декоратор-based MCP framework, частина офіційного MCP SDK |
| 9 | Easiest path to MCP | Так, fastmcp — найнижчий поріг для Python |
| 10 | FinOps control | kgateway LLMPolicy + Prometheus metrics |
| 11 | Token/per-agent level | kgateway per-route + різні modelConfig per agent |
| 12 | Custom cost controls | kgateway LLMPolicy або FastAPI middleware |
| 13 | Per-agent budgets | AutoGen max_turns + external budget tracker |
| 14 | vLLM for agents | Підходить з prefix caching; оптимально з llm-d |
| 15 | llm-d scheduler | KV-cache aware routing → 3-5x faster agentic chains |
