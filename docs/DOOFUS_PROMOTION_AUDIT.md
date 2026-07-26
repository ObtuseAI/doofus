# Doofus Promotion Audit

Audits promoted candidates for replay, regression, bloat, and safety.

```powershell
.\.venv_doofus\Scripts\python.exe -m doofus.reports.promotion_audit_report
```

Verdicts: `promotion_validated`, `promotion_weak`, `promotion_unreplayable`, etc.

No automatic rollback unless unsafe.
