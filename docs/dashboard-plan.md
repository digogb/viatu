# Plano — Dashboard Web do Viatu

Frontend SPA + endpoints novos no backend para visualizar watches, executar buscas manuais (incluindo range de datas/meses) e converter buscas em monitoramentos.

## Stack

- **Frontend**: React 18 + Vite 5 + Tailwind 3 + React Router 6 + Axios + Recharts (gráficos) + Lucide (ícones) + date-fns
- **Backend**: endpoints novos em FastAPI; build estático do React servido pelo mesmo container (`StaticFiles`)
- **Auth**: login simples baseado em senha única + JWT em cookie httpOnly (single-user)

## Decisões assumidas

| Tema | Decisão |
|------|---------|
| Range curto (≤7 dias específicos) | Síncrono — um Playwright por data, em série, ~70s no pior caso |
| Range médio (mês inteiro) | Calendar BFF (1 request/mês, ~3s) — só pontos, sem brand discriminada |
| Range longo (vários meses) | Async — cria job, frontend faz polling em `/jobs/{id}` |
| Detalhar dia específico | Botão "Detalhar" na tabela do calendar dispara Playwright sob demanda |
| Auth | Senha única em env (`DASHBOARD_PASSWORD`), JWT em cookie httpOnly com 30d de validade |
| Origem default | `FOR` (Fortaleza), persistida em localStorage |

## Modelo de dados — adições

Apenas duas tabelas novas:

```python
class SearchJob(Base):
    """Job de busca em range — usado quando o range é grande demais pra síncrono."""
    id: int
    kind: Literal["calendar", "range_dates", "range_months"]
    params: JSON          # origin, destination, dates ou month list, cabin, adults
    status: Literal["pending", "running", "done", "error"]
    progress: int         # 0..100
    result: JSON | None   # lista de SearchResult
    error: str | None
    created_at, updated_at
```

`Watch` ganha um campo opcional `notes: str | None` para o usuário escrever o motivo do monitoramento.

## Endpoints novos (API)

### Busca

```
POST /api/search                  # síncrono — uma data específica via Playwright (já existe)
POST /api/search/calendar          # síncrono — mês inteiro via calendar BFF
  body: { origin, destination, year, month, round_trip? }
  resp: { days: [{ date, points, taxes_brl }] }

POST /api/search/range             # async se >7 dias, senão síncrono
  body: { origin, destination, dates: [date], cabin, adults }
  resp síncrono: { results: [SearchResult] }
  resp async: { job_id }

GET  /api/jobs/{id}                # polling de status
```

### Watches (extensão dos existentes)

```
GET  /api/watches                  # já existe
GET  /api/watches/{id}/history     # NOVO — snapshots agrupados por dia + min/max/avg
PUT  /api/watches/{id}/active      # NOVO — toggle rápido (vs. PATCH)
POST /api/watches/from-search      # NOVO — cria watch a partir de um resultado de busca
  body: { origin, destination, departure, return_date?, max_points, ... }
```

### Auth

```
POST /api/auth/login    body: { password }       → set-cookie: viatu_session
POST /api/auth/logout
GET  /api/auth/me                                # retorna 401 se não logado
```

Middleware FastAPI em todas as rotas `/api/*` exceto login: valida o cookie. Em caso de 401, frontend redireciona pra `/login`.

## Páginas (frontend)

```
/login          — campo de senha + botão entrar
/               — Dashboard
/buscar         — Busca manual
/watch/:id      — Detalhe do watch
/config         — (opcional na primeira versão) — preferências
```

### `/` Dashboard

- Header com origem default + botão "Nova busca"
- Cards (grid responsivo) — 1 por watch ativo:
  - Rota (`FOR → IGU`), data ou range
  - Último preço LIGHT (pontos + R$ taxas) + delta vs. snapshot anterior
  - Mini-sparkline 30 dias
  - Badge "ALERTOU 2x" se houve alertas no período
  - Toggle ativo/pausado
  - Click → `/watch/:id`
- Seção "Pausados" colapsada no fim

### `/buscar`

