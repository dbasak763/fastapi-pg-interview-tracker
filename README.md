# Interview Tracker API

## Dashboard chat

The dashboard chat uses a deterministic LangGraph workflow to classify lookup,
analysis, and visualization requests. It can route to Groq, a local Ollama
model, or the built-in deterministic dashboard answers.

Install the application dependencies first:

```bash
python -m pip install -r requirements.txt
```

### Groq

1. Create a Groq API key at <https://console.groq.com/keys>.
2. Add these values to `.env` (never commit that file):

   ```dotenv
   GROQ_API_KEY=gsk_replace_with_your_key
   GROQ_MODEL=llama-3.1-8b-instant
   GROQ_BASE_URL=https://api.groq.com/openai/v1
   ```

Optional `GROQ_LOOKUP_MODEL`, `GROQ_ANALYSIS_MODEL`, and
`GROQ_VISUALIZATION_MODEL` variables override the model for each route.

### Local Ollama model

1. [Install Ollama](https://docs.ollama.com/quickstart) and pull the default
   tool-capable model:

   ```bash
   ollama pull qwen3:8b
   ```

2. Start Ollama if it is not already running:

   ```bash
   ollama serve
   ```

3. Confirm its OpenAI-compatible API can see the model:

   ```bash
   curl http://127.0.0.1:11434/v1/models
   ```

4. Enable it in `.env`:

   ```dotenv
   LOCAL_LLM_ENABLED=true
   LOCAL_LLM_BASE_URL=http://127.0.0.1:11434/v1
   LOCAL_LLM_API_KEY=ollama
   LOCAL_LLM_MODEL=qwen3:8b
   LLM_VISUALIZATION_PROVIDER=local
   ```

The local API key is required by the OpenAI-compatible client contract but is
ignored by Ollama. If the selected provider is unavailable, the workflow tries
the other configured provider once and then uses the deterministic fallback.

### Default routing policy

| Request type | Preferred provider/model | Why |
| --- | --- | --- |
| Simple lookups | Groq `llama-3.1-8b-instant` | Low-latency tool calls |
| Analysis and coaching | Groq `llama-3.3-70b-versatile` | Stronger comparisons |
| Visualization | Local `qwen3:8b` | Private, cost-free formatting |

Change `LLM_LOOKUP_PROVIDER`, `LLM_ANALYSIS_PROVIDER`, or
`LLM_VISUALIZATION_PROVIDER` to `groq` or `local` to override the defaults.

The server sends the selected topic's complete attempt records, aggregate
statistics for every topic, and the last 10 chat messages. The API key remains
server-side and is never sent to the browser.

## LLM roadmap

- [x] Understand and document the Groq API surface, including the Groq
      architecture and the current Swagger/OpenAPI-derived tool integration.
      See [LLM architecture](docs/llm-architecture.md).
- [x] Route lookup, analysis, and visualization requests through a deterministic
      LangGraph workflow. LangGraph is used without LangChain because the app
      already owns its prompts, tools, and validated execution loop.
- [x] Add an optional local Ollama model and route lookup, analysis, and
      visualization requests to configurable providers and models through
      LangGraph, with provider and deterministic fallbacks.
