#!/usr/bin/env python3
"""EnkiFlux : collecte les articles récents avec l'API Anthropic (recherche web) et réécrit data.json.

Fichiers :
  data.json     articles du jour (items), avec leur importance "i"
  archive.json  articles sortis de la sélection, par rubrique ; ne fait que grandir

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
ARCHIVE_PATH = "archive.json"
TODAY = datetime.now(ZoneInfo("America/Toronto")).date()
MAX_AGE_DAYS = 10
MIN_TOTAL_ITEMS = 10  # sécurité : en dessous, on ne touche pas au site (archives non comptées)
MAX_ITEMS_PER_TOPIC = 15
MAX_SEARCHES = 10  # plafond de recherches web par rubrique
MAX_TOKENS = 8500
# web_search_20260209 filtre les résultats avant de les passer au modèle (moins de tokens d'entrée) ;
# repli automatique sur la version de base si le modèle ne la prend pas en charge.
SEARCH_TOOL_TYPES = ["web_search_20260209", "web_search_20250305"]
ITEM_KEYS = ("t", "u", "s", "d", "k", "x")
# Tarifs en $ par million de tokens (Claude Sonnet 5.5) et par recherche web, pour estimer le coût dans le journal.
PRICE_IN, PRICE_OUT, PRICE_CACHE_READ, PRICE_CACHE_WRITE, PRICE_SEARCH = 2.00, 10.00, 0.10, 2.50, 0.01
USAGE = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "web_search_requests": 0}

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

Utilise la recherche web pour trouver tous les articles pertinents des 7 derniers jours (jamais plus de 10 jours), 15 au maximum, en privilégiant les plus récents et les plus importants. Fais des recherches ciblées (une par sujet), sans répéter une recherche déjà faite, et arrête-toi dès que tu as assez d'articles.
{known}Règles strictes :
- L'URL est celle d'un article précis (jamais une page d'accueil, de tag ou de catégorie), copiée exactement d'un résultat de recherche, sur un des domaines autorisés.
- La date "d" est au format AAAA-MM-JJ, déduite de l'URL ou de la page. Si seul le mois est certain, écris AAAA-MM. Si tu ne peux pas dater l'article, écarte-le.
- "t" : titre traduit en français, fidèle à l'original.
- "x" : une seule phrase courte (30 mots au plus) en français sur ce que cela change pour un architecte cloud et TI, sans inventer de détail absent de la page.
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


def known_block(known, since):
    """Partie du prompt qui évite de rechercher et de réécrire ce qu'on a déjà."""
    if not known:
        return ""
    return ("Dernière collecte : le {since}. Ces articles sont déjà connus : ne les renvoie pas et ne recherche "
            "que ce qui est paru depuis (ou ce qui manque) :\n{urls}\nS'il n'y a rien de nouveau, réponds [].\n"
            ).format(since=since, urls="\n".join(known))


def add_usage(resp):
    u = resp.get("usage") or {}
    for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        USAGE[k] += u.get(k) or 0
    USAGE["web_search_requests"] += (u.get("server_tool_use") or {}).get("web_search_requests") or 0


def usage_cost():
    return (USAGE["input_tokens"] * PRICE_IN + USAGE["output_tokens"] * PRICE_OUT
            + USAGE["cache_read_input_tokens"] * PRICE_CACHE_READ
            + USAGE["cache_creation_input_tokens"] * PRICE_CACHE_WRITE) / 1e6 + USAGE["web_search_requests"] * PRICE_SEARCH


