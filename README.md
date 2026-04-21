# Liofilizaty tracker

Codzienny, automatyczny monitor cen liofilizatów turystycznych w polskich sklepach outdoorowych. Scrapuje o 9:00 rano, generuje PDF z wykresami historii cen i oznacza okazje.

**Obecna faza:** prototyp na 2 sklepach (Skalnik + 8a.pl). Po potwierdzeniu że scraping działa, dołożymy WGL, Sportano, Sewel, turmat.store, 4Camping, Equip, Militaria.

---

## Jak to działa

Codziennie o 9:00 czasu polskiego GitHub Actions:
1. Odpytuje wyszukiwarki obu sklepów dla każdego produktu z `config.yaml`.
2. Parsuje ceny i dostępność, zapisuje do `prices.db` (SQLite w repo).
3. Generuje PDF z wykresami ostatnich 15 dni per produkt, tabelką "najtaniej dziś" i alertami okazji.
4. Commituje zmiany z powrotem do repo.

PDF jest dostępny w dwóch miejscach:
- `raporty/YYYY-MM-DD.pdf` — pełna historia
- `raporty/latest.pdf` — zawsze aktualny
- Dodatkowo jako GitHub Actions artifact (30 dni retencji)

---

## Setup — raz na zawsze

### 1. Utwórz repo na GitHub

Zaloguj się na GitHub → **New repository** → nazwa np. `liofilizaty-tracker` → **Private** (żeby nie pokazywać światu co jesz na Sareku 😄) → bez README → **Create**.

### 2. Wrzuć kod

Na Macu w terminalu:

```bash
cd ~/Dokumenty/AI_Agent   # albo gdziekolwiek
# Rozpakuj otrzymany folder projektu, wejdź do niego
cd liofilizaty-tracker

git init
git add .
git commit -m "Initial: prototyp Skalnik + 8a"
git branch -M main
git remote add origin git@github.com:TWOJ_LOGIN/liofilizaty-tracker.git
git push -u origin main
```

### 3. Włącz GitHub Actions

Wejdź w repo → zakładka **Actions** → kliknij "I understand my workflows, go ahead and enable them".

### 4. Daj Actions prawo do push

**Settings** → **Actions** → **General** → sekcja "Workflow permissions" → zaznacz **"Read and write permissions"** → **Save**.

Bez tego workflow nie będzie mógł commitować `prices.db` z powrotem.

### 5. Test ręczny

Zakładka **Actions** → wybierz workflow "Daily price check" → **Run workflow** → **Run workflow**.

Poczekaj ~2 minuty, potem zobaczysz w logach czy scraping zadziałał. Jeśli tak — w repo pojawi się `raporty/latest.pdf` i `prices.db` z pierwszym wpisem.

---

## Setup lokalny (opcjonalnie — do testów przed pushem)

```bash
cd liofilizaty-tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Test: czy scraping w ogóle cokolwiek znajduje?
python scraper.py --dry-run --verbose

# Jeden produkt, jeden sklep:
python scraper.py --dry-run --verbose --shops skalnik --product rt_reindeer_stew

# Pełny run z zapisem do bazy:
python scraper.py --verbose

# Generuj PDF:
python report.py
open raporty/latest.pdf
```

---

## Dodawanie nowych produktów

Otwórz `config.yaml` i dopisz w sekcji `products:` kolejny blok:

```yaml
  - id: rt_pulled_pork
    name: "Real Turmat — Szarpana wieprzowina z ryżem 500g"
    brand: "Real Turmat"
    weight_g: 500
    search_terms:
      - "Real Turmat Szarpana wieprzowina 500"
      - "Real Turmat Pulled Pork"
      - "real turmat wieprzowina ryż"
```

Kluczowe pola:
- `id` — krótkie, unikalne, bez spacji (używany jako klucz w bazie)
- `search_terms` — im więcej wariantów, tym większa szansa że scraper znajdzie produkt. Skrypt testuje frazy po kolei.
- `weight_g` — opcjonalnie; jeśli podasz, PDF pokaże cenę/100g do porównania

Commit → push → następny cron odpali z nową listą.

---

## Jak się psuje i co z tym robić

### "Adapter X: 0 hitów dla '...'"

Sklep prawdopodobnie zmienił układ wyszukiwarki lub klasy CSS. Otwórz w przeglądarce URL wyszukiwarki (zobacz `SEARCH_URL` w `shops/skalnik.py` / `shops/sklep8a.py`), kliknij prawym → Zbadaj element → sprawdź klasy kafelka produktu. Dopisz je do selektorów w `_parse_tile()` albo w `search()`.

### "403 Forbidden"

Sklep zablokował User-Agenta. Zmień UA w `shops/base.py` na nowszy, ewentualnie dodaj delay (`request_delay_s = 5.0`). Skrajny przypadek — sklep wymaga JS-rendering, wtedy trzeba przerzucić się na Playwright (większy refactor; na razie zostawiamy).

### "Cena dziś jest None mimo że produkt istnieje"

Selektor `.price` nie chwycił. Na stronie kafelka mogą być dwie ceny (przed/po rabacie) — zajrzyj do HTML-a i dodaj konkretniejszy selektor.

### Wszystko zjada tyle samo czasu

Scraping jest sekwencyjny — 15 produktów × 2 sklepy × 2s rate-limit = ~60s. Można zrównoleglić (per sklep w osobnym wątku), ale to komplikuje rate-limiting i na GH Actions i tak limit czasu 15 min jest z wielkim zapasem.

---

## Struktura projektu

```
liofilizaty-tracker/
├── .github/workflows/daily.yml   Cron GitHub Actions (07:00 i 08:00 UTC)
├── config.yaml                   Produkty + sklepy + parametry raportu
├── requirements.txt              requests, bs4, lxml, yaml, matplotlib, reportlab
├── scraper.py                    Orkiestracja: config → adaptery → DB
├── storage.py                    SQLite: upsert per dzień, odczyt historii
├── report.py                     PDF: wykres + tabela + alerty okazji
├── shops/
│   ├── __init__.py               Rejestr adapterów
│   ├── base.py                   HTTP + retry + rate limit + parse_price_pln()
│   ├── skalnik.py                Adapter Skalnik.pl
│   └── sklep8a.py                Adapter 8a.pl
├── .gitignore
├── prices.db                     (tworzony przy pierwszym runie)
└── raporty/
    ├── YYYY-MM-DD.pdf            Raporty dzienne
    └── latest.pdf                Kopia najnowszego
```

---

## Plan — faza 2

Po pierwszym tygodniu, gdy potwierdzimy że Skalnik + 8a działają stabilnie:

1. `shops/wgl.py` — WGL.pl
2. `shops/sportano.py` — Sportano
3. `shops/sewel.py` — Sewel
4. `shops/turmat_store.py` — turmat.store (producent; ceny referencyjne)
5. `shops/camping4.py` — 4Camping
6. `shops/equip.py` — Equip.pl
7. `shops/militaria.py` — Militaria.pl

Dla każdego: ~40-60 linii (klon adaptera Skalnika z nowym URL-em i selektorami), plus wpis w `shops/__init__.py` i odblokowanie w `config.yaml`.

---

## Uwagi prawne

Scraping w celu osobistego porównywania cen raz dziennie, z rozsądnym rate-limitem, jest generalnie akceptowalny. Część regulaminów sklepów formalnie tego zabrania, ale ryzyko realne przy takim wolumenie jest znikome. Nie redystrybuuj danych ani PDF-ów publicznie — trzymaj repo jako **Private**.
