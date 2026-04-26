# Estratégia Anti-Bot LATAM — Diagnóstico e Solução

## O que a LATAM usa

A stack de proteção tem **duas camadas independentes**:

### Camada 1 — Akamai Bot Manager (CDN)
Valida o cliente antes de passar o request para a aplicação.

- **Cookie `_abck`**: resultado do JavaScript challenge do Akamai. Codifica um score de confiabilidade (`~0~` = legítimo, `~-1~` = bot suspeito).
- **Cookie `bm_sv` / `bm_sz`**: cookies de sessão comportamental do Akamai.
- **TLS fingerprint (JA3)**: compara o fingerprint TLS com perfis conhecidos de browsers reais. `httpx` puro tem JA3 diferente do Chrome → 400.
- **HTTP/2 settings**: ordem e valores dos frames SETTINGS também fazem parte do fingerprint.

**Resultado dos testes**: `curl_cffi` com `impersonate="chrome"` passa pelo Akamai (chega na camada 2).

### Camada 2 — Aplicação LATAM (BFF)
Valida tokens gerados pelo frontend antes de responder com preços.

| Header | Tipo | Validade | Como é gerado |
|--------|------|----------|---------------|
| `x-latam-captcha-token` | reCAPTCHA Enterprise v3 | ~2 min | JS do browser via `www.recaptcha.net/recaptcha/enterprise.js` |
| `x-latam-search-token` | JWT HS512 | 20 min | Bundle `web-air-offers` em `s.latamairlines.com` (atrás de auth) |
| `x-latam-request-id` | UUID v4 | por request | Gerado pelo frontend, replicável |
| `x-latam-track-id` | UUID v4 | por request | Idem |
| `x-latam-app-session-id` | UUID v4 | por sessão | Idem |

**Site key reCAPTCHA Enterprise (prod)**: `6LdLc4gdAAAAAFNjKQtyrDorNRhPnayEajdsRS90`

**Payload do `x-latam-search-token`** (JWT decodificado):
```json
{
  "country": "BR",
  "language": "PT",
  "destination": "GRU",
  "origin": "FOR",
  "message": "Hi Hacker friend, if you need to see our offers out of our site, feel free to contact us and we will see how we can help you. Thank you.",
  "iat": 1777217374,
  "exp": 1777218574
}
```
Assinado com HS512. Chave de assinatura está no bundle `web-air-offers` servido por `s.latamairlines.com` após autenticação Auth0 — impossível extrair sem estar logado.

---

## O que tentamos e por que não funcionou

| Abordagem | Resultado | Motivo |
|-----------|-----------|--------|
| `httpx` direto com cookies | 400 Bad Request | TLS fingerprint errado → Akamai rejeita |
| `curl_cffi` `impersonate="chrome"` | 403 Forbidden — "Missing latam headers" | Passa Akamai, mas faltam `captcha-token` e `search-token` |
| `curl_cffi` + token de captcha aleatório | 403 Forbidden | Backend valida token contra Google (reCAPTCHA Enterprise) |
| Playwright `--init` no WSL | Erro reCAPTCHA v2 ao logar | WSL não alcança `www.recaptcha.net` — problema de rede da VM |
| Playwright + cookies estáticos sem `_xp_session` válido | Redirecionado para login Auth0 | Sessão LATAM expirada ou exportação incompleta dos cookies |

---

## Solução que funcionou

### Abordagem: Playwright intercept da response do BFF

O browser real (Chromium via Playwright) navega até a página de busca com a sessão autenticada restaurada via `storage_state`. O frontend da LATAM gera automaticamente o `captcha-token`, o `search-token` e faz o request BFF. Nós interceptamos a **response** via `ctx.on("response", ...)`.

**Por que funciona:**
- reCAPTCHA v3 (usado na busca) é invisível — não exige interação do usuário e funciona no Chromium headless.
- O reCAPTCHA v2 (login) era o problema original — não é necessário porque já temos sessão autenticada nos cookies.
- O Playwright usa o Chromium real com fingerprint legítimo, passando pelo Akamai naturalmente.

### Arquitetura final

```
Worker Celery (sync)
  └─ check_watch(watch_id)
       ├─ asyncio.run(_load_watch)          → busca watch no banco (async)
       ├─ PlaywrightSearchClient.search()   → subprocess playwright_search (sync)
       │     └─ app/playwright_search.py
       │           ├─ restore storage_state
       │           ├─ stealth_async (tf-playwright-stealth)
       │           ├─ ctx.on("response") → captura BFF response
       │           ├─ page.goto(URL de busca)
       │           ├─ asyncio.wait_for(captured, timeout=30)
       │           └─ imprime JSON no stdout
       └─ asyncio.run(_save_and_notify)     → grava snapshots + dispara notify (async)
```

