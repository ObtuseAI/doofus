# Doofus Desktop API Secret Loading

Operator Desktop sources checked (in order):

- `%USERPROFILE%\Desktop\doofusapi`
- `%USERPROFILE%\Desktop\doofusapi.txt`
- `%USERPROFILE%\OneDrive\Desktop\doofusapi.txt`

Secrets are never printed. Reports show `REDACTED` and safe metadata only
(`key_shape`, `secret_length_bucket`).

Run discovery from the workspace root:

```powershell
.\.venv_doofus\Scripts\python.exe -m doofus.model_router.desktop_secret_loader
```