```
┌─────────────────────────────────────────────────┐
│ Origem: [FOR ▾]   Destino: [____]               │
│                                                 │
│ Tipo: ( ) Data específica                       │
│       (•) Range de datas                        │
│       ( ) Mês inteiro (calendar)                │
│       ( ) Vários meses (calendar combinado)     │
│                                                 │
│ De: [2026-06-01]  Até: [2026-06-30]             │
│ Cabine: [Y ▾]   Passageiros: [1 ▾]              │
│                                                 │
│         [Buscar]                                │
└─────────────────────────────────────────────────┘

Resultados (33 datas, ordenado por pontos):
┌──────────┬─────────┬─────────┬───────┬────────┐
│ Data     │ Pontos  │ R$ taxa │ Voo   │ Ações  │
├──────────┼─────────┼─────────┼───────┼────────┤
│ 21/06    │ 28.712  │ 56,88   │LA3319 │ [👁][⭐]│
│ 23/06    │ 29.150  │ 56,88   │LA3319 │ [👁][⭐]│
│ ...                                            │
└────────────────────────────────────────────────┘
```

- 👁 = abre detalhamento Playwright (modal com brands LIGHT/STANDARD/FULL)
- ⭐ = "Monitorar" → modal com `max_points` sugerido (preço atual − 10%) e cria watch

Para "Mês inteiro" o resultado é um heatmap calendário em vez de tabela.

### `/watch/:id`

- Cabeçalho: rota, datas, max_points (editável inline), toggle ativo
- Gráfico (Recharts) — linha de pontos LIGHT ao longo do tempo, marcadores nos alertas disparados
- Tabela de snapshots — paginada, agrupada por dia, mostrando min/max/avg
- Lista de alertas enviados (se houver)
- Botões: "Forçar check agora" (chama `/watches/{id}/check`), "Excluir"

## Fases de implementação

Cada fase é um commit isolado. Frontend e backend podem ir em paralelo após a Fase 1.

---

### Fase 1 — Auth + scaffold do frontend

**Backend**
- `app/auth.py`: middleware JWT, dependency `require_auth`
- Settings novas: `DASHBOARD_PASSWORD`, `JWT_SECRET`, `JWT_TTL_DAYS=30`
- `POST /api/auth/login` `POST /api/auth/logout` `GET /api/auth/me`
- Aplicar `Depends(require_auth)` em todas as rotas `/api/*` exceto auth e health

**Frontend**
- `frontend/` no repo: Vite + React + Tailwind + Router + Axios
- `src/api.js` — instância Axios com `withCredentials: true` e interceptor 401 → `/login`
- Página `/login`
- Layout com sidebar (Dashboard / Buscar / Config) protegido
- Build dev rodando em `localhost:5173` com proxy para a API em `:8000`

**Aceite**: senha errada retorna 401, senha certa loga e redireciona pra `/`. Sem cookie acessar `/api/watches` retorna 401.

---

### Fase 2 — Dashboard básico

**Backend**
- `GET /api/watches/{id}/history?days=30` — agrupa snapshots por dia, retorna `{ date, min_points, max_points, last_taxes_brl }`
- Ajustar `GET /api/watches` para incluir `last_snapshot` (LIGHT mais recente) embutido

**Frontend**
- `Dashboard.jsx` lista watches em cards
- Card usa o `last_snapshot` + sparkline com `history?days=30`
- Toggle ativo via `PUT /api/watches/{id}/active`

**Aceite**: cards renderizam, toggle persiste, sparkline aparece. Watches sem snapshots ainda mostram "Nenhuma busca ainda" + botão "Forçar check".

---

### Fase 3 — Busca manual (data específica e range curto)

**Backend**
- `POST /api/search/range` — para até 7 dates em série, chama `PlaywrightSearchClient` em loop e retorna `[{ date, cheapest_light, options }]`
- Cache Redis 10 min por `(origin, destination, date, cabin)`

**Frontend**
- Página `/buscar` com formulário
- Tipo "Data específica" → 1 request, mostra brands em tabela
- Tipo "Range de datas" (até 30 dias) → faz N requests em série mostrando progresso ("buscando 5/30...")
- Botão ⭐ Monitorar → modal com prefill, `POST /api/watches/from-search`

