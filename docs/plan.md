# Plano de Implementação — Viatu

5 fases. Cada uma é um prompt completo pro Claude Code, autocontida e testável. Roda em ordem.

---

## Fase 1 — Setup do projeto e cliente do BFF

**Objetivo**: ter o cliente HTTP funcional + cookie priming + uma busca on-demand via FastAPI funcionando localmente.

**Entregáveis**:
- `pyproject.toml` com deps (`fastapi`, `uvicorn[standard]`, `httpx[http2]`, `playwright`, `pydantic>=2`, `pydantic-settings`, `tenacity`)
- `app/config.py` com Settings via `pydantic-settings` lendo `.env`
- `app/schemas.py` com `SearchRequest`, `FareOption`, `SearchResponse`
- `app/cookie_store.py` (já no scaffold)
- `app/primer.py` (já no scaffold)
- `app/latam_client.py` com `LatamClient.search()` e `LatamClient.calendar()` (parser confirmado contra a resposta real)
- `app/main.py` com `POST /search` e `GET /calendar` e `GET /health`
- Teste manual: `curl POST /search` retorna JSON com tarifas em pontos

**Critério de aceite**:
- `uv run python -m app.primer` gera `.latam_cookies.json` com 10+ cookies (incluindo `_abck`, `bm_sv`, `bm_sz`).
- `uv run uvicorn app.main:app --reload` sobe sem erro.
- `curl -X POST localhost:8000/search -H 'Content-Type: application/json' -d '{"origin":"FOR","destination":"IGU","departure":"2026-06-21","adults":1,"cabin":"Y"}'` retorna lista ordenada por pontos com pelo menos 1 resultado da brand LIGHT.
- Em caso de 403, retorna 503 com mensagem clara pedindo re-priming.

**Riscos**:
- Headers `x-latam-*` podem ser obrigatórios em alguns ambientes — se der 403 mesmo com cookies, capturar do DevTools e adicionar em `BASE_HEADERS`.

**Prompt sugerido pro Claude Code**:
> Implemente a Fase 1 do plano em `docs/plan.md`. O scaffold já tem `cookie_store.py`, `primer.py`, e versões iniciais de `latam_client.py`/`main.py`/`schemas.py` que precisam ser completadas e testadas. Use o sample em `docs/sample-response.json` como verdade de campo para o parser. Confirme cada passo testando com `curl`.

---

## Fase 2 — Persistência (Watches + Snapshots)

**Objetivo**: tirar do papel o conceito de "watch" e começar a gravar histórico de preços.

**Entregáveis**:
- `app/db.py` com `engine`, `SessionLocal`, dependency `get_session` para FastAPI
- `app/models.py` com `Watch`, `PriceSnapshot`, `Alert` (ver shape em CLAUDE.md)
- `alembic.ini` + `alembic/env.py` configurado lendo `DATABASE_URL` das settings
- Primeira migration: `alembic revision --autogenerate -m "initial schema"`
- CRUD de watches em `app/main.py`:
  - `POST /watches` cria
  - `GET /watches` lista
  - `GET /watches/{id}` detalha + últimos N snapshots
  - `PATCH /watches/{id}` atualiza (active, max_points, etc)
  - `DELETE /watches/{id}` remove (soft? só active=False)
- `POST /watches/{id}/check` força uma execução síncrona e grava snapshot

**Schema de Watch (mínimo)**:
```
id, origin, destination, departure, return_date (nullable),
cabin (default Y), adults (default 1),
max_points (nullable), only_direct (default true),
interval_minutes (default 30), active (default true),
notify_phone (nullable, formato E.164),
created_at, updated_at
```

**Schema de PriceSnapshot**:
```
id, watch_id (FK, indexed),
flight_number, stops, departure_at, arrival_at, duration_minutes,
fare_brand, fare_basis, cabin,
points, taxes_brl,
captured_at (indexed, default now)
```

Index composto: `(watch_id, captured_at DESC)`.

**Critério de aceite**:
- `alembic upgrade head` cria as tabelas no Postgres local.
- `POST /watches` com body válido retorna 201 e grava no banco.
- `POST /watches/{id}/check` retorna o snapshot mais barato gravado e a quantidade de novos registros.
- Re-rodar o `/check` cria snapshots adicionais sem duplicar (snapshots são append-only por design).

