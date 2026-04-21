#!/usr/bin/env python3
"""
report.py — generuje PDF z wykresami cen i tabelą 'najtaniej dziś'.

Użycie:
    python report.py                           # zapisuje raporty/YYYY-MM-DD.pdf
    python report.py --out /tmp/raport.pdf     # własna ścieżka
    python report.py --date 2026-04-20         # raport za wybraną datę

Raport zawiera:
  1. Nagłówek z datą.
  2. Dla każdego produktu:
       - panel z wykresem liniowym (15 dni, jedna linia per sklep)
       - obok panel "Dziś" z tabelką sklep → cena, pogrubiony najtańszy
       - oznaczenie 🔥 OKAZJA jeśli cena dziś < 90% średniej 7-dniowej
  3. Stronę podsumowującą: top 5 największych spadków cen.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import logging
import statistics
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")   # bez serwera X
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

# matplotlib ma DejaVu Sans w standardzie — to obsługuje polskie znaki
matplotlib.rcParams["font.family"] = "DejaVu Sans"
matplotlib.rcParams["axes.unicode_minus"] = False
import yaml
from matplotlib.ticker import MaxNLocator
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from storage import PriceDB


# ────────────────────────────────────────────────── fonty z polskimi znakami
# DejaVu Sans obsługuje polskie znaki i większość emoji. Jest domyślnie
# dostępny na Ubuntu (i na runnerach GitHub Actions) oraz na macOS przez
# Homebrew. Jeśli nie ma — fallback na Helvetica (bez polskich znaków).
_FONT_PATHS = [
    # Linux / GitHub Actions
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    # macOS (instalowane przez Homebrew jako font-dejavu)
    "/usr/local/share/fonts/DejaVuSans.ttf",
    "/Library/Fonts/DejaVuSans.ttf",
    # macOS — fallback na system
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]

def _register_fonts() -> tuple[str, str]:
    """Rejestruje font z polskimi znakami. Zwraca (regular, bold)."""
    for regular, bold in [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/local/share/fonts/DejaVuSans.ttf",
         "/usr/local/share/fonts/DejaVuSans-Bold.ttf"),
        ("/Library/Fonts/DejaVuSans.ttf",
         "/Library/Fonts/DejaVuSans-Bold.ttf"),
    ]:
        if Path(regular).exists() and Path(bold).exists():
            pdfmetrics.registerFont(TTFont("PLSans", regular))
            pdfmetrics.registerFont(TTFont("PLSans-Bold", bold))
            return "PLSans", "PLSans-Bold"
    # Fallback
    return "Helvetica", "Helvetica-Bold"


FONT_REGULAR, FONT_BOLD = _register_fonts()

ROOT = Path(__file__).parent
# Jak w scraper.py — dane można przenieść do wolumenu przez DATA_DIR
import os
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT)))
CONFIG_PATH = ROOT / "config.yaml"
DB_PATH = DATA_DIR / "prices.db"
REPORTS_DIR = DATA_DIR / "raporty"

log = logging.getLogger("report")


# ────────────────────────────────────────────────────────── wykres per produkt
def build_price_chart(
    product_id: str,
    product_name: str,
    rows: List,            # sqlite3.Row list
    shops_config: dict,
    history_days: int,
) -> bytes:
    """Zwraca PNG jako bytes — wykres cen w czasie, jedna linia per sklep."""
    # Grupujemy po sklepie
    by_shop: Dict[str, List[tuple[dt.date, float]]] = {}
    for r in rows:
        if r["price_pln"] is None:
            continue
        d = dt.date.fromisoformat(r["date"])
        by_shop.setdefault(r["shop_id"], []).append((d, float(r["price_pln"])))

    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=110)
    today = dt.date.today()
    x_start = today - dt.timedelta(days=history_days - 1)
    x_end = today

    if not by_shop:
        ax.text(
            0.5, 0.5,
            "Brak danych — uruchamiaj codziennie, historia się zbuduje",
            ha="center", va="center", transform=ax.transAxes,
            fontsize=11, color="gray",
        )
        ax.set_xticks([]); ax.set_yticks([])
    else:
        for shop_id, points in sorted(by_shop.items()):
            points.sort()
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            color = shops_config.get(shop_id, {}).get("color", "#444444")
            display = shops_config.get(shop_id, {}).get("display_name", shop_id)
            ax.plot(xs, ys, marker="o", linewidth=2, markersize=5,
                    color=color, label=display)

        ax.set_xlim(x_start, x_end)
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, history_days // 7)))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        ax.yaxis.set_major_locator(MaxNLocator(integer=False, nbins=6))
        ax.set_ylabel("Cena (zł)", fontsize=10)
        ax.grid(True, linestyle="--", alpha=0.35)
        ax.legend(loc="best", fontsize=9, frameon=True)

    ax.set_title(product_name, fontsize=12, fontweight="bold", pad=10)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


# ───────────────────────────────────────────────────── analiza "dziś" + okazja
def analyze_today(
    rows: List,
    shops_config: dict,
    today: dt.date,
    deal_threshold_pct: float,
) -> dict:
    """
    Zwraca słownik:
        today_by_shop:   shop_id → (price, available, url)
        cheapest_shop:   najtańszy sklep dziś (lub None)
        cheapest_price:  cena najtańszego (lub None)
        is_deal:         True jeśli najtańsza cena < (1 - threshold) * średnia_7d
        avg_7d:          średnia 7-dniowa najtańszych cen (albo None)
    """
    # Dziś per sklep
    today_by_shop: Dict[str, dict] = {}
    for r in rows:
        if dt.date.fromisoformat(r["date"]) == today and r["price_pln"] is not None:
            today_by_shop[r["shop_id"]] = {
                "price": float(r["price_pln"]),
                "available": bool(r["available"]),
                "url": r["product_url"],
                "title": r["product_title"],
            }

    # Najtańszy dziś wśród dostępnych (jak nie ma dostępnych — wśród wszystkich)
    cheapest_shop = None
    cheapest_price = None
    pool = {s: d for s, d in today_by_shop.items() if d["available"]}
    if not pool:
        pool = today_by_shop
    if pool:
        cheapest_shop = min(pool, key=lambda s: pool[s]["price"])
        cheapest_price = pool[cheapest_shop]["price"]

    # Średnia z ostatnich 7 dni najtańszych dziennych (dostępne)
    by_date_cheapest: Dict[dt.date, float] = {}
    for r in rows:
        if r["price_pln"] is None or not r["available"]:
            continue
        d = dt.date.fromisoformat(r["date"])
        if d == today:
            continue  # nie liczymy dzisiaj do średniej
        cur = by_date_cheapest.get(d)
        p = float(r["price_pln"])
        if cur is None or p < cur:
            by_date_cheapest[d] = p

    recent_7 = [
        p for d, p in by_date_cheapest.items()
        if d >= today - dt.timedelta(days=7)
    ]
    avg_7d = statistics.mean(recent_7) if recent_7 else None

    is_deal = False
    if avg_7d is not None and cheapest_price is not None:
        threshold = avg_7d * (1 - deal_threshold_pct / 100)
        is_deal = cheapest_price < threshold

    return {
        "today_by_shop": today_by_shop,
        "cheapest_shop": cheapest_shop,
        "cheapest_price": cheapest_price,
        "is_deal": is_deal,
        "avg_7d": avg_7d,
    }


# ──────────────────────────────────────────────────────────────────── PDF
def build_pdf(
    out_path: Path,
    cfg: dict,
    db: PriceDB,
    today: dt.date,
) -> None:
    history_days = int(cfg["report"]["history_days"])
    deal_threshold = float(cfg["report"]["deal_threshold_pct"])
    shops_config = cfg["shops"]

    styles = getSampleStyleSheet()
    # Podmień domyślny font na nasz (z polskimi znakami)
    for sn in ("Heading1", "Heading2", "BodyText", "Normal"):
        styles[sn].fontName = FONT_REGULAR
    h1 = styles["Heading1"]; h1.fontSize = 18; h1.spaceAfter = 8
    h1.fontName = FONT_BOLD
    h2 = ParagraphStyle("h2-tight", parent=styles["Heading2"],
                        fontSize=13, spaceAfter=4, spaceBefore=12,
                        fontName=FONT_BOLD)
    body = styles["BodyText"]; body.fontSize = 9
    small = ParagraphStyle("small", parent=body, fontSize=8,
                           textColor=colors.grey, fontName=FONT_REGULAR)

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title=f"Raport liofilizatów {today.isoformat()}",
        author="liofilizaty-tracker",
    )

    story = []
    story.append(Paragraph(
        f"Raport cen liofilizatów — {today.strftime('%d.%m.%Y')}", h1,
    ))
    story.append(Paragraph(
        f"Historia: ostatnie {history_days} dni. "
        f"Progiem okazji jest spadek o ≥ {deal_threshold:.0f}% "
        f"poniżej średniej z ostatnich 7 dni.",
        small,
    ))
    story.append(Spacer(1, 0.4 * cm))

    # Do strony podsumowującej
    deals: list[tuple[str, str, float, float]] = []  # (prod_id, shop, price, diff_pct)

    for prod in cfg["products"]:
        pid = prod["id"]
        name = prod["name"]

        rows = db.history(pid, history_days, today=today)
        analysis = analyze_today(rows, shops_config, today, deal_threshold)

        story.append(Paragraph(name, h2))

        # Wykres
        png_bytes = build_price_chart(pid, name, rows, shops_config, history_days)
        img = Image(io.BytesIO(png_bytes), width=17 * cm, height=7.2 * cm)
        story.append(img)

        # Tabela "Dziś":
        tbl_data = [["Sklep", "Cena dziś", "Dostępność", "Cena / 100 g"]]
        weight_g = prod.get("weight_g")
        sorted_shops = sorted(
            analysis["today_by_shop"].items(),
            key=lambda kv: kv[1]["price"],
        )
        for shop_id, d in sorted_shops:
            display = shops_config.get(shop_id, {}).get("display_name", shop_id)
            price = d["price"]
            per_100g = (
                f"{price / weight_g * 100:.2f} zł" if weight_g else "—"
            )
            avail = "✓" if d["available"] else "zapytaj"
            is_cheapest = (shop_id == analysis["cheapest_shop"])
            marker = "  ← najtaniej" if is_cheapest else ""
            tbl_data.append([
                f"{display}{marker}",
                f"{price:.2f} zł",
                avail,
                per_100g,
            ])

        if len(tbl_data) == 1:
            tbl_data.append(["— brak odczytów na dziś —", "", "", ""])

        t = Table(tbl_data, colWidths=[5 * cm, 3.5 * cm, 3 * cm, 3.5 * cm])
        ts = TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ECEFF1")),
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ("FONTNAME", (0, 1), (-1, -1), FONT_REGULAR),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#B0BEC5")),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
        # Podświetl najtańszy wiersz
        for i, (shop_id, _d) in enumerate(sorted_shops, start=1):
            if shop_id == analysis["cheapest_shop"]:
                ts.add("BACKGROUND", (0, i), (-1, i), colors.HexColor("#E8F5E9"))
                ts.add("FONTNAME", (0, i), (-1, i), FONT_BOLD)
        t.setStyle(ts)
        story.append(t)

        # Etykieta okazji
        if analysis["is_deal"]:
            diff_pct = (analysis["avg_7d"] - analysis["cheapest_price"]) / analysis["avg_7d"] * 100
            deals.append((pid, analysis["cheapest_shop"], analysis["cheapest_price"], diff_pct))
            story.append(Spacer(1, 0.15 * cm))
            deal_style = ParagraphStyle(
                "deal", parent=body,
                fontSize=10, textColor=colors.HexColor("#D84315"),
                fontName=FONT_BOLD,
            )
            shop_name = shops_config.get(
                analysis["cheapest_shop"], {}
            ).get("display_name", analysis["cheapest_shop"])
            story.append(Paragraph(
                f"OKAZJA: {shop_name} — {analysis['cheapest_price']:.2f} zł "
                f"({diff_pct:.1f}% poniżej śr. 7-dniowej {analysis['avg_7d']:.2f} zł)",
                deal_style,
            ))

        story.append(Spacer(1, 0.4 * cm))

    # ─── Strona podsumowująca
    story.append(PageBreak())
    story.append(Paragraph("Podsumowanie dnia", h1))

    if not deals:
        story.append(Paragraph(
            "Dziś brak alertów okazji — wszystkie ceny w ramach ±10% średniej tygodniowej.",
            body,
        ))
    else:
        story.append(Paragraph("Największe spadki cen vs średnia 7-dniowa:", h2))
        deals.sort(key=lambda x: x[3], reverse=True)
        data = [["Produkt", "Sklep", "Cena", "Spadek"]]
        prod_names = {p["id"]: p["name"] for p in cfg["products"]}
        for pid, shop, price, diff in deals:
            shop_name = shops_config.get(shop, {}).get("display_name", shop)
            data.append([
                prod_names[pid],
                shop_name,
                f"{price:.2f} zł",
                f"-{diff:.1f}%",
            ])
        t = Table(data, colWidths=[7 * cm, 4 * cm, 3 * cm, 2.5 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FFCCBC")),
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ("FONTNAME", (0, 1), (-1, -1), FONT_REGULAR),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BF360C")),
            ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ]))
        story.append(t)

    story.append(Spacer(1, 0.8 * cm))
    story.append(Paragraph(
        f"Raport wygenerowany automatycznie. Baza: {DB_PATH.name}. "
        f"Źródła: {', '.join(cfg['shops'][s]['display_name'] for s in cfg['shops'] if cfg['shops'][s].get('enabled'))}.",
        small,
    ))

    doc.build(story)
    log.info("PDF zapisany: %s", out_path)


# ────────────────────────────────────────────────────────────────────── main
def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    ap = argparse.ArgumentParser(description="Generator raportu PDF")
    ap.add_argument("--out", type=Path, default=None,
                    help="Ścieżka wyjściowa. Domyślnie raporty/YYYY-MM-DD.pdf")
    ap.add_argument("--date", default=None,
                    help="Data raportu (YYYY-MM-DD), domyślnie dziś")
    args = ap.parse_args()

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    out = args.out or (REPORTS_DIR / f"{today.isoformat()}.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)

    db = PriceDB(DB_PATH)
    build_pdf(out, cfg, db, today)

    # Zawsze trzymaj też kopię jako 'latest.pdf' dla wygody
    latest = REPORTS_DIR / "latest.pdf"
    latest.write_bytes(out.read_bytes())
    log.info("Dodatkowa kopia: %s", latest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
