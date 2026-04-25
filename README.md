# Viatu

Monitor de preços de passagens LATAM em pontos LATAM Pass.

Consulta periodicamente o BFF do `latamairlines.com`, grava histórico em Postgres, e alerta no WhatsApp via Evolution API quando o preço cai abaixo de um limite.

## Quick start

```bash
# 1. Deps
uv sync
uv run playwright install chromium

# 2. Config
cp .env.example .env
# editar .env (DATABASE_URL, REDIS_URL, EVOLUTION_*)

# 3. Cookies do Akamai (uma vez, ou quando expirar)
uv run python -m app.primer

# 4. Subir API local (Fase 1)
uv run uvicorn app.main:app --reload

# 5. Testar busca on-demand
curl -X POST http://localhost:8000/search \
  -H 'Content-Type: application/json' \
  -d '{
    "origin": "FOR",
    "destination": "IGU",
    "departure": "2026-06-21",
    "adults": 1,
    "cabin": "Y"
  }'
```

## Estrutura

```
app/
├── config.py          # Settings (pydantic-settings)
├── schemas.py         # Pydantic: SearchRequest, FareOption, Watch*
├── cookie_store.py    # Persistência dos cookies Akamai
├── primer.py          # Playwright para gerar cookies
├── latam_client.py    # Cliente HTTP do BFF
├── main.py            # FastAPI
├── db.py              # SQLAlchemy (Fase 2)
├── models.py          # Watch, PriceSnapshot, Alert (Fase 2)
├── celery_app.py      # App Celery (Fase 3)
├── tasks.py           # check_watch, sweep, reprime, notify (Fase 3-4)
└── notifier.py        # WhatsApp (Fase 4)

docs/
├── plan.md            # Plano de implementação por fases
└── sample-response.json   # Resposta real do BFF (verdade de campo)

alembic/               # Migrations (Fase 2)
tests/                 # pytest
```

## Documentação

- **`CLAUDE.md`** — guia do projeto pro Claude Code (arquitetura, convenções, gotchas)
- **`docs/plan.md`** — plano de implementação em 5 fases, cada uma com prompt sugerido
- **`docs/sample-response.json`** — resposta real do BFF, base do parser

## Status atual

- ✅ Scaffold completo
- ✅ Fase 1 (cliente BFF + busca on-demand) — código no lugar, falta testar end-to-end
- ⏳ Fase 2 (persistência)
- ⏳ Fase 3 (Celery)
- ⏳ Fase 4 (WhatsApp)
- ⏳ Fase 5 (Deploy OCI)

Para continuar, abra o projeto no VS Code, inicie o Claude Code e siga `docs/plan.md`.
