#!/usr/bin/env python3
"""EnkiFlux : collecte les articles récents avec l'API Anthropic (recherche web) et réécrit data.json.

Variables d'environnement :
  ANTHROPIC_API_KEY  (obligatoire) clé d'API, stockée comme secret du dépôt
  ANTHROPIC_MODEL    (optionnel) modèle à utiliser, par défaut claude-sonnet-5-5
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

API = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-5-5"
DATA_PATH = "data.json"
TODAY = datetime.now(ZoneInfo("America/Toronto")).date()
MAX_AGE_DAYS = 10
MIN_TOTAL_ITEMS = 10  # sécurité : en dessous, on ne touche pas au site

TOPICS = {
    "securite": {
        "label": "Sécurité",
        "focus": "vulnérabilités activement exploitées, correctifs d'urgence, incidents et rançongiciels touchant des produits d'entreprise, avis du Centre canadien pour la cybersécurité et du CERT-FR",
        "domains": ["thehackernews.com", "bleepingcomputer.com", "securityweek.com", "krebsonsecurity.com", "therecord.media", "cyber.gc.ca", "cert.ssi.gouv.fr", "lemagit.fr"],
    },
    "cloud": {
        "label": "Cloud",
        "focus": "annonces AWS, Azure et Google Cloud, multicloud, Kubernetes et cloud native, architecture, coûts",
        "domains": ["aws.amazon.com", "azure.microsoft.com", "cloud.google.com", "cncf.io", "infoq.com", "thenewstack.io"],
    },
    "ia": {
        "label": "IA",
        "focus": "agents IA, modèles, gouvernance et sécurité de l'IA, coût et retour sur investissement de l'IA en entreprise",
        "domains": ["technologyreview.com", "theregister.com", "anthropic.com", "openai.com", "deepmind.google", "techcrunch.com"],
    },
    "ti": {
        "label": "TI",
        "focus": "infrastructure, centres de données et capacité, exploitation, plateformes d'entreprise, transport collectif (UITP)",
        "domains": ["theregister.com", "thenewstack.io", "infoq.com", "lemagit.fr", "uitp.org"],
    },
    "finance": {
        "label": "Finance et politique",
        "focus": "dépenses d'investissement (capex) et résultats des hyperscalers, financement et prix des centres de données, lois et régulation (projet de loi C-8, Loi 25, AI Act, NIS2, régulation américaine de l'IA), souveraineté numérique du Canada et du Québec, Hydro-Québec et tarifs des centres de données",
        "domains": ["techcrunch.com", "datacenterdynamics.com", "theregister.com", "lesaffaires.com", "ledevoir.com", "lapresse.ca", "betakit.com", "cbc.ca", "parl.ca", "euractiv.com"],
    },
}
KINDS = "Urgent, Menace, Correctif, Fin de vie, Annonce, Synthèse, Analyse, Recherche, Économie, Investissement, Politique, Réglementation, Souveraineté, Gouvernance, Capacité, Risque, Événement"

PROMPT = """Nous sommes le {today}. Tu alimentes EnkiFlux, un journal de veille pour un architecte cloud et TI chez GIRO (Montréal, logiciels de transport collectif).

Rubrique : {label}. Sujets : {focus}.

