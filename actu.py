"""
Journal du brief : récupère les actus publiques par thème et écrit actu.json.
Lancé toutes les 30 min par GitHub Actions ; la page index.html le lit.
Aucune donnée personnelle ici : uniquement des flux RSS publics et des cours de bourse.
"""
import datetime as dt
import email.utils
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import requests

UA = {"User-Agent": "Mozilla/5.0 (brief du matin; usage perso)"}

THEMES = {
    "une": {"titre": "À la une", "emoji": "🌍", "max": 6, "sources": [
        ("franceinfo", "https://www.franceinfo.fr/titres.rss"),
        ("Le Monde", "https://www.lemonde.fr/rss/une.xml"),
        ("France 24", "https://www.france24.com/fr/rss"),
    ]},
    "marche": {"titre": "Le marché", "emoji": "📈", "max": 5, "sources": [
        ("BFM Bourse", "https://www.tradingsat.com/rssbourse.xml"),
        ("franceinfo éco", "https://www.franceinfo.fr/economie.rss"),
    ]},
    "anime": {"titre": "Animés & mangas", "emoji": "🎌", "max": 5, "sources": [
        ("Crunchyroll", "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/fr-FR/rss"),
        ("Adala News", "https://adala-news.fr/feed/"),
    ]},
    "jv": {"titre": "Jeux vidéo", "emoji": "🎮", "max": 5, "sources": [
        ("jeuxvideo.com", "https://www.jeuxvideo.com/rss/rss.xml"),
        ("Gameblog", "https://www.gameblog.fr/rss.php"),
        ("Gamekult", "https://www.gamekult.com/feed.xml"),
    ]},
}

# cours affichés pour le thème « marché » (simple information, pas un conseil)
COURS = [("CAC 40", "^FCHI"), ("S&P 500", "^GSPC"), ("Bitcoin €", "BTC-EUR"), ("€/$", "EURUSD=X")]

NS = {"media": "http://search.yahoo.com/mrss/", "content": "http://purl.org/rss/1.0/modules/content/"}


def propre(texte, n=220):
    t = html.unescape(re.sub(r"<[^>]+>", " ", texte or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[:n - 1].rsplit(" ", 1)[0] + "…"


def date_iso(texte):
    try:
        return email.utils.parsedate_to_datetime(texte).astimezone(dt.timezone.utc).isoformat()
    except Exception:
        try:
            return dt.datetime.fromisoformat(texte.replace("Z", "+00:00")).isoformat()
        except Exception:
            return ""


def image(item):
    for chemin in ("media:content", "media:thumbnail"):
        el = item.find(chemin, NS)
        if el is not None and el.get("url"):
            return el.get("url")
    enc = item.find("enclosure")
    if enc is not None and (enc.get("type") or "").startswith("image"):
        return enc.get("url")
    m = re.search(r'<img[^>]+src="([^"]+)"', item.findtext("description") or "")
    return m.group(1) if m else ""


def lire_flux(source, url):
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        racine = ET.fromstring(r.content)
    except Exception as e:
        print(f"⚠️ {source} : {type(e).__name__} {str(e)[:80]}", file=sys.stderr)
        return []
    articles = []
    for item in racine.iter("item"):
        titre = propre(item.findtext("title"), 200)
        if not titre or re.match(r"(GUIDE|SOLUCE|ASTUCE|TUTO|BON PLAN|CODE PROMO)\b", titre, re.I):
            continue  # pas des infos : on saute guides et promos
        articles.append({
            "titre": titre,
            "resume": propre(item.findtext("description"), 220),
            "lien": (item.findtext("link") or "").strip(),
            "date": date_iso(item.findtext("pubDate") or ""),
            "image": image(item),
            "source": source,
        })
    return articles[:10]


def cours():
    resultat = []
    for nom, symbole in COURS:
        try:
            m = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbole}",
                             params={"range": "1d", "interval": "1d"}, headers=UA,
                             timeout=15).json()["chart"]["result"][0]["meta"]
            prix = m["regularMarketPrice"]
            veille = m.get("chartPreviousClose") or m.get("previousClose")
            resultat.append({"nom": nom, "valeur": round(prix, 4 if prix < 10 else 2),
                             "variation": round((prix - veille) / veille * 100, 2) if veille else None})
        except Exception as e:
            print(f"⚠️ cours {nom} : {e}", file=sys.stderr)
    return resultat


def melanger(listes, maximum):
    """Alterne les sources (1er de chaque, puis 2e…) pour varier, comme un JT."""
    resultat, vus = [], set()
    for rang in range(10):
        for liste in listes:
            if rang < len(liste):
                a = liste[rang]
                cle = a["titre"].lower()[:60]
                if cle not in vus:
                    vus.add(cle)
                    resultat.append(a)
    return resultat[:maximum]


def main():
    taches = [(t, s, u) for t, conf in THEMES.items() for s, u in conf["sources"]]
    with ThreadPoolExecutor(8) as pool:
        flux = list(pool.map(lambda x: (x[0], lire_flux(x[1], x[2])), taches))
    themes = {}
    for cle, conf in THEMES.items():
        listes = [articles for t, articles in flux if t == cle]
        themes[cle] = {"titre": conf["titre"], "emoji": conf["emoji"],
                       "articles": melanger(listes, conf["max"])}
    sortie = {"maj": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              "cours": cours(), "themes": themes}
    with open("actu.json", "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False, separators=(",", ":"))
    print("✅ actu.json :", {k: len(v["articles"]) for k, v in themes.items()},
          "| cours :", len(sortie["cours"]))


if __name__ == "__main__":
    main()