**Por que subprocess (não coroutine direta):**
Playwright cria seu próprio event loop. Celery tasks são síncronas e usam `asyncio.run()` para as ops de banco — dois `asyncio.run()` consecutivos na mesma thread sync funcionam, mas Playwright dentro de um `asyncio.run()` existente causaria nested loop. O subprocess isola completamente.

### Fluxo de cookie management

```
1ª vez (ou sessão expirada):
  uv run python -m app.primer --init
    → abre Chromium headed no Windows (não WSL)
    → login manual na LATAM (Auth0 + senha, sem reCAPTCHA v2 no browser real)
    → salva .latam_storage.json (storage_state completo)
    → salva .latam_cookies.json (cookies do domínio latamairlines.com)

Renovação automática (a cada 4h via Celery beat):
  reprime_cookies task → subprocess app.primer (warmup)
    → restaura storage_state
    → navega na homepage para renovar bm_sv, _abck, _xp_session
    → salva cookies atualizados

Busca periódica (a cada 30min via sweep_active_watches):
  PlaywrightSearchClient.search()
    → subprocess app.playwright_search
    → restaura storage_state → intercepta BFF → atualiza cookies → retorna JSON
```

### Formato de exportação de cookies (Cookie-Editor → Playwright)

O Cookie-Editor do Chrome exporta em formato diferente do Playwright. Ao exportar manualmente, converter com:

```python
SAMESIDE_MAP = {"no_restriction": "None", "strict": "Strict", "lax": "Lax", None: "Lax"}
converted = [{
    "name": c["name"], "value": c["value"], "domain": c["domain"],
    "path": c.get("path", "/"),
    "expires": c.get("expirationDate", -1) if not c.get("session", False) else -1,
    "httpOnly": c.get("httpOnly", False),
    "secure": c.get("secure", False),
    "sameSite": SAMESIDE_MAP.get(c.get("sameSite"), "Lax"),
} for c in raw]
```

Depois injetar no `storage_state`:
```python
state = json.load(open(".latam_storage.json"))
latam_domains = {".latamairlines.com", "www.latamairlines.com"}
state["cookies"] = [c for c in state["cookies"] if c["domain"] not in latam_domains] + converted
json.dump(state, open(".latam_storage.json", "w"))
```

### Cookie crítico: `_abck`

O cookie `_abck` do Akamai tem um score embutido:
- `hash~0~...` → cliente legítimo (browser real com JS challenge passado)
- `hash~-1~...` → bot suspeito

O `_abck` exportado do Chrome real (após navegar e fazer buscas) vem com `~0~`. Se o score for `-1~`, o backend LATAM pode exigir o `captcha-token` mesmo com outros cookies válidos.

**Sempre exportar cookies do Chrome após fazer uma busca real** (não só abrir a homepage) para garantir `_abck` com score `~0~`.

---

## Resultado validado

```
FOR → GRU em 21/06/2026 — 198 opções capturadas
  LIGHT          | 28.712 pts | R$ 56,88 | LA3319 | direto
  STANDARD       | 31.802 pts | R$ 56,88 | LA3319 | direto
  FULL           | 33.017 pts | R$ 56,88 | LA3319 | direto
  PREMIUM ECONOMY| 33.365 pts | R$ 56,88 | LA3883 | direto
```

Latência: ~10s por busca (navegação + captura BFF). Aceitável para cadência de 30min.

---

## Trade-offs

| Aspecto | Impacto |
|---------|---------|
| Latência por busca | ~10s vs <1s com httpx direto — aceitável para 30min de cadência |
| Memória por busca | ~150MB Chromium por subprocess (processo encerrado após captura) |
| Confiabilidade | Alta — usa o mesmo stack do browser legítimo |
| Renovação de sessão | Manual inicialmente (primer --init no Windows). Warmup automático a cada 4h. |
| Escalabilidade | Adequado para <50 watches. Acima disso, pool de browsers ou paralelismo de subprocesses. |

---

## Arquivos relevantes

| Arquivo | Papel |
|---------|-------|
| `app/playwright_search.py` | Script standalone — navega + intercepta BFF + stdout JSON |
| `app/primer.py` | Login inicial (--init) e warmup de cookies |
| `app/latam_client.py` | `PlaywrightSearchClient` (wrapper subprocess) + `LatamClient` (curl_cffi, para calendar) |
| `app/cookie_store.py` | Lê/escreve `.latam_cookies.json` e `.latam_storage.json` |
| `.latam_storage.json` | Storage state completo do Playwright (cookies + localStorage de todos os domínios) |
| `.latam_cookies.json` | Cookies no formato Playwright para latamairlines.com |
| `.latam_bff_headers.json` | Headers `x-latam-*` estáticos capturados do DevTools |
