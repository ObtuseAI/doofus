# Doofus Provider Router

Provider selection by key shape:

- `openrouter_like` → OpenRouter DeepSeek V4 Flash lane
- `openai_like` → OpenAI-compatible lane (`DOOFUS_OPENAI_MODEL`, default `gpt-4o-mini`)
- unknown → dry_run

`live_provider_ready` and `deepseek_openrouter_ready` are distinct flags.
