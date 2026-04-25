"""Tasks Celery. Implementação completa na Fase 3.

Tasks planejadas:
- sweep_active_watches: enfileira check_watch para todos os Watches ativos
- check_watch(watch_id): consulta BFF, grava snapshot, decide notify
- reprime_cookies: subprocess Playwright para renovar cookies
- notify(watch_id, snapshot_id): WhatsApp via Evolution API (Fase 4)
"""
from __future__ import annotations

# TODO Fase 3: ver docs/plan.md
