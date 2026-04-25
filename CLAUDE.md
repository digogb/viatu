# Viatu — Monitor de preços em milhas

Sistema que consulta periodicamente o BFF do `latamairlines.com` para monitorar preços de passagens em pontos LATAM Pass e alertar quando cair abaixo de um limite.

## Stack

- **Python 3.12** com `uv` para gestão de deps
- **FastAPI** + **httpx[http2]** para o cliente do BFF
- **Celery** + **Redis** para tarefas periódicas
- **PostgreSQL** + **SQLAlchemy 2.x** + **Alembic** para histórico
- **Playwright** (chromium) só para cookie priming inicial
- **Evolution API** (já em uso em outros projetos) para alerta no WhatsApp
- Deploy: Docker Compose na OCI ARM (Ampere A1)

## Arquitetura em 3 processos

1. **`api`** (FastAPI/uvicorn) — CRUD de watches, busca on-demand, healthcheck
2. **`worker`** (Celery worker) — executa `check_watch`, `reprime_cookies`, `notify`
3. **`beat`** (Celery beat) — agenda `sweep_active_watches` (a cada 30min) e `reprime_cookies` (a cada 4h)

Singleton: **beat tem replicas: 1 obrigatoriamente**.

## Fluxo de uma consulta

```
Beat → sweep_active_watches → enfileira N check_watch (com jitter)
  → check_watch carrega Watch
  → LatamClient.search() → GET BFF com cookies do .latam_cookies.json
  → parse → grava PriceSnapshot por (brand, fare_basis)
  → se min(LIGHT, stops<=1).points <= watch.max_points → enfileira notify
```

Em 401/403: dispara `reprime_cookies` (subprocess Playwright) e re-tenta com backoff.

## Endpoint do BFF (confirmado)

```
GET https://www.latamairlines.com/bff/air-offers/v2/offers/search/redemption
  ?redemption=true
  &origin=FOR&destination=IGU
  &outFrom=2026-06-21
  &adult=1&child=0&infant=0
  &cabinType=Economy
  &sort=RECOMMENDED
  &locale=pt-br
  &outOfferId=null&inOfferId=null
  &outFlightDate=null&inFlightDate=null
  [&inFrom=2026-06-26]   # se RT
```

Resposta: `content[].summary.brands[]` com `price.amount` em LOYALTY_POINTS, `taxes.amount` em BRL, `farebasis` (código tarifário), `offerId` (token efêmero), `lowestPrice` (do itinerário). Ver `docs/sample-response.json`.

Endpoint complementar (calendário do mês inteiro, mais barato):

```
GET https://www.latamairlines.com/bff/air-offers/v2/calendar
  ?origin=FOR&destination=IGU&month=6&year=2026&isRoundTrip=true
```

## Anti-bot

O `latamairlines.com` está atrás de Akamai Bot Manager. Cookies do tipo `_abck`, `bm_sv`, `bm_sz` são obrigatórios. A estratégia (mesma usada no scraper do STJ): Playwright abre uma busca real uma vez, salva os cookies em `.latam_cookies.json`, e o cliente httpx os reusa. Quando dá 403, re-roda o primer.

**Não rode Playwright dentro do worker async.** O `reprime_cookies` faz `subprocess.run(["python", "-m", "app.primer"])` para isolar o event loop.

## Modelos

- `Watch` — rota + datas + critérios (max_points, cabin, only_direct, interval_minutes)
- `PriceSnapshot` — append-only, FK pra Watch, indexado por (watch_id, captured_at). Guarda `points`, `taxes_brl`, `fare_brand`, `fare_basis`, `flight_number`, `stops`, `departure_at`.
- `Alert` — quando disparou notify, com qual snapshot e canal

## Limites e cuidados

- Cadência mínima: 30 min/rota. Mais agressivo atrai bloqueio.
- Jitter no sweep: 0–60s + 5s × índice, para não rajar requisições.
- `task_acks_late=True` + `worker_prefetch_multiplier=1` no Celery (requests caras, evita perda).
- Cache Redis 10 min nas buscas on-demand do FastAPI.
- TTL do `offerId` é curto (minutos): salvar só pra auditoria, não pra reusar.

## Convenções

- Tudo em Português nas mensagens de log/UI/notificação. Código e nomes de variáveis em inglês.
- Datas sempre em ISO (`YYYY-MM-DD`) na fronteira da API; SQLAlchemy usa `date`/`datetime` nativos.
- `stops`: 0 = direto, 1 = uma conexão. Default do monitor é alertar com `stops <= 1`.
- Brands LATAM, do mais barato pro mais caro: `LIGHT` < `STANDARD` < `FULL` < `PREMIUM ECONOMY`. Monitorar LIGHT por padrão.

## Comandos

```bash
uv sync                                    # instalar deps
uv run playwright install chromium         # 1ª vez
uv run python -m app.primer                # gerar cookies (1×, ou quando 403)
uv run alembic upgrade head                # subir schema
docker compose up -d                       # subir tudo
docker compose logs -f worker beat         # acompanhar
```

## Skills relevantes

- Quando mexer em código Python desse projeto, padrões a seguir: type hints sempre, `pydantic` v2, `from __future__ import annotations` se necessário, async no que toca rede/db.
- Antes de criar nova migration: `alembic revision --autogenerate -m "..."` e revisa o SQL gerado antes de aplicar.

## O que NÃO fazer

- Não chamar Playwright dentro de coroutine do FastAPI ou worker. Sempre subprocess.
- Não persistir `offerId` como fonte de verdade para booking — é efêmero.
- Não baixar a cadência abaixo de 15 min sem necessidade real.
- Não rodar `beat` com mais de 1 réplica.
- Não logar valores completos de cookies (mask `_abck`, `bm_sv`).