**Riscos**:
- Cuidado com timezone: usar `DateTime(timezone=True)` e armazenar em UTC. Converter pra `America/Fortaleza` só na apresentação.

**Prompt sugerido**:
> Implemente Fase 2 do plano. Use SQLAlchemy 2.x com `Mapped`/`mapped_column`. Configure Alembic para autogenerate. Postgres roda em `localhost:5432` com `latam:latam@localhost/viatu`. Adicione fixture mínima em `tests/test_watches.py` com SQLite in-memory pra smoke test do CRUD.

---

## Fase 3 — Celery + agendamento

**Objetivo**: tirar a verificação manual e colocar pra rodar de tempos em tempos com tolerância a falhas.

**Entregáveis**:
- `app/celery_app.py` com app Celery, broker/backend Redis, beat schedule
- `app/tasks.py`:
  - `sweep_active_watches` — lista watches ativos, agenda `check_watch` com jitter
  - `check_watch(watch_id)` — chama LatamClient, grava snapshot, decide se notifica
  - `reprime_cookies` — `subprocess.run(["python", "-m", "app.primer"])`
  - `notify(watch_id, snapshot_id)` — placeholder por enquanto (só log)
- Configuração: `task_acks_late=True`, `worker_prefetch_multiplier=1`, `task_time_limit=120`, timezone `America/Fortaleza`
- Beat schedule: `sweep_active_watches` a cada 30min, `reprime_cookies` a cada 4h
- Ajuste no `LatamClient`: aceitar uma instância de session compartilhada (não criar/fechar a cada task)

**Critério de aceite**:
- `celery -A app.celery_app worker -l info` sobe sem erro
- `celery -A app.celery_app beat -l info` sobe sem erro
- Watches ativos geram snapshots a cada ~30min sem intervenção
- Em 403 sintetizado (apaga cookies manualmente): task falha, dispara `reprime_cookies`, retry funciona
- Logs mostram jitter aplicado (não dispara tudo no mesmo segundo)

**Riscos**:
- `asyncio.run` dentro de task Celery cria event loop novo. OK pra esse caso (request curto), mas evita criar/fechar `httpx.AsyncClient` por task — passa via factory.
- Beat replicado = duplicação de jobs. **Garantir replicas: 1**.

**Prompt sugerido**:
> Implemente Fase 3. Mantenha as tasks idempotentes — re-tentar uma `check_watch` no mesmo minuto não deve criar 2 snapshots para o mesmo voo (dedup por `(watch_id, fare_basis, flight_number, departure_at)` na mesma janela de 1min). Use `tenacity` no cliente, `self.retry()` na task para 503/auth.

---

## Fase 4 — Notificação WhatsApp via Evolution API

**Objetivo**: alertar quando o preço cair abaixo do threshold.

**Entregáveis**:
- `app/notifier.py` com `WhatsAppNotifier` usando Evolution API (mesmo padrão dos outros projetos do Rodrigo)
- Settings novas: `EVOLUTION_BASE_URL`, `EVOLUTION_INSTANCE`, `EVOLUTION_API_KEY`
- `notify(watch_id, snapshot_id)` task envia mensagem formatada
- Lógica anti-spam: não envia se já enviou alerta para o mesmo watch nas últimas N horas (default 12h) com preço >= ao último alerta
- Modelo `Alert` registra cada envio (watch_id, snapshot_id, channel, sent_at, success)

**Formato da mensagem (Markdown WhatsApp)**:
```
✈️ *Queda de preço LATAM*

FOR → IGU em 21/06/2026

💰 *22.666 milhas* + R$ 56,88 (LIGHT)
🛫 LA3253 às 06:00 — 1 conexão (GRU)
⏱️ 8h05min

Limite definido: 25.000 milhas
Reservar: https://www.latamairlines.com/br/pt/oferta-voos?...
```

**Critério de aceite**:
- Watch com `max_points=25000` e `notify_phone` configurado: ao detectar 22.666, envia WhatsApp
- Logs em `Alert` ficam consistentes com o histórico de snapshots
- Alertas duplicados em 12h não acontecem (a menos que o preço caia ainda mais)

