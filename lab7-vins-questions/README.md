# Lab 7 — Vin's Questions: AI Infrastructure Research

**Stack:** kagent · kgateway / agentgateway · A2A protocol · MCP · Qdrant · abox (KinD) · Flux GitOps

> All claims below are verified against official documentation:
> [kagent.dev/docs](https://kagent.dev/docs), [kgateway.dev/docs](https://kgateway.dev/docs),
> [google.github.io/adk-docs](https://google.github.io/adk-docs), [docs.vllm.ai](https://docs.vllm.ai),
> [github.com/llm-d/llm-d](https://github.com/llm-d/llm-d), [github.com/jlowin/fastmcp](https://github.com/jlowin/fastmcp).

---

## 1. How could we handle 'agent got stuck' scenarios?

Our setup has multiple protection layers against stuck agents:

**Kubernetes level (kagent Agents):**
- Liveness probe automatically restarts a hanging Pod.
- `terminationGracePeriodSeconds` bounds the shutdown time.

**kagent engine runtime:**
Since v0.6, kagent supports two runtimes selected via the `runtime` field in the Agent spec:
- **Python ADK** (default) — built on top of [Google ADK](https://google.github.io/adk-docs/), supports CrewAI / LangGraph / OpenAI integrations.
- **Go ADK** — native Go implementation with faster startup (~2 s vs ~15 s) and lower resource consumption.

Both runtimes provide `max_llm_calls` in `RunConfig` (default **500**), which caps the total number of LLM invocations per invocation context and is the primary guard against runaway agent loops. For deterministic workflow loops, the `LoopAgent` workflow type has a separate `MaxIterations` field.

**A2A protocol layer (our FastAPI agents):**
- HTTP client timeout in `orchestrator-agent` when calling `time-agent`.
- If `time-agent` does not respond within N seconds — orchestrator returns an error to the caller.

**Production recommendation:** add a dead-letter queue or retry-with-backoff at the orchestrator level, and a Prometheus alert on abnormal inference duration.

---

## 2. Any automatic timeout/circuit breaker patterns coming out from this framework?

**kgateway** has native timeout and retry support via the standard Gateway API. An `HTTPRoute` rule supports two timeout fields:
- `timeouts.request` — overall request timeout (max duration for the gateway to respond to the client).
- `timeouts.backendRequest` — per-backend attempt timeout. Must be ≤ `request`.

**Circuit breaker** in kgateway is implemented via `BackendConfigPolicy`. Two related mechanisms exist:

- **Outlier detection** — passive health checking. Configurable fields include `consecutive5xx` (eject after N consecutive 5xx), `interval` (analysis interval), `baseEjectionTime` (how long the host stays ejected), and `maxEjectionPercent` (cap on the percentage of hosts that can be ejected simultaneously).
- **Circuit breakers** (added to `BackendConfigPolicy` per kgateway release notes) — enforces connection / request limits per backend to prevent cascading failures.

**kagent itself** has no built-in circuit breaker — it delegates resilience to Kubernetes and the gateway. For a full circuit breaker at the service mesh level, Istio (`DestinationRule` + `outlierDetection`) is the typical complement. For application-level retries, the Python `tenacity` library works inside FastAPI agents.

---

## 3. How does kgateway handle model failover?

kgateway models **AI failover inside a single Backend resource**, not via weighted HTTPRoute backends.

You define a `Backend` with `spec.type: AI` (Envoy data plane) or an `AgentgatewayBackend` (agentgateway data plane). Inside the AI spec there is a list of **priority groups**, each containing one or more LLM providers. The HTTPRoute simply references that single Backend.

How it behaves at runtime:

1. Requests are first load-balanced across all providers inside the **highest-priority group**.
2. If every provider in that group becomes unhealthy (5xx, rate-limit, timeout), traffic falls back to the **next priority group**.
3. Provider health is tracked passively (similar to outlier detection); when a provider recovers it is re-included in rotation.

A typical cost-optimised pattern is: priority group 1 — cheap models (e.g. `gpt-3.5-turbo`, `claude-3-5-haiku`); priority group 2 — premium fallback (e.g. `gpt-4.1`, `claude-opus`). Load balancing happens **within** a group; failover happens **between** groups.

> ⚠️ In kgateway **v2.2.0** the AI Gateway and Inference Extension were removed from the Envoy data plane — AI backends are now supported only via the **agentgateway** data plane (`apiVersion: agentgateway.dev/v1alpha1`, `kind: AgentgatewayBackend`).

---

## 4. Can we automatically switch from OpenAI to Claude to local model?

Yes — using the same `priorityGroups` mechanism described in Q3, plus an OpenAI-compatible local backend.

Each provider (OpenAI, Anthropic, a local vLLM endpoint, AWS Bedrock, etc.) is declared inside one of the priority groups of a **single AI Backend**. For a local model served by vLLM, you use the `openai` provider type with a `customHost` pointing at the in-cluster vLLM service — vLLM exposes an OpenAI-compatible API, so no special adapter is required.

Priority chain example for our setup: OpenAI → Anthropic → local vLLM. The gateway promotes the next group automatically when the current one is unhealthy.

In **kagent**, agents reference a `ModelConfig` that targets the kgateway endpoint. Switching the cluster-wide default behaviour requires changing one ModelConfig (e.g. `default-model-config`) instead of editing every agent.

---

## 5. Could we seamlessly handle the response formats from these providers?

**Yes** — and this is one of the main reasons to put kgateway in front of multiple LLM providers.

All supported providers are normalized to the **OpenAI Chat Completions API format**:

| Provider          | Native format            | kgateway behavior            |
|-------------------|--------------------------|------------------------------|
| OpenAI            | OpenAI                   | transparent pass-through     |
| Claude (Anthropic)| Anthropic Messages API   | converts → OpenAI            |
| vLLM (local)      | OpenAI-compatible        | transparent pass-through     |
| AWS Bedrock       | Bedrock                  | converts → OpenAI            |
| Gemini            | Gemini                   | converts → OpenAI            |

kagent agents receive a unified response regardless of which backend served the request — switching between providers requires no changes in agent code.

**Caveat:** provider-specific capabilities (Anthropic extended thinking, Bedrock prompt caching, Gemini search grounding) do not have a direct mapping into the OpenAI schema. For those features the native SDK or a provider-specific passthrough route is required.

---

## 6. Can we version the agents built from kagent?

**Yes**, via GitOps (Flux, as in Lab 2). The mechanism is the standard Kubernetes one — kagent does **not** introduce a custom `version` field in the Agent CRD; versioning is achieved through Git history, Kustomize overlays, and labels.

Practical pattern:

1. Each `Agent` CRD change is a Git commit → OCI artifact → Flux reconciles into the cluster.
2. Use Kubernetes labels such as `app.kubernetes.io/version` on the Agent metadata to make versions queryable.
3. Use Kustomize overlays for different environments / versions (`namePrefix`, patches).
4. Use Flux `Kustomization` with `suspend: true` to freeze a specific version on a specific cluster.
5. Rely on the built-in `metadata.generation` and `metadata.resourceVersion` for in-cluster tracking.

For BYO agents (where the agent is shipped as a container image rather than declaratively configured), versioning is just the container image tag — same as any other Kubernetes workload.

---

## 7. Any blue/green or canary deployment patterns for agents?

Since a kagent `Agent` CRD ultimately runs as a Kubernetes Pod, **standard K8s deployment patterns apply**.

**Blue/Green:**
Define two Agent resources (e.g. `time-agent-blue` and `time-agent-green`) with distinguishing labels. Switch live traffic by updating the `Service` selector from `slot: blue` to `slot: green`. Rollback is one selector change.

**Canary via HTTPRoute:**
A standard Gateway API `HTTPRoute` can split traffic between two backend Services using `backendRefs[].weight` — for example, 90% to the stable agent service and 10% to the canary. This is purely Gateway API and is not kagent-specific.

**Progressive delivery with Flagger** (works with Flux):
[Flagger](https://fluxcd.io/flagger/) automates the canary lifecycle — it watches a target Deployment, gradually shifts traffic, analyses metrics (success rate, latency) against a defined SLO, and either promotes the new version or rolls back. Flagger supports both blue/green and canary modes across Istio, NGINX, Gateway API, and other meshes/ingress controllers.

---

## 8. What's the fastmcp-python framework mentioned?

[fastmcp](https://github.com/jlowin/fastmcp) — a Python framework for building MCP servers and clients with a decorator-based API.

**What fastmcp provides:**
- Automatic JSON Schema generation for tools from Python type hints.
- Pluggable transports (stdio / SSE / streamable-HTTP) selected automatically from the connection string.
- Built-in argument validation via Pydantic.
- High-level primitives for Tools, Resources, Prompts, and (in 3.0) Apps with interactive UIs.

**Important history detail:** FastMCP **1.0** was contributed to the official MCP Python SDK in 2024 and is available there as `mcp.server.fastmcp`. **FastMCP 2.0 and 3.0** are a separate, actively-developed standalone project (originally `jlowin/fastmcp`, now maintained by PrefectHQ) that adds a client library, server proxying/composition, OpenAPI/FastAPI integration, and many other features beyond the SDK baseline. For new servers today, the standalone package is the recommended path.

---

## 9. Is it the easiest path to MCP?

**Yes**, fastmcp has the lowest entry barrier for Python MCP servers today. According to the project README, some version of fastmcp powers ~70% of MCP servers across all languages.

| Approach                          | Complexity | When to use                                  |
|-----------------------------------|------------|----------------------------------------------|
| **fastmcp**                       | low        | most Python MCP servers                      |
| Raw MCP Python SDK                | medium     | when you need full control over the protocol |
| mcp-go                            | medium     | Go services                                  |
| TypeScript MCP SDK                | medium     | Node.js ecosystem                            |
| Manual JSON-RPC implementation    | high       | custom transports                            |

In our labs we used the official `mcp/time` image. For custom MCP servers in Python — fastmcp is the first choice.

---

## 10. About FinOps: how much control can I have?

Control depends on the stack layer. The picture has changed recently because **agentgateway now has native token-based rate limiting**, which fills the historical gap.

**Gateway level (kgateway / agentgateway):**
- **Request-based** local rate limiting via `TrafficPolicy.spec.rateLimit.local` (token bucket on request count per route).
- **Token-based** local rate limiting (counts LLM input/output tokens) via the same `TrafficPolicy` mechanism — available for agentgateway-class routes from **v2.1.0** (tracked in kgateway issue #11844, now closed).
- **Global** rate limiting via an external rate-limit service (Envoy ratelimit protocol).
- Prometheus metrics exported by the proxy — request counts, latency, and per-provider token usage in Grafana.

**kagent level:**
- `ModelConfig` selects which backend / model an agent uses — cheap models can be pinned to specific agents.
- ADK `RunConfig.max_llm_calls` caps the number of LLM invocations per session (per-invocation cost ceiling).
- No built-in cumulative budget tracker on the kagent side.

**Agent application level (custom):**
- FastAPI middleware to log `usage.total_tokens` from each response into Prometheus or a time-series store.
- External budget enforcement layer (e.g. Redis-backed) called before each LLM request.

---

## 11. Token level / per-agent level

**Token level:**
- agentgateway TrafficPolicy: native token-counting local rate limit (from v2.1.0) — independent of request count, useful because LLM costs are token-driven, not request-driven.
- ADK `ModelConfig` / `GenerateContentConfig.max_output_tokens` caps response length per call.
- kagent `ModelConfig.maxTokens` is the declarative way to set the per-request output cap for all agents using that config.

**Per-agent level:**
- Each kagent `Agent` is reachable via a distinct HTTPRoute → distinct TrafficPolicy → independent token / request limits per agent.
- Different agents can reference different `ModelConfig` resources, pointing at different providers with different pricing — e.g. an expensive orchestrator on a flagship model and cheap utility agents on a small model.

---

## 12. Can I implement custom cost controls?

Yes. Three approaches, from simplest to most flexible:

1. **kgateway / agentgateway TrafficPolicy** — request-rate and token-rate limiting with no code changes. Attach the policy to an HTTPRoute and define a token-bucket per agent route.
2. **FastAPI middleware** in the A2A agents — parse each LLM response, extract `usage.total_tokens`, push to a Prometheus counter labelled by agent name. Combine with Alertmanager for budget breach alerts.
3. **Prometheus + Grafana + automation** — alert on a `tokens_used_total{agent="…"}` threshold, route the alert to a webhook that tightens the TrafficPolicy rate limit or scales the agent down.

---

## 13. Per-agent budgets or depth of token limits

**Depth limit (number of LLM calls in a chain):**
This is what `RunConfig.max_llm_calls` controls in the ADK runtime — it caps the total LLM invocations per invocation context (default 500). For deterministic looping workflows, `LoopAgent.MaxIterations` is the equivalent. Both are configured in the agent application code; there is no corresponding field on the kagent Agent CRD today.

**Per-agent cumulative budget:**
Not natively implemented in kagent. Practical options:
1. **agentgateway TrafficPolicy with token-based local rate limit** — simplest, but enforced per time window rather than as a true cumulative spend cap.
2. **External budget tracker** — Redis / a TS DB keeps `{agent_name: tokens_used_today}`, agent middleware checks before each LLM call.
3. **Kubernetes `ResourceQuota`** — does not cap tokens, but can cap CPU/memory for the agent Pod, which indirectly limits throughput.

**Roadmap note:** both kagent and kgateway/agentgateway are evolving quickly — true per-agent token budgets are a likely future addition.

---

## 14. Is vLLM suitable for agents with many back-and-forth tool calls, or is it better for single-shot inference?

**vLLM works well for both**, with some nuances for agentic workloads.

**Single-shot inference** — where vLLM is most efficient:
- Continuous batching: many parallel requests share a GPU batch.
- PagedAttention: efficient GPU memory usage.
- Optimised for high throughput.

**Agentic workloads (many tool calls)** — vLLM also handles this well, especially with:
- **Automatic Prefix Caching (APC)** — enabled via `enable_prefix_caching=True` on the engine (or `--enable-prefix-caching` on `vllm serve`). The KV cache of an already-processed prefix (system prompt, conversation history) is reused for new requests that share that prefix. Per vLLM docs, this delivers large wins for multi-round conversations and long-document workloads, where the shared prefix dominates and only the new suffix needs prefill.
- **Speculative decoding** — reduces latency for short responses such as tool-call JSON.
- **KV cache reuse** between same-prefix requests — effective when the agent's system prompt and tool definitions stay constant across turns.

**Limit for long agentic chains:** as the agent appends each tool result to the context, the prefix that future calls share with past calls shrinks, so cache hit rate degrades over very long sessions. This is exactly the gap llm-d is designed to close (Q15).

**Conclusion:** vLLM + prefix caching is a strong choice for agents with stable system prompts and many tool calls. For maximum efficiency across distributed inference at scale, combine vLLM with llm-d.

---

## 15. llm-d's scheduler — does it help when agents make 15 LLM calls?

**Yes**, and this is one of llm-d's headline use cases.

**What llm-d is:**
[llm-d](https://github.com/llm-d/llm-d) — a Kubernetes-native, high-performance distributed LLM inference framework built on vLLM, Kubernetes, and the Gateway API Inference Extension. It was originally launched by Red Hat (under the Red Hat / IBM umbrella) and is now a multi-vendor open-source project.

**How it helps with 15 LLM calls from one agent:**
- **KV-cache aware routing** — the scheduler tracks which decode worker holds which KV cache blocks and routes new requests to the worker that already has the matching prefix cached. For an agent with a 2000-token system prompt repeated across 15 calls, this turns 14 expensive prefills into cache hits.
- **Disaggregated prefill / decode** — prefill runs on compute-optimised nodes, decode on memory-bandwidth-optimised nodes, transferred via a KV connector (e.g. NIXL). This removes head-of-line blocking that vLLM monolithic deployments hit when long prefills delay running decodes.
- **Prefix-aware scheduling** — requests that share a long prefix are routed to the same pod, maximising the cache hit rate that vLLM's APC can exploit.
- **Hierarchical KV offloading** (v0.5+) — KV blocks evicted from GPU memory are kept on CPU or disk tiers instead of being thrown away.

**Why naive Kubernetes load balancing breaks this:** round-robin spreads related requests across pods, destroying cache locality and forcing repeated prefills. llm-d replaces that with an Envoy-based inference-aware scheduler (External Processing Pod) plugged into the Gateway API Inference Extension.

**Published numbers** (from llm-d and partners' benchmarks):
- ~3× lower TTFT and ~50% higher QPS vs round-robin baseline on prefix-heavy workloads.
- Up to ~70% higher throughput with prefill/decode disaggregation on large models.

**In our abox setup:** llm-d can be deployed alongside vLLM as the scheduling layer — agents continue to call the OpenAI-compatible endpoint, while llm-d transparently optimises routing across GPU nodes.