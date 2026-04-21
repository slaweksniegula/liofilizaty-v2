# CONTEXT — Liofilizaty Tracker (projekt portfolio #1)

> **Instrukcja użycia:** wklej ten plik na początku każdej nowej sesji z Claude
> (lub załącz go jako plik) razem z pytaniem typu "wracamy do projektu,
> chcę pracować nad [X]". Claude dostanie pełny kontekst w 10 sekund.

---

## Kim jestem

Sławek z Polski, background security engineering (Java/Spring) + crisis management
+ BHP/KPP. Aktualnie przebranżawiam się w stronę **AI + automation** — cel to
stanowisko AI/Automation Engineer albo własna działalność w niszy
BHP-tech + AI.

## Czym jest ten projekt

**„Liofilizaty Tracker"** — **projekt #1 z 10-elementowego portfolio**
AI + n8n, które buduję żeby zdobyć pracę w automatyzacji/AI. Projekt scrapuje
ceny liofilizatów turystycznych w polskich sklepach outdoorowych i codziennie
rano generuje PDF z raportem, a n8n+Claude wysyła powiadomienia o okazjach.

**UWAGA:** ten projekt NIE dotyczy planowania jedzenia na wyprawę do Sarek
(to inny temat). Dotyczy pisania **kodu scrapującego ceny** i pokazania
tego w portfolio jako pierwszą pozycję.

## Stan projektu — gdzie jesteśmy

Zbudowane są dwie wersje:

**v1** (skończona, wrzucona na GitHub) — Python + GitHub Actions cron 09:00 +
SQLite + matplotlib + reportlab. Scrapery dla Skalnik i 8a.pl, generuje
PDF z wykresami historii 15 dni. Kod jest w osobnym repo GitHub
(Sławek trzyma go u siebie, nie jest w tym pliku).

**v2** (w trakcie — Etap 1 i 2 skończone, zweryfikowane lokalnie) — refaktor
na architekturę hybrydową:
- Python FastAPI wystawia istniejące scrapery jako REST API
- n8n (na tym samym serwerze) jest **orkiestratorem** — triggeruje scrape,
  odczytuje wyniki, wywołuje Claude do analizy, wysyła powiadomienia
- Hosting: **Hetzner CAX11** (~15 PLN/mies) + **Coolify** (self-hosted PaaS,
  one-click deploy n8n i aplikacji z GitHub)

Plik `liofilizaty-v2.zip` zawiera kompletny kod v2 (API + Docker).
Do uruchomienia pozostało:
- **Etap 3:** zakup Hetznera + instalacja Coolify + deploy API + deploy n8n
- **Etap 4:** pierwszy workflow w n8n (dzienny scrape + alert o okazjach przez Telegram/email)
- **Etap 5:** workflow tygodniowy (raport PDF mailem) + AI agent (tygodniowe insighty do Notion)
- **Etap 6:** portfolio polish (README v2, diagram architektury, post na LinkedIn)

## Kluczowe decyzje architektoniczne

1. **Hybryda zamiast czystego n8n** — scrapery w Pythonie zostają (robią swoją
   robotę lepiej niż n8n-HTTP-Request), a n8n dopiero WOKÓŁ nich
2. **Hetzner CAX11 + Coolify** — najtańszy reliable stack; darmowe Oracle
   Cloud odrzucone bo problem z dostępnością instancji ARM
3. **SQLite w wolumenie Dockera** — nie Postgres, bo dla 5 produktów × 2 sklepy
   × 365 dni = pomijalnie małe dane
4. **API_KEY w nagłówku X-API-Key** — prosta autoryzacja, wystarczy dla tego
   przypadku (nie ma tu kluczy bankowych ani nic wrażliwego)
5. **`DATA_DIR` env var** — oddziela kod od danych (baza i PDF-y w wolumenie
   `/app/data`, przetrwają redeploy)

## Stack techniczny — co już jest w v2

```
liofilizaty-v2/
├── api.py              ← FastAPI, 10 endpointów (/scrape, /deals, /report/pdf, ...)
├── scraper.py          ← istniejący scraper, czyta DATA_DIR z env
├── storage.py          ← SQLite, upsert per dzień
├── report.py           ← matplotlib + reportlab, PDF z wykresami
├── shops/              ← adaptery per sklep (Skalnik, 8a.pl)
│   ├── base.py
│   ├── skalnik.py
│   └── sklep8a.py
├── config.yaml         ← lista produktów + sklepy + parametry raportu
├── Dockerfile          ← python:3.12-slim + DejaVu fonts + uvicorn
├── docker-compose.yml  ← API + nazwany wolumen na dane
├── .env.example        ← wzorzec dla API_KEY
├── .gitignore
└── requirements.txt    ← fastapi, uvicorn, + wszystko z v1
```