**Riscos**:
- Evolution API às vezes retorna 200 com erro no body. Validar `response.json()['status']` antes de marcar como `success=True`.

**Prompt sugerido**:
> Implemente Fase 4. Reuse o padrão de Evolution API que tenho em outros projetos (mensagem via `POST /message/sendText/{instance}`). Crie um teste em `tests/test_notifier.py` com `httpx.MockTransport` validando a URL chamada e o payload. Construa a deep link da LATAM com todos os params relevantes para que abrir no celular já caia na busca certa.

---

## Fase 5 — Deploy OCI ARM (Docker Compose)

**Objetivo**: subir tudo na A1 e deixar rodando 24/7.

**Entregáveis**:
- `Dockerfile` multi-stage (builder com `uv`, runtime slim com Playwright chromium pré-instalado)
- `docker-compose.yml` com serviços: `api`, `worker`, `beat`, `postgres`, `redis`, `primer` (one-shot)
- `compose.override.yml.example` para dev local
- `Caddyfile` ou config nginx para expor `api` em HTTPS via domínio próprio
- `scripts/backup-db.sh` e cronjob (pg_dump diário pro bucket OCI)
- README com runbook: como adicionar watch, como ver logs, como rodar primer manualmente
- Healthchecks em todos os serviços

**Pontos críticos do Dockerfile**:
- Imagem base: `mcr.microsoft.com/playwright/python:v1.48.0-jammy` (já vem com chromium ARM64)
- Multi-stage para não levar `uv` no runtime
- `USER` não-root
- Logs em stdout/stderr (Docker handle)

**docker-compose pontos chave**:
```yaml
services:
  beat:
    deploy:
      replicas: 1   # CRÍTICO

  worker:
    deploy:
      replicas: 2   # pode escalar
    volumes:
      - cookies:/app/.cookies   # compartilhado entre workers e primer

  primer:
    profiles: ["primer"]  # roda manualmente: docker compose run primer
    volumes:
      - cookies:/app/.cookies
```

**Critério de aceite**:
- `docker compose up -d` sobe tudo, healthchecks passam
- API acessível em HTTPS pelo domínio
- Beat dispara sweeps; logs mostram execução periódica
- Reiniciar containers não perde cookies (volume persistido)
- Backup do Postgres roda e gera arquivo no bucket

**Riscos**:
- Playwright chromium ARM64 às vezes falha em fontes. Se der erro de render, instalar `fonts-noto-color-emoji` na imagem.
- A1 free tier: 4 OCPUs, 24GB. Mais que suficiente pra esse workload.

**Prompt sugerido**:
> Implemente Fase 5. Considere que a OCI ARM já tem Docker e Caddy configurados. Use o padrão do projeto Vendora (que tenho rodando há meses) como referência para o compose. Garanta que o `primer` rode com `headless=true` em produção mas continue suportando `headless=false` em dev via env var.

---

## Fora do escopo (próximos passos depois das 5 fases)

- Frontend React/Vite simples para gerenciar watches sem precisar de curl
- Endpoint `/calendar` integrado ao monitor (varre o mês inteiro 1× por dia para sugerir melhores datas)
- Suporte a `bff/air-offers/v2/calendar` para descobrir os 5 dias mais baratos do mês
- Histórico em série temporal (queries com window functions pra detectar quedas anômalas, não só thresholds fixos)
- Alerta com previsão: "esse preço caiu 30% nos últimos 7 dias, tendência indica que pode cair mais"
- Suporte a outras programas (Smiles, TudoAzul, Livelo) com a mesma arquitetura

---

## Como usar este plano com Claude Code

1. Abra o projeto no VS Code
2. Inicie o Claude Code: `claude` no terminal integrado
3. Para cada fase, copie o "Prompt sugerido" como mensagem inicial
4. Deixe o Claude Code criar/editar os arquivos. Revise antes de aceitar.
5. Após cada fase, rode os critérios de aceite manualmente.
6. Commit por fase: `git commit -m "feat: fase 1 — cliente BFF"`.

Não pule fases. Cada uma resolve uma camada e a próxima depende dela funcionando.
