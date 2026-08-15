# Dashboard LLM architecture

This document records the provider and tool architecture as of August 14,
2026. The most important distinction is that Groq's API specification and this
application's Swagger document have different jobs.

## Groq API surface

Groq exposes an OpenAI-compatible API at `https://api.groq.com/openai/v1`.
The dashboard currently needs only `POST /chat/completions`, including its
messages, function tools, `tool_choice`, and `parallel_tool_calls` fields.
Groq also offers Responses, audio, models, batches, files, and fine-tuning APIs,
but they are outside this dashboard's current request path.

Primary references:

- [Groq API reference](https://console.groq.com/docs/api-reference)
- [Groq OpenAI compatibility](https://console.groq.com/docs/openai)
- [Groq local tool calling](https://console.groq.com/docs/tool-use/local-tool-calling)

Chat Completions remains the shared provider contract because both Groq and
local Ollama models support it, including function tools. Moving to the
Responses API would not improve the database security boundary and would make
the first multi-provider implementation less portable.

## Application Swagger/OpenAPI surface

FastAPI generates the application's `/openapi.json` (and renders it at
`/docs`). At startup, `build_tools_from_openapi` reads that document and keeps
only GET operations whose `operationId` is also present in
`APPROVED_CHAT_OPERATIONS`.

The resulting JSON schemas are sent to the selected model as function tools.
They are not Groq endpoints, and the model never calls FastAPI routes directly.
The server validates the chosen tool and arguments, then calls a trusted Python
executor with the current SQLAlchemy session.

```mermaid
flowchart LR
    Browser[Dashboard chat] --> Route[FastAPI chat route]
    OpenAPI[FastAPI OpenAPI schema] --> Allowlist[Read-only operation allowlist]
    Allowlist --> Tools[Function tool schemas]
    Route --> Provider[Groq or local provider]
    Tools --> Provider
    Provider --> Call[Requested tool call]
    Call --> Validate[Pydantic argument validation]
    Validate --> Executor[Trusted Python executor]
    Executor --> DB[(PostgreSQL)]
    DB --> Provider
    Provider --> Browser
```

## Security invariants

1. Only explicitly registered GET operations become model tools.
2. Tool argument models use `extra="forbid"` and field constraints.
3. Models receive neither SQL nor a database connection.
4. POST, PUT, and DELETE operations never enter the tool list.
5. Database results are treated as untrusted data when generating an answer.
6. The server owns provider keys; the browser never receives them.

## Provider boundary

`ChatProvider` describes a name, model, base URL, key, and timeout.
`run_provider_tool_chat` owns the common two-request sequence:

1. require a validated read tool call;
2. execute the approved operation on the server;
3. send the structured result back without tools for a final explanation.

This boundary keeps the tool loop identical for Groq and OpenAI-compatible
local servers. Provider selection belongs to the LangGraph workflow described
in the next roadmap item, not to the database or tool executors.

## LangGraph routing

`llm_router.py` compiles a three-branch graph once:

```mermaid
flowchart LR
    Request --> Classify
    Classify -->|lookup| Lookup
    Classify -->|analysis| Analysis
    Classify -->|visualization| Visualization
    Lookup --> Provider
    Analysis --> Provider
    Visualization --> Provider
```

The classifier is deterministic rather than model-based. This avoids spending
tokens on routing, prevents a routing model from inventing destinations, and
makes every branch unit-testable. LangGraph still provides an explicit workflow
boundary where retries, persistence, streaming, or human review can be added
later.

The default Groq model policy is:

| Intent | Model | Reason |
| --- | --- | --- |
| Lookup | local `qwen3:8b`, then `openai/gpt-oss-20b` | Private, fast tool selection with hosted fallback |
| Analysis | `openai/gpt-oss-120b` | Stronger comparisons and coaching |
| Visualization | `openai/gpt-oss-120b` | Explains validated data while the browser renders the chart |

All model names and provider preferences are environment overrides.

## Local model support and failover

Ollama exposes an OpenAI-compatible `POST /v1/chat/completions` endpoint with
function-tool support. The application therefore reuses the same
`ChatProvider` and validated tool loop for local inference; there is no second
database integration or weaker local security path.

References:

- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling)
- [LangGraph workflows and routing](https://docs.langchain.com/oss/python/langgraph/workflows-agents)

Local inference is opt-in with `LOCAL_LLM_ENABLED=true`. The default preference
routes simple lookups to local `qwen3:8b`, while analysis and visualization
explanations use their Groq models. Every route can be changed in `.env`.

The visualization route does not ask either model to draw. FastAPI derives a
bounded `bar` or `line` chart specification from validated PostgreSQL query
results, and the browser renders that data with Chart.js. The routed model only
explains the important pattern in prose.

Provider execution follows a bounded availability policy:

1. run the provider selected by LangGraph;
2. if it fails, try the other configured provider once;
3. if both fail (or neither is configured), use deterministic SQLAlchemy
   answers for the supported dashboard questions.

The repository does not install or launch Ollama automatically. Local model
weights and compute remain an explicit operator choice, and the README includes
the pull, serve, and `/v1/models` verification commands.