def ask_topic(tid, cfg, known=(), since=""):
    prompt = PROMPT.format(today=TODAY.isoformat(), label=cfg["label"], focus=cfg["focus"], kinds=KINDS,
                           known=known_block(known, since))
    messages = [{"role": "user", "content": prompt}]
    tools = [{"type": SEARCH_TOOL_TYPES[0], "name": "web_search", "max_uses": MAX_SEARCHES, "allowed_domains": list(cfg["domains"])}]
    text = ""
    for _ in range(4):  # gère pause_turn
        resp = None
        for _retry in range(3):  # corrections de configuration de l'outil
            try:
                resp = call_api({"model": MODEL, "max_tokens": MAX_TOKENS, "tools": tools, "messages": messages})
                break
            except RuntimeError as e:
                msg = str(e)
                # modèle trop ancien pour le filtrage dynamique : on passe à la version de base
                if "API 400" in msg and tools[0]["type"] in msg and tools[0]["type"] != SEARCH_TOOL_TYPES[-1]:
                    print(f"[{tid}] {tools[0]['type']} refusé, repli sur {SEARCH_TOOL_TYPES[-1]}", flush=True)
                    tools[0]["type"] = SEARCH_TOOL_TYPES[-1]
                    continue
                # domaine inaccessible au robot : on le retire de la liste et on réessaie
                m = re.search(r"not accessible to our user agent: \[([^\]]*)\]", msg)
                bad = re.findall(r"'([^']+)'", m.group(1)) if m else []
                rest = [d for d in tools[0]["allowed_domains"] if d not in bad]
                if not bad or not rest:
                    raise
                print(f"[{tid}] domaines retirés (inaccessibles): {bad}", flush=True)
                tools[0]["allowed_domains"] = rest
        if resp is None:
            raise RuntimeError("configuration de l'outil de recherche refusée")
        add_usage(resp)
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
    """Anciens articles datés au jour et de 10 jours au plus, avec leur importance (3 si inconnue)."""
    keep = []
    for it in items:
        d = it.get("d", "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            if (TODAY - datetime.strptime(d, "%Y-%m-%d").date()).days <= MAX_AGE_DAYS:
                o = clean(it)
                try:
                    o["_i"] = max(1, min(5, int(it.get("i", 3))))
                except (TypeError, ValueError):
                    o["_i"] = 3
                keep.append(o)
    return keep


def date_key(d):
    return d if len(d) == 10 else d + "-00"


def clean(it):
    """Article réduit à ses champs de base (sans top, une ni _i)."""
    return {k: it[k] for k in ITEM_KEYS if k in it}


def archive_dropped(old_items, archive, kept_items):
    """Déplace dans l'archive les anciens articles qui ne sont plus dans items.

    L'archive ne fait que grandir : rien n'en est retiré, pas de doublon (clé : URL "u").
    Elle est rangée du plus récent au moins récent.
    """
    kept = {it["u"] for it in kept_items}
    out, seen = [], set()
    for it in list(archive) + [it for it in old_items if it.get("u") not in kept]:
        u = it.get("u")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(clean(it))
    out.sort(key=lambda it: date_key(it.get("d", "")), reverse=True)
    return out


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
            o = clean(it)
            if "i" in it:
                o["i"] = it["i"]
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


def load_archive(data):
    """Archive par rubrique : archive.json, plus une éventuelle clé "archive" restée dans un ancien data.json."""
    arch = {}
    try:
        with open(ARCHIVE_PATH, encoding="utf-8") as f:
            arch = json.load(f).get("topics", {})
    except FileNotFoundError:
        pass
    for t in data["topics"]:
        if "archive" in t:
            arch[t["id"]] = list(arch.get(t["id"], [])) + t.pop("archive")
    return arch


def write_archive(updated, arch):
    parts = []
    for tid, items in arch.items():
        parts.append('  %s:[\n    %s\n  ]' % (j(tid), ",\n    ".join(j(clean(it)) for it in items)))
    out = '{\n "updated": %s,\n "topics": {\n%s\n }\n}\n' % (j(updated), ",\n".join(parts))
    json.loads(out)  # contrôle
    with open(ARCHIVE_PATH, "w", encoding="utf-8") as f:
        f.write(out)


def collect(tid, cfg, known, since):
    """Nouveaux articles valides d'une rubrique ; lève une exception si la collecte échoue."""
    raw = None
    for attempt in (1, 2):  # un 2e essai si la réponse est inutilisable
        try:
            raw = ask_topic(tid, cfg, known, since)
            break
        except Exception as e1:
            print(f"[{tid}] essai {attempt} raté : {e1}", flush=True)
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
    print(f"[{tid}] {len(items)} nouveaux articles valides sur {len(raw)}", flush=True)
    return items


def main():
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    archive = load_archive(data)
    since = data.get("updated") or ""
    new_items, failures = {}, []
    for t in data["topics"]:
        fresh = old_items_still_fresh(t["items"])
        cfg = TOPICS.get(t["id"])
        found = []
        if cfg:
            print(f"[{t['id']}] recherche ({len(fresh)} articles déjà connus)…", flush=True)
            try:
                found = collect(t["id"], cfg, [it["u"] for it in fresh], since)
            except Exception as e:
                print(f"[{t['id']}] ÉCHEC : {e} (anciens articles encore récents conservés)", flush=True)
                failures.append(t["id"])
        # nouveaux + anciens encore récents ; les plus récents d'abord, puis les plus importants à date égale
        urls = {it["u"] for it in found}
        items = found + [it for it in fresh if it["u"] not in urls]
        items.sort(key=lambda it: (date_key(it["d"]), it["_i"]), reverse=True)
        new_items[t["id"]] = items[:MAX_ITEMS_PER_TOPIC]
    total = sum(len(v) for v in new_items.values())  # archives exclues
    if failures:
        print(f"Rubriques en échec : {', '.join(failures)}", flush=True)
    print(f"Consommation : {USAGE['input_tokens']} tokens d'entrée, {USAGE['output_tokens']} de sortie, "
          f"{USAGE['cache_read_input_tokens']} lus en cache, {USAGE['web_search_requests']} recherches, "
          f"coût estimé {usage_cost():.2f} $", flush=True)
    if total < MIN_TOTAL_ITEMS:
        print(f"Trop peu de résultats ({total} articles) : data.json non modifié.", flush=True)
        sys.exit(1)
    rank(new_items)
    for t in data["topics"]:
        items = [{**{k: v for k, v in it.items() if k != "_i"}, "i": it.get("_i", 3)} for it in new_items[t["id"]]]
        archive[t["id"]] = archive_dropped(t.get("items", []), archive.get(t["id"], []), items)
        t["items"] = items
    data["updated"] = TODAY.isoformat()
    write_data(data)
    write_archive(data["updated"], archive)
    print(f"data.json mis à jour : {total} articles ; archive.json : {sum(map(len, archive.values()))} articles.", flush=True)


if __name__ == "__main__":
    main()
