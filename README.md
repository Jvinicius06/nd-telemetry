# ND Telemetry

Coletor de telemetria para descobrir **por que alguns devices ESP8266 reiniciam sozinho**.
Registra cada reboot (com o motivo: queda de energia, crash/exception, watchdog, restart de
software) e eventos operacionais (ex.: queda de WiFi) para correlacionar o comportamento
"funciona localmente mas não recebe dados da rede".

Dois servidores em **um único container** (HTTP puro, sem SSL):

| Porta | Servidor | Uso | Auth |
|------|----------|-----|------|
| `8080` | **Device API** | ingest barato dos devices | nenhuma |
| `8081` | **Dashboard** | painel administrativo | HTTP Basic |

Stack: Python + FastAPI + SQLite (arquivo único em `/data`). Sem dependências externas em runtime.

---

## Subir

```bash
# com docker compose (recomendado)
docker compose up --build -d
#  -> device API:  http://<host>:8080
#  -> dashboard:   http://<host>:8081   (admin / change-me)

# ou docker puro
docker build -t nd-telemetry .
docker run -d --name nd-telemetry -p 8080:8080 -p 8081:8081 \
  -e ND_ADMIN_PASS=segredo -v "$PWD/data:/data" nd-telemetry
```

Rodar local sem Docker:

```bash
pip install -r requirements.txt
python -m app.main
```

### Variáveis de ambiente

| Var | Default | Descrição |
|-----|---------|-----------|
| `ND_DEVICE_PORT` | `8080` | porta da API de ingest |
| `ND_DASHBOARD_PORT` | `8081` | porta do dashboard |
| `ND_DB_PATH` | `/data/telemetry.db` | caminho do SQLite |
| `ND_ADMIN_USER` | `admin` | usuário do dashboard |
| `ND_ADMIN_PASS` | `admin` | senha do dashboard (**troque!**) |

---

## API de devices (porta 8080)

Três formas de enviar — escolha a mais barata para o device:

### 1. `GET /v1/i` — ingest compacto (mais barato)
Sem corpo, sem JSON. Ideal para ESP8266.

**Boot / reset:**
```
GET /v1/i?d=<MAC>&k=boot&r=<reason>&ec=<exccause>&epc1=<epc1>&va=<excvaddr>&h=<heap>&up=<uptime_s>&fw=<ver>&rssi=<rssi>
```
**Evento:**
```
GET /v1/i?d=<MAC>&k=event&t=wifi_disconnect&m=<msg>&h=<heap>&rssi=<rssi>
```
Chaves: `d`=device, `k`=kind(boot|event), `r`=reason, `ec`=exccause, `va`=excvaddr,
`h`=heap, `up`=uptime, `t`=tipo do evento, `m`=mensagem. Endereços aceitam `0x...`.
Resposta: `OK` (corpo mínimo).

### 2. `POST /v1/boot` (JSON)
```json
{ "dev":"A4CF12AABBCC", "fw":"1.4.2", "reason":2, "exccause":28,
  "epc1":1075843260, "excvaddr":0, "heap":4200, "uptime":37, "rssi":-71 }
```

### 3. `POST /v1/event` (JSON)
```json
{ "dev":"A4CF12AABBCC", "type":"wifi_disconnect", "msg":"reason=202", "heap":4200, "rssi":-83 }
```

`GET /healthz` → `{"ok":true}`.

### Motivos de reset (ESP8266 `system_get_rst_info()`)

| `reason` | Significado | Classificação |
|---------|-------------|---------------|
| 0 | Power-on / Brown-out (**queda de energia**) | normal |
| 1 | Hardware WDT | **anormal** |
| 2 | Exception (**crash**) — ver `exccause`/`epc1` | **anormal** |
| 3 | Software WDT | **anormal** |
| 4 | Software restart (`system_restart`, OTA) | normal |
| 5 | Deep-sleep wake | normal |
| 6 | External reset (pino RST) | normal |

---

## Integração no firmware (ESP8266)

> ⚠️ **Restrições do firmware** (CLAUDE.md): **não** crie task nova. Reporte o boot **uma vez**,
> de dentro de uma task existente (ex.: `task_main`) logo após o WiFi conectar. Monte a URL em
> buffer de **stack < 256 B** ou estático single-thread; nada de buffers grandes. Use o
> transporte HTTP que já existe no projeto.

Captura do motivo no boot:

```c
#include "user_interface.h"   // system_get_rst_info()

void report_boot_reason(void) {
    struct rst_info *r = system_get_rst_info();
    char url[200];                 // < 256 B, fica na stack
    // monta GET compacto; %08x para os endereços de exception
    snprintf(url, sizeof url,
        "/v1/i?d=%s&k=boot&r=%u&ec=%u&epc1=0x%08x&va=0x%08x&h=%u&fw=%s",
        device_id_str(),          // ex.: MAC sem ":"
        r->reason, r->exccause, r->epc1, r->excvaddr,
        (unsigned) system_get_free_heap_size(),
        FW_VERSION);
    http_get(TELEMETRY_HOST, 8080, url);   // transporte HTTP já existente
}
```

Eventos (ex.: queda de WiFi — para o caso "funciona local mas sem rede"):

```c
// no handler de desconexão do WiFi
char url[160];
snprintf(url, sizeof url, "/v1/i?d=%s&k=event&t=wifi_disconnect&m=reason%u&rssi=%d",
         device_id_str(), disc_reason, wifi_station_get_rssi());
http_get(TELEMETRY_HOST, 8080, url);
```

Outros eventos úteis: `wifi_reconnect`, `heap_low` (quando `free_heap` cruza um limiar),
`got_ip`, `mqtt_lost` etc. — basta mudar `t=`.

---

## Dashboard (porta 8081)

- **Visão geral**: nº de devices, offline (>10 min), reboots 24h/7d, crashes/WDT, eventos WiFi,
  e a distribuição de motivos de reboot.
- **Por device**: status online/offline, firmware, histórico de motivos e uma **timeline**
  unificada de reboots + eventos (com `exccause`, `epc1`/`excvaddr` em hex para crashes).

Endpoints JSON (mesma auth): `/api/overview`, `/api/devices`, `/api/device/{id}`.

---

## Estrutura

```
nd-telemetry/
├── Dockerfile              # imagem única
├── docker-compose.yml
├── requirements.txt
└── app/
    ├── main.py             # sobe os 2 servidores (asyncio)
    ├── device_api.py       # API de ingest (8080)
    ├── dashboard.py        # painel admin (8081)
    ├── db.py               # SQLite (boots, events, devices)
    ├── models.py           # tabelas de reset reason / exccause
    └── templates/          # HTML do dashboard
```

## Roadmap (próximos passos, fora do escopo atual)
- Alertas (webhook/Telegram) quando crashes de um device passam de N em 1h.
- Decodificar `epc1` → linha de código via `.elf` + `addr2line`.
- Retenção / limpeza automática de registros antigos.
