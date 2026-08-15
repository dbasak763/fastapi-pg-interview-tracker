# Interview Tracker API

## Optional open-model dashboard chat

The dashboard chat uses Groq-hosted Llama 3.1 8B when `GROQ_API_KEY` is set.
Without a key, it automatically falls back to the built-in dashboard answers.

1. Create a Groq API key at <https://console.groq.com/keys>.
2. Add these values to `.env` (never commit that file):

   ```dotenv
   GROQ_API_KEY=gsk_replace_with_your_key
   GROQ_MODEL=llama-3.1-8b-instant
   GROQ_BASE_URL=https://api.groq.com/openai/v1
   ```

The server sends the selected topic's complete attempt records, aggregate
statistics for every topic, and the last 10 chat messages. The API key remains
server-side and is never sent to the browser.

## LLM roadmap

- [ ] Understand and document the Groq API surface, including the Groq
      architecture and the current Swagger/OpenAPI-derived tool integration.
- [ ] Evaluate LLM request routing with LangChain and LangGraph, including when
      a graph-based workflow is more useful than the current direct tool flow.
- [ ] Run a local LLM and evaluate a model router that can send different
      request types (for example, data lookup, analysis, and visualization) to
      different models, coordinated through LangChain or LangGraph.
