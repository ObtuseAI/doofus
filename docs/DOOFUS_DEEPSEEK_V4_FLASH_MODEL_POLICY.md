# DeepSeek V4 Flash Model Policy

- Provider: OpenRouter (default)
- Model: `deepseek/deepseek-v4-flash`
- Credentials: `OPENROUTER_API_KEY` env only — **never hardcoded**
- Local setup: copy `.env.example` → `.env` (gitignored) in workspace root
- dry_run if credentials absent
- Budget: `DOOFUS_MAX_DAILY_COST_USD`, `DOOFUS_MAX_MODEL_CALLS_PER_HOUR`
