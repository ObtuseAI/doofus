# Doofus Secret and Environment Policy

- OPENROUTER_API_KEY must never be printed, committed, logged, or hashed into reports.
- Use user-level environment variable or gitignored `.env` loaded by `doofus_env_loader`.
- All outputs pass through `model_secret_redactor` and `secret_guard`.