**Aceite**: range de 7 dias retorna em <90s. Criar watch a partir de resultado funciona e aparece no dashboard.

---

### Fase 4 — Calendar BFF + heatmap

**Backend**
- `LatamClient.calendar()` (já existe em `latam_client.py`) — testar se passa pelo anti-bot ou precisa ir via Playwright também
  - Se precisar Playwright: criar `app/playwright_calendar.py` análogo ao `playwright_search.py`, interceptando a URL `/bff/air-offers/v2/calendar`
- `POST /api/search/calendar` — recebe ano/mês, retorna lista de `{ date, points, taxes_brl }`
- Cache Redis 1h

**Frontend**
- Tipo de busca "Mês inteiro" renderiza heatmap calendário com cores escalonadas (verde = barato, vermelho = caro)
- Click numa data abre detalhamento Playwright (brands LIGHT/STANDARD/FULL)
- Tipo "Vários meses" → roda calendar para cada mês e mescla resultados em tabela ordenável

**Aceite**: heatmap de 1 mês carrega em <5s. Click em data abre brands corretos via Playwright.

---

### Fase 5 — Jobs assíncronos para ranges grandes

**Backend**
- Migration: tabela `search_jobs`
- Task Celery `run_search_job(job_id)` — executa o range e atualiza `progress`/`result`
- `POST /api/search/range` com `dates > 7` retorna `{ job_id }` em vez de resultado síncrono
- `GET /api/jobs/{id}` retorna status + result quando done

**Frontend**
- Quando recebe `job_id` em vez de resultado: tela de progresso com polling a cada 2s
- Cancelar = `DELETE /api/jobs/{id}` (revoga task Celery)

**Aceite**: range de 60 dias roda em background, progresso atualiza, resultado aparece quando termina. Refresh da página não perde o job.

---

### Fase 6 — Detalhe do watch

**Backend**
- `GET /api/watches/{id}/snapshots?from=&to=&page=` — paginado
- `GET /api/watches/{id}/alerts` — lista de alertas disparados

**Frontend**
- Página `/watch/:id` com:
  - Header editável (max_points, notes inline)
  - Gráfico Recharts: linha de pontos LIGHT no tempo + scatter de alertas
  - Tabela de snapshots paginada
  - Botão "Forçar check agora" → `POST /watches/{id}/check`

**Aceite**: gráfico mostra evolução de 30/90 dias. Forçar check insere snapshot novo e gráfico atualiza.

---

### Fase 7 — Polish + build de produção

**Backend**
- Servir build estático: `app.mount("/", StaticFiles(directory="frontend/dist", html=True))` no fim do `main.py`
- Catch-all para SPA routing

**Dockerfile**
- Stage `frontend-builder`: `node:20-alpine`, `npm ci`, `npm run build`
- Stage final: copia `frontend/dist` pra `/app/frontend/dist`

**Frontend**
- Skeleton loaders nos cards/tabelas
- Toasts (sonner) para sucesso/erro de ações
- Atalhos de teclado: `n` = nova busca, `/` = focar busca

**Aceite**: `docker compose up` sobe API + frontend juntos em `:8000`. Build de produção carrega em <2s no 4G.

---

## Fora do escopo desta entrega

- Multi-usuário / RBAC
- Notificações in-app (push browser)
- Comparativo entre rotas similares ("FOR→GRU vs FOR→VCP")
- Export CSV
- Dark mode (deixar pré-configurado no Tailwind, mas só o claro na primeira versão)

## Riscos

- **Calendar BFF anti-bot**: se também exigir tokens dinâmicos, todo `/calendar` vira Playwright e perde a vantagem de velocidade. Validar logo na Fase 4.
- **Concorrência Playwright**: rodar N subprocesses Chromium em paralelo no worker ARM = pico de RAM. Limitar concurrency a 2 e fazer fila se necessário.
- **JWT secret rotacionado** = todos deslogam. OK pra single-user, mas documentar no README.