Utilise la recherche web pour trouver 6 à 10 articles publiés dans les 7 derniers jours (jamais plus de 10 jours). Règles strictes :
- L'URL est celle d'un article précis (jamais une page d'accueil, de tag ou de catégorie), copiée exactement d'un résultat de recherche, sur un des domaines autorisés.
- La date "d" est au format AAAA-MM-JJ, déduite de l'URL ou de la page. Si seul le mois est certain, écris AAAA-MM. Si tu ne peux pas dater l'article, écarte-le.
- "t" : titre traduit en français, fidèle à l'original.
- "x" : une phrase en français sur ce que cela change pour un architecte cloud et TI, sans inventer de détail absent de la page.
- "s" : nom de la source (ex. The Hacker News).
- "k" : un seul mot ou groupe de mots parmi : {kinds}. N'utilise "Urgent" que pour une faille activement exploitée ou un correctif d'urgence touchant des produits d'entreprise courants.
- "i" : importance pour un architecte cloud et TI, entier de 1 à 5, barème strict : 5 = faille activement exploitée, panne majeure, loi ou décision réglementaire adoptée, investissement ou acquisition de plus de 1 G$ ; 4 = annonce majeure d'un grand fournisseur (AWS, Microsoft, Google), correctif critique, changement de prix ou de politique important ; 3 = article utile mais courant ; 2 = secondaire ; 1 = anecdotique. Réserve 4 et 5 à au plus 2 articles de la rubrique.

Réponds UNIQUEMENT par un tableau JSON, sans texte autour ni balises de code :
[{{"t":"...","u":"https://...","s":"...","d":"AAAA-MM-JJ","k":"...","x":"...","i":3}}]"""


def call_api(body):
    data = json.dumps(body).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
    }
    for attempt in range(5):
        req = urllib.request.Request(API, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            if e.code in (429, 500, 502, 503, 529) and attempt < 4:
                wait = 20 * (attempt + 1)
                print(f"  API {e.code}, nouvel essai dans {wait} s", flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(f"API {e.code}: {detail}")
        except urllib.error.URLError as e:
            if attempt < 4:
                time.sleep(10 * (attempt + 1))
                continue
            raise RuntimeError(f"Réseau: {e}")


def ask_topic(tid, cfg):
    prompt = PROMPT.format(today=TODAY.isoformat(), label=cfg["label"], focus=cfg["focus"], kinds=KINDS)
    messages = [{"role": "user", "content": prompt}]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 8, "allowed_domains": cfg["domains"]}]
    text = ""
    for _ in range(4):  # gère pause_turn
        try:
            resp = call_api({"model": MODEL, "max_tokens": 6000, "tools": tools, "messages": messages})
        except RuntimeError as e:
            # domaine inaccessible au robot : on le retire de la liste et on réessaie
            m = re.search(r"not accessible to our user agent: \[([^\]]*)\]", str(e))
            bad = re.findall(r"'([^']+)'", m.group(1)) if m else []
            rest = [d for d in tools[0]["allowed_domains"] if d not in bad]
            if not bad or not rest:
                raise
            print(f"[{tid}] domaines retirés (inaccessibles): {bad}")
            tools[0]["allowed_domains"] = rest
            cfg = {**cfg, "domains": rest}
            resp = call_api({"model": MODEL, "max_tokens": 6000, "tools": tools, "messages": messages})
        text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
        if resp.get("stop_reason") == "pause_turn":
            messages = [messages[0], {"role": "assistant", "content": resp["content"]}]
            continue
        break
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        raise ValueError("pas de tableau JSON dans la réponse")
    return json.loads(text[start:end + 1])


def valid_item(it, domains):
    try:
        for k in ("t", "u", "s", "d", "x"):
            if not isinstance(it.get(k), str) or not it[k].strip():
                return None
        u = urlparse(it["u"])
        host = (u.hostname or "").lower()
        if u.scheme != "https" or not any(host == d or host.endswith("." + d) for d in domains):
            return None
        if len(u.path.strip("/")) < 8:  # page d'accueil ou de catégorie
            return None
        d = it["d"].strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            day = datetime.strptime(d, "%Y-%m-%d").date()
            if day > TODAY or (TODAY - day).days > MAX_AGE_DAYS:
                return None
        elif re.fullmatch(r"\d{4}-\d{2}", d):
            first = TODAY.replace(day=1)
            prev = (first - timedelta(days=1)).strftime("%Y-%m")
            if d not in (TODAY.strftime("%Y-%m"), prev):
                return None
        else:
            return None
        try:
            imp = int(it.get("i", 3))
        except (TypeError, ValueError):
            imp = 3
        return {"t": it["t"].strip(), "u": it["u"].strip(), "s": it["s"].strip(), "d": d,
                "k": str(it.get("k", "")).strip(), "x": it["x"].strip(), "_i": max(1, min(5, imp))}
    except Exception:
        return None


def old_items_still_fresh(items):
    keep = []
    for it in items:
        d = it.get("d", "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            if (TODAY - datetime.strptime(d, "%Y-%m-%d").date()).days <= MAX_AGE_DAYS:
                keep.append({k: v for k, v in it.items() if k not in ("top", "une")})
    return keep


def rank(topics_items):
    """Attribue top (à la une, 6 max, 2 par rubrique max) et une (vedette de chaque rubrique)."""
    for items in topics_items.values():
        for it in items:
            if it.get("k") == "Urgent":
                it["_i"] = 5
    key = lambda p: (p[1].get("_i", 3), p[1]["d"] if len(p[1]["d"]) == 10 else p[1]["d"] + "-00")
    pool = [(tid, it) for tid, items in topics_items.items() for it in items]
    pool.sort(key=key, reverse=True)
    # seuls les articles très importants (4-5) vont à la une ; on complète à 3 au minimum
    chosen, per = [], {}
    for tid, it in pool:
        if len(chosen) >= 6:
            break
        if it.get("_i", 3) >= 4 and per.get(tid, 0) < 2:
            chosen.append((tid, it)); per[tid] = per.get(tid, 0) + 1
    if len(chosen) < 3:
        for tid, it in sorted(pool, key=lambda p: p[1]["d"] if len(p[1]["d"]) == 10 else p[1]["d"] + "-00", reverse=True):
            if len(chosen) >= 3:
                break
            if (tid, it) not in chosen and per.get(tid, 0) < 2:
                chosen.append((tid, it)); per[tid] = per.get(tid, 0) + 1
    chosen.sort(key=key, reverse=True)
    for n, (tid, it) in enumerate(chosen, 1):
        it["top"] = n
    for tid, items in topics_items.items():
        cands = [it for it in items if "top" not in it] or items
        if cands:
            best = max(cands, key=lambda it: (it.get("_i", 3), it["d"] if len(it["d"]) == 10 else it["d"] + "-00"))
            best["une"] = True


def j(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def write_data(data):
    out = '{\n "updated": %s,\n "topics": [\n' % j(data["updated"])
    parts = []
    for t in data["topics"]:
        items = []
        for it in t["items"]:
            o = {k: it[k] for k in ("t", "u", "s", "d", "k", "x") if k in it}
            if "top" in it:
                o["top"] = it["top"]
            if it.get("une"):
                o["une"] = True
            items.append(j(o))
        parts.append('  {"id":%s,"label":%s,"color":%s,"count":%s,\n   "sources":[\n    %s\n   ],\n   "items":[\n    %s\n   ]}' % (
            j(t["id"]), j(t["label"]), j(t["color"]), j(t["count"]),
            ",\n    ".join(j(s) for s in t["sources"]), ",\n    ".join(items)))
    out += ",\n".join(parts) + "\n ]\n}\n"
    json.loads(out)  # contrôle
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        f.write(out)


def main():
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    new_items, failures = {}, []
    for t in data["topics"]:
        cfg = TOPICS.get(t["id"])
        if not cfg:
            new_items[t["id"]] = old_items_still_fresh(t["items"])
            continue
        print(f"[{t['id']}] recherche…", flush=True)
        try:
            raw = None
            for attempt in (1, 2):  # un 2e essai si la réponse est inutilisable
                try:
                    raw = ask_topic(t["id"], cfg)
                    break
                except Exception as e1:
                    print(f"[{t['id']}] essai {attempt} raté : {e1}", flush=True)
                    if attempt == 2:
                        raise
                    time.sleep(10)
            seen, items = set(), []
            for it in raw:
                if not isinstance(it, dict):
                    continue
                v = valid_item(it, cfg["domains"])
                if v and v["u"] not in seen:
                    seen.add(v["u"])
                    items.append(v)
            items = items[:9]
            print(f"[{t['id']}] {len(items)} articles valides sur {len(raw)}", flush=True)
        except Exception as e:
            print(f"[{t['id']}] ÉCHEC : {e}", flush=True)
            failures.append(t["id"])
            items = []
        if not items:
            items = old_items_still_fresh(t["items"])
            for it in items:
                it["_i"] = 3
            print(f"[{t['id']}] on garde {len(items)} anciens articles encore récents", flush=True)
        new_items[t["id"]] = items
    total = sum(len(v) for v in new_items.values())
    if failures:
        print(f"Rubriques en échec (anciens articles conservés) : {', '.join(failures)}", flush=True)
    if total < MIN_TOTAL_ITEMS:
        print(f"Trop peu de résultats ({total} articles) : data.json non modifié.", flush=True)
        sys.exit(1)
    rank(new_items)
    for t in data["topics"]:
        t["items"] = [{k: v for k, v in it.items() if k != "_i"} for it in new_items[t["id"]]]
    data["updated"] = TODAY.isoformat()
    write_data(data)
    print(f"data.json mis à jour : {total} articles.", flush=True)


if __name__ == "__main__":
    main()