### Endpointy API (zweryfikowane, działają)

- `GET /` — health check
- `GET /products` — lista produktów z config
- `GET /shops` — lista sklepów
- `GET /prices/today` — ceny dziś, wszystkie produkty × sklepy
- `GET /prices/history?days=15` — pełna historia N dni
- `GET /deals?threshold_pct=10` — tylko okazje (cena < (1-X%) średniej 7-dniowej)
- `POST /scrape` — async scrape, zwraca 202
- `POST /scrape/sync` — sync scrape, blokuje do końca
- `POST /report/pdf` — generuje PDF, zwraca ścieżkę
- `GET /report/latest` — pobiera latest.pdf binarnie (dla Gmail/Telegram attachment)

## Plan pierwszego workflow n8n (Etap 4 — do zrobienia)

```
[Schedule Trigger 09:00]
       ↓
[HTTP Request: POST https://liofilizaty.MOJA-DOMENA/scrape]
     headers: X-API-Key = {{$credentials.liofApiKey}}
       ↓
[Wait 3 minutes]     ← scraping trwa ~1 min, zapas bezpieczeństwa
       ↓
[HTTP Request: GET .../deals]
       ↓
[IF: {{$json.count > 0}}]
    TAK ↓                              NIE → koniec
[Split In Batches: 1 okazja naraz]
       ↓
[Claude (Anthropic Chat Model node)]
   prompt: "Produkt {product_name}, cena {price_pln} zł w sklepie {shop_name},
           średnia 7-dniowa {avg_7d_pln} zł, spadek {discount_pct}%.
           Napisz 2-zdaniowy alert dla Sławka, który kompletuje jedzenie na
           trekking. Ton: zwięzły, konkretny, nie sprzedażowy. W pierwszym zdaniu
           nazwa + sklep + cena + procent. W drugim jedno zdanie dlaczego warto
           teraz ({url})."
       ↓
[Telegram: Send Message]
   lub alternatywnie Gmail albo Slack albo Discord — wybieram przy budowie
```

## Co zostało do uzgodnienia przy kontynuacji

Gdy wrócisz do tego projektu, prawdopodobne pytania:
1. Czy mamy już kupiony VPS na Hetzner, czy trzeba to zrobić?
2. Czy chcesz instrukcję Coolify z screenshotami czy sam klikniesz?
3. Na czym chcesz dostawać alerty — Telegram / Gmail / Slack / coś innego?
4. Czy chcesz dopisać jeszcze 3-5 sklepów (WGL, Sportano, Sewel, 4Camping,
   Equip, Militaria, turmat.store) w tej wersji, czy najpierw dopiąć workflow
   z 2 sklepami co są?
5. Czy Claude Code jest zainstalowany na Macu? Jeśli tak, część etapów można
   zrobić z jego pomocą (on ma dostęp do filesystemu i terminala).

## Portfolio — kontekst szerszy

Po skończeniu tego projektu, kolejne 9 pozycji z planu portfolio (w kolejności):
2. Generator kart oceny ryzyka BHP z opisu stanowiska
3. Research assistant dla trekerów (pod reele na TikToka)
4. Monitor nowych ofert pracy AI+n8n (z powiadomieniami)
5. Chatbot Q&A do procedur bezpieczeństwa firmy (RAG)
6. Generator materiałów szkoleniowych BHP z przepisów
7. System raportowania incydentów BHP z AI vision
8. Agent planujący ćwiczenia ewakuacyjne
9. Content engine dla reeli o trekkingu
10. SaaS MVP: ComplianceBot dla małych firm

Cały plan portfolio jest w pliku `portfolio-10-projektow.pdf`.

## Instrukcja dla Claude w nowej sesji

Gdy dostajesz ten kontekst:
1. Zapytaj Sławka konkretnie, na czym chce pracować dzisiaj (który etap, jaki problem)
2. NIE proponuj od zera — bazuj na tym co opisane powyżej
3. Unikaj przeplatania z tematem "jedzenie na wyprawę Sarek" — to inny wątek
4. Jeśli Sławek wspomni "v1", "v2", "prices.db", "Coolify", "n8n workflow" —
   to właśnie ten projekt, nie planowanie menu na trekking
5. Jeśli czegoś ci brakuje w kontekście, poproś Sławka o wklejenie
   konkretnego pliku (najczęściej `api.py` albo `config.yaml`)
