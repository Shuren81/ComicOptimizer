"""Fonti di ricerca online: ComicVine, MyAnimeList e ComicsBox. Nessuna dipendenza dall'interfaccia."""
import html
import json
import re
import socket
import ssl
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from .comicinfo import pulisci_numero, togli_maiuscole

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


def pulisci_html(testo):
    testo = re.sub(r"(?i)<br\s*/?>|</p>|</li>", "\n", testo)
    testo = re.sub(r"<[^>]+>", "", testo)
    testo = html.unescape(testo)
    testo = re.sub(r"\n{3,}", "\n\n", testo)
    return testo.strip()


USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) CBZInfo/1.0"


class ErroreRicerca(Exception):
    def __init__(self, messaggio, codice=None):
        super().__init__(messaggio)
        self.codice = codice


def contesto_ssl():
    # Se c'è certifi uso i suoi certificati (utile nell'AppImage), altrimenti quelli del sistema
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _testo_semplice(testo, massimo=200):
    testo = re.sub(r"<[^>]+>", " ", testo or "")
    return re.sub(r"\s+", " ", testo).strip()[:massimo]


def _messaggio_http(errore):
    # Il server di solito spiega l'errore nel corpo della risposta: lo mostro invece del solo codice
    try:
        corpo = errore.read().decode("utf-8", "replace")
    except Exception:
        return ""
    try:
        dati = json.loads(corpo)
        for chiave in ("message", "error_description", "hint", "error"):
            if isinstance(dati, dict) and dati.get(chiave):
                return str(dati[chiave])
    except ValueError:
        pass
    return _testo_semplice(corpo)


def richiesta_bytes(url, intestazioni=None, timeout=30, dati=None):
    richiesta = urllib.request.Request(
            url,
            data=dati,
            headers={"User-Agent": USER_AGENT, **(intestazioni or {})},
    )
    try:
        with urllib.request.urlopen(richiesta, timeout=timeout, context=contesto_ssl()) as risposta:
            return risposta.read()
    except urllib.error.HTTPError as e:
        dettaglio = _messaggio_http(e)
        raise ErroreRicerca(
                f"Il server ha risposto con errore HTTP {e.code}" + (f":\n{dettaglio}" if dettaglio else "."),
                codice=e.code,
        )
    except (socket.timeout, TimeoutError):
        raise ErroreRicerca(f"Il server non ha risposto entro {timeout} secondi. Riprova tra poco.")
    except urllib.error.URLError as e:
        motivo = getattr(e, "reason", e)
        if isinstance(motivo, (socket.timeout, TimeoutError)):
            raise ErroreRicerca(f"Il server non ha risposto entro {timeout} secondi. Riprova tra poco.")
        if isinstance(motivo, ssl.SSLError):
            raise ErroreRicerca(f"Errore nei certificati di sicurezza (SSL):\n{motivo}")
        raise ErroreRicerca(f"Impossibile contattare il server (controlla la connessione):\n{motivo}")


def richiesta_json(url, intestazioni=None, timeout=30, dati=None):
    corpo = richiesta_bytes(url, {"Accept": "application/json", **(intestazioni or {})}, timeout, dati)
    try:
        return json.loads(corpo.decode("utf-8"))
    except ValueError:
        raise ErroreRicerca(
                "Il server non ha risposto con dati validi (possibile blocco o manutenzione).\n"
                "Inizio della risposta: " + _testo_semplice(corpo.decode("utf-8", "replace"))
        )


def unici(elementi):
    visti = set()
    risultato = []
    for e in elementi:
        if e and e not in visti:
            visti.add(e)
            risultato.append(e)
    return risultato


def parole(testo):
    # Senza accenti e punteggiatura: "Batman: L'ultimo" e "batman - l ultimo" sono le stesse parole
    testo = unicodedata.normalize("NFKD", testo).lower()
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    return re.findall(r"[^\W_]+", testo)


def passa_filtro(filtro, etichetta):
    testo = " ".join(parole(etichetta))
    return all(parola in testo for parola in parole(filtro))


def ordina_per_parole(risultati, testo):
    """Prima chi ha più parole del nome in comune con la ricerca, poi più numeri: cercando
    "Absolute Superman 25", "Absolute Superman #24" viene prima di "Absolute Batman #25"."""
    cercate = set(parole(testo))

    def chiave(r):
        comuni = cercate & set(parole(r["etichetta"]))
        numeri = sum(p.isdigit() for p in comuni)
        return -(len(comuni) - numeri), -numeri
    return sorted(risultati, key=chiave)


def titolo_da_nome(nome):
    """Da "Batman - L'ultimo cavaliere (2020)" a "L'ultimo cavaliere": il sito non trova il nome intero."""
    nome = re.sub(r"[(\[].*?[)\]]", " ", nome.replace("_", " "))
    con_lettere = [p.strip() for p in re.split(r"\s+-\s+", nome) if re.search(r"[^\W\d_]", p)]
    return con_lettere[-1] if con_lettere else nome.strip()


def separa_numero(query):
    m = re.search(r"(?:^|\s)#?\s*(\d+)\s*$", query)
    testo = re.sub(r"\s+#?\s*\d+\s*$", "", query).strip().lower() or query.strip().lower()
    return testo, m.group(1) if m else None


def punti_pertinenza(nome, testo):
    if nome == testo:
        return 0
    if nome.startswith(testo):
        return 1
    if testo in nome:
        return 2
    return 3


# ---------------------------------------------------------------- ComicVine
CV_API = "https://comicvine.gamespot.com/api"
CV_CAMPI_RICERCA = "id,name,issue_number,cover_date,volume,image,api_detail_url"
CV_CAMPI_DETTAGLIO = "name,issue_number,cover_date,store_date,description,person_credits,character_credits,team_credits,volume"


def controlla_stato_cv(dati):
    # ComicVine risponde anche con HTTP 200 quando c'è un problema: il vero esito è in status_code
    stato = dati.get("status_code") if isinstance(dati, dict) else None
    if stato not in (None, 1):
        errore = dati.get("error") or "errore sconosciuto"
        if stato == 100:
            errore = f"la chiave API non è valida ({errore})"
        raise ErroreRicerca(f"ComicVine ha risposto: {errore}")


def _numero_ordinabile(testo):
    try:
        return float(testo)
    except (TypeError, ValueError):
        return 1e9


def cv_cerca(chiave, query):
    testo, numero_cercato = separa_numero(query)

    url = (
            f"{CV_API}/search/?api_key={urllib.parse.quote(chiave)}&format=json&resources=issue&limit=50"
            f"&field_list={CV_CAMPI_RICERCA}&query={urllib.parse.quote(query)}"
    )
    dati = richiesta_json(url, timeout=45)
    controlla_stato_cv(dati)

    risultati = []
    for item in dati.get("results") or []:
        volume = (item.get("volume") or {}).get("name") or "Senza Serie"
        numero = str(item.get("issue_number") or "")
        nome = item.get("name") or ""
        data = item.get("cover_date") or ""
        anno = data.split("-")[0] if data else ""
        immagini = item.get("image") or {}
        copertina = immagini.get("medium_url") or immagini.get("small_url") or immagini.get("thumb_url")

        nome_vol = volume.lower()
        punti = punti_pertinenza(nome_vol, testo)
        fuori_numero = 0 if (numero_cercato and numero == numero_cercato) else 1

        etichetta = f"{volume} #{numero}" + (f" - {nome}" if nome else "") + (f" ({anno})" if anno else "")
        risultati.append({
                "ordine": (punti, fuori_numero, nome_vol, _numero_ordinabile(numero)),
                "etichetta": etichetta,
                "copertina": copertina,
                "campi": {"Series": volume, "Number": numero, "Title": nome, "Year": anno},
                "grezzo": item,
        })
    risultati.sort(key=lambda r: r["ordine"])
    return risultati


def pulisci_descrizione_cv(testo):
    testo = re.split(r"(?i)<h[2-4][^>]*>\s*list of covers", testo or "")[0]
    testo = re.sub(r"(?is)<table.*?</table>", "", testo)
    return pulisci_html(testo)


def cv_dettagli(chiave, risultato):
    """Seconda richiesta, solo per l'albo scelto: autori, trama, personaggi, squadre ed editore."""
    url_albo = risultato["grezzo"].get("api_detail_url")
    if not url_albo:
        return {}
    dati = richiesta_json(
            f"{url_albo}?api_key={urllib.parse.quote(chiave)}&format=json&field_list={CV_CAMPI_DETTAGLIO}",
            timeout=45,
    )
    controlla_stato_cv(dati)
    albo = dati.get("results") or {}

    scrittori, disegnatori = [], []
    for persona in albo.get("person_credits") or []:
        ruolo = (persona.get("role") or "").lower()
        nome = persona.get("name") or ""
        if "writer" in ruolo:
            scrittori.append(nome)
        if "penciler" in ruolo or "artist" in ruolo:
            disegnatori.append(nome)

    campi = {
            "Writer": ", ".join(unici(scrittori)),
            "Penciller": ", ".join(unici(disegnatori)),
            "Summary": pulisci_descrizione_cv(albo.get("description")),
            "Characters": ", ".join(unici([c.get("name") for c in albo.get("character_credits") or []])[:25]),
            "Teams": ", ".join(unici([t.get("name") for t in albo.get("team_credits") or []])[:15]),
    }

    # L'editore sta nella collana: richiesta facoltativa, se fallisce si va avanti senza
    url_volume = (albo.get("volume") or {}).get("api_detail_url")
    if url_volume:
        try:
            d2 = richiesta_json(
                    f"{url_volume}?api_key={urllib.parse.quote(chiave)}&format=json&field_list=publisher",
                    timeout=45,
            )
            controlla_stato_cv(d2)
            campi["Publisher"] = ((d2.get("results") or {}).get("publisher") or {}).get("name") or ""
        except ErroreRicerca:
            pass
    return campi


# ---------------------------------------------------------------- MyAnimeList
MAL_API = "https://api.myanimelist.net/v2"
MAL_CAMPI = (
        "alternative_titles,start_date,synopsis,media_type,status,num_volumes,num_chapters,"
        "authors{first_name,last_name},serialization{name}"
)


def mal_cerca(client_id, query):
    if len(query.strip()) < 3:
        raise ErroreRicerca("MyAnimeList richiede almeno 3 caratteri nella ricerca.")
    url = (
            f"{MAL_API}/manga?q={urllib.parse.quote(query.strip())}&limit=25"
            f"&fields={urllib.parse.quote(MAL_CAMPI, safe=',{}_')}"
    )
    try:
        dati = richiesta_json(url, {"X-MAL-CLIENT-ID": client_id}, timeout=25)
    except ErroreRicerca as e:
        if e.codice in (401, 403):
            raise ErroreRicerca("MyAnimeList ha rifiutato il Client ID. Controlla di averlo copiato per intero.", e.codice)
        raise
    if isinstance(dati, dict) and dati.get("error") and "data" not in dati:
        raise ErroreRicerca(f"MyAnimeList ha risposto: {dati.get('message') or dati.get('error')}")

    risultati = []
    for voce in dati.get("data") or []:
        nodo = voce.get("node") or {}
        titolo = nodo.get("title") or "Senza titolo"
        inglese = (nodo.get("alternative_titles") or {}).get("en") or ""
        anno = (nodo.get("start_date") or "")[:4]
        tipo = nodo.get("media_type") or ""
        volumi = nodo.get("num_volumes") or 0

        scrittori, disegnatori = [], []
        for autore in nodo.get("authors") or []:
            persona = autore.get("node") or {}
            nome = f"{persona.get('first_name') or ''} {persona.get('last_name') or ''}".strip()
            ruolo = (autore.get("role") or "").lower()
            if not nome:
                continue
            if "story" in ruolo:
                scrittori.append(nome)
            if "art" in ruolo:
                disegnatori.append(nome)

        sinossi = re.sub(r"\s*\[Written by MAL Rewrite\]\s*$", "", nodo.get("synopsis") or "").strip()
        immagine = nodo.get("main_picture") or {}

        dettagli_etichetta = [x for x in (tipo, anno, f"{volumi} vol." if volumi else "") if x]
        etichetta = titolo
        if inglese and inglese.lower() != titolo.lower():
            etichetta += f" / {inglese}"
        if dettagli_etichetta:
            etichetta += " (" + ", ".join(dettagli_etichetta) + ")"

        note = []
        if inglese and inglese.lower() != titolo.lower():
            note.append(f"Titolo inglese: {inglese}")
        magazine = unici([((x.get("node") or {}).get("name")) for x in nodo.get("serialization") or []])
        if magazine:
            note.append("Pubblicato su: " + ", ".join(magazine))

        risultati.append({
                "etichetta": etichetta,
                "copertina": immagine.get("large") or immagine.get("medium"),
                "campi": {
                        "Series": titolo,
                        "Year": anno,
                        "Count": str(volumi) if volumi else "",
                        "Writer": ", ".join(unici(scrittori)),
                        "Penciller": ", ".join(unici(disegnatori)),
                        "Summary": sinossi,
                },
                "note": note,
                "grezzo": nodo,
        })
    return risultati


# ---------------------------------------------------------------- AniList
AL_API = "https://graphql.anilist.co"
AL_QUERY = """query($q: String) {
    Page(perPage: 20) {
        media(search: $q, type: MANGA, sort: SEARCH_MATCH) {
            title { romaji english }
            format
            startDate { year }
            volumes
            coverImage { extraLarge large }
            genres
            description(asHtml: false)
            staff(perPage: 8) { edges { role node { name { full } } } }
            characters(perPage: 25, sort: [ROLE, RELEVANCE]) { nodes { name { full } } }
        }
    }
}"""


def al_pulisci_trama(testo):
    testo = re.sub(r"~!.*?!~", "", testo or "", flags=re.S)  # spoiler nascosti
    testo = re.sub(r"\(Source:[^)]*\)", "", testo, flags=re.I)
    return pulisci_html(testo)


def al_risultato(voce):
    titoli = voce.get("title") or {}
    romaji = titoli.get("romaji") or ""
    titolo = titoli.get("english") or romaji or "Senza titolo"
    anno = str((voce.get("startDate") or {}).get("year") or "")
    volumi = voce.get("volumes") or 0

    scrittori, disegnatori = [], []
    for collaboratore in (voce.get("staff") or {}).get("edges") or []:
        ruolo = (collaboratore.get("role") or "").lower()
        nome = ((collaboratore.get("node") or {}).get("name") or {}).get("full") or ""
        if "touch" in ruolo or "assistant" in ruolo:
            continue
        if re.search(r"\bstory\b", ruolo):
            scrittori.append(nome)
        if re.search(r"\bart\b", ruolo):
            disegnatori.append(nome)
    personaggi = [((c.get("name") or {}).get("full")) for c in (voce.get("characters") or {}).get("nodes") or []]

    dettagli_etichetta = [x for x in (voce.get("format") or "", anno, f"{volumi} vol." if volumi else "") if x]
    diverso = romaji and romaji.lower() != titolo.lower()
    etichetta = titolo + (f" / {romaji}" if diverso else "")
    if dettagli_etichetta:
        etichetta += " (" + ", ".join(dettagli_etichetta) + ")"

    note = [f"Titolo originale: {romaji}"] if diverso else []
    if voce.get("genres"):
        note.append("Generi: " + ", ".join(voce["genres"]))
    copertine = voce.get("coverImage") or {}
    return {
            "etichetta": etichetta,
            "copertina": copertine.get("extraLarge") or copertine.get("large"),
            "campi": {
                    "Series": titolo,
                    "Year": anno,
                    "Count": str(volumi) if volumi else "",
                    "Writer": ", ".join(unici(scrittori)),
                    "Penciller": ", ".join(unici(disegnatori)),
                    "Characters": ", ".join(unici(personaggi)),
                    "Summary": al_pulisci_trama(voce.get("description")),
            },
            "note": note,
    }


def al_cerca(_chiave, query):
    corpo = json.dumps({"query": AL_QUERY, "variables": {"q": query.strip()}}).encode("utf-8")
    dati = richiesta_json(AL_API, {"Content-Type": "application/json"}, 25, corpo)
    if dati.get("errors"):
        raise ErroreRicerca(f"AniList ha risposto: {dati['errors'][0].get('message') or 'errore sconosciuto'}")
    return [al_risultato(voce) for voce in ((dati.get("data") or {}).get("Page") or {}).get("media") or []]


# ---------------------------------------------------------------- ComicsBox
CB_SITO = "https://www.comicsbox.it/"
CB_INTESTAZIONI = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
}


cb_blocco = threading.Lock()
cb_pagine = {}
cb_memoria = {}  # tutti i risultati trovati finché il programma è aperto, per riusarli sui file dopo


def cb_scarica(url):
    # ComicsBox risponde 429 già dopo poche ricerche ravvicinate: una richiesta alla volta,
    # mai due volte la stessa pagina e attesa automatica prima di arrendersi
    with cb_blocco:
        if url not in cb_pagine:
            for attesa in (15, 30, None):
                try:
                    cb_pagine[url] = richiesta_bytes(url, CB_INTESTAZIONI).decode("utf-8", "ignore")
                    break
                except ErroreRicerca as e:
                    if e.codice != 429:
                        raise
                    if attesa is None:
                        raise ErroreRicerca("ComicsBox limita le richieste troppo ravvicinate. Riprova tra un minuto.", 429)
                    time.sleep(attesa)
        return cb_pagine[url]


def cb_analizza_etichetta(testo):
    """Es. "DYLAN DOG # 100 - La storia di Dylan Dog (Sergio Bonelli Editore)"."""
    campi = {}
    m = re.search(r"\s*\(([^()]*)\)$", testo)
    if m:
        campi["Publisher"] = m.group(1).strip()
        testo = testo[:m.start()]
    m = re.match(r"(.*?)\s*#\s*(\S*)(?:\s*-\s*(.*))?$", testo)
    if m:
        campi["Series"] = m.group(1)
        campi["Number"] = m.group(2).rstrip("*")
        campi["Title"] = m.group(3) or ""
    else:
        campi["Series"] = testo
    return campi


def cb_analizza_pagina(pagina, query):
    testo, numero = separa_numero(query)
    risultati = []
    visti = set()
    for a in BeautifulSoup(pagina, "html.parser").find_all("a", href=True):
        href = a["href"]
        if not any(k in href for k in ("/serie/", "/albo/", "serie.php", "albo.php")):
            continue
        titolo = a.get_text(strip=True)
        if len(titolo) < 2:
            continue
        url = href if href.startswith("http") else CB_SITO + href.lstrip("/")
        if url in visti:
            continue
        visti.add(url)
        risultati.append({
                "etichetta": titolo,
                "copertina": None,
                "campi": cb_analizza_etichetta(titolo),
                "note": [f"Scheda ComicsBox: {url}"],
                "grezzo": {"url": url},
        })

    def ordine(r):
        fuori_numero = 0 if numero and r["campi"].get("Number") == pulisci_numero(numero) else 1
        return (punti_pertinenza(r["campi"]["Series"].lower(), testo), fuori_numero)

    risultati.sort(key=ordine)
    return risultati


def cb_cerca(_chiave, query):
    if BeautifulSoup is None:
        raise ErroreRicerca("Libreria 'beautifulsoup4' non installata. Esegui: pip install beautifulsoup4")
    url = f"{CB_SITO}search.php?stringa={urllib.parse.quote(query)}&criterio=ita"
    return cb_analizza_pagina(cb_scarica(url), query)


def cb_testo(zuppa, selettore):
    elemento = zuppa.select_one(selettore)
    return elemento.get_text(" ", strip=True) if elemento else ""


def cb_copertina(zuppa, selettore):
    elemento = zuppa.select_one(selettore)
    return CB_SITO + elemento["src"].lstrip("/") if elemento and elemento.get("src") else None


def cb_campi_albo(zuppa):
    scrittori, disegnatori = [], []
    for a in zuppa.select(".alboita_dettagli a[href^='/autore/']"):
        ruolo = str(a.next_sibling or "").lower()
        nome = a.get_text(strip=True)
        if re.search(r"script|stor|test|sogg|sceneg|writer", ruolo):
            scrittori.append(nome)
        if re.search(r"\bart|pencil|disegn", ruolo):
            disegnatori.append(nome)
    anno = re.search(r"\d{4}", cb_testo(zuppa, "#data_issue"))
    return {
            "Series": cb_testo(zuppa, "#intestazione h1").split("#")[0].strip(),
            "Title": cb_testo(zuppa, "#subtitolo_issue").lstrip("| ") or cb_testo(zuppa, ".titolo_storia"),
            "Year": anno.group() if anno else "",
            "Publisher": cb_testo(zuppa, "#editore_issue"),
            "Writer": ", ".join(unici(scrittori)),
            "Penciller": ", ".join(unici(disegnatori)),
            "Summary": "\n\n".join(s.get_text(" ", strip=True) for s in zuppa.select(".sinossi")),
    }


def cb_dettagli(_chiave, risultato):
    """Apre la scheda scelta solo quando la selezioni, per non consumare il limite di richieste."""
    url = risultato["grezzo"]["url"]
    zuppa = BeautifulSoup(cb_scarica(url), "html.parser")
    risultato["note"].clear()  # il link ora è nel Summary: in anteprima si vedrebbe due volte
    if "/albo/" in url or "albo.php" in url:
        risultato["copertina"] = cb_copertina(zuppa, "#container_cover_cb img")
        campi = cb_campi_albo(zuppa)
        # Con il link davanti una trama tutta maiuscola non verrebbe più riconosciuta come tale
        trama = togli_maiuscole("Summary", campi["Summary"])
        campi["Summary"] = f"{url}\n\n{trama}" if trama else url
        return campi

    risultato["copertina"] = cb_copertina(zuppa, "#container_cover_serie img")
    informazioni = cb_testo(zuppa, "#info_dettagli1")
    inizio_serie = re.search(r"anno inizio serie:\s*(\d{4})", informazioni)
    if inizio_serie:
        risultato["note"].append(f"Serie iniziata nel {inizio_serie.group(1)}")
    numeri = re.search(r"numeri rilasciati:\s*\d+\s*-\s*(\d+)", informazioni)
    titolo = zuppa.title.get_text(strip=True).split(" :: ")[0] if zuppa.title else ""
    return {"Series": titolo, "Count": numeri.group(1) if numeri else "", "Summary": url}


# ---------------------------------------------------------------- elenco delle fonti
FONTI_RICERCA = {
        "ComicVine": {
                "chiave_config": "comicvine_api_key",
                "etichetta_chiave": "API Key ComicVine:",
                "aiuto": "Chiave gratuita su comicvine.gamespot.com/api",
                "url_aiuto": "https://comicvine.gamespot.com/api/",
                "cerca": cv_cerca,
                "dettagli": cv_dettagli,
                "query_iniziale": lambda serie, numero: f"{serie} {numero}".strip(),
                "formatta_titoli": True,
        },
        "MyAnimeList": {
                "chiave_config": "mal_client_id",
                "etichetta_chiave": "Client ID MyAnimeList:",
                "aiuto": "Si crea su myanimelist.net/apiconfig (Create ID)",
                "url_aiuto": "https://myanimelist.net/apiconfig",
                "cerca": mal_cerca,
                "dettagli": None,
                "query_iniziale": lambda serie, numero: serie.strip(),
                "formatta_titoli": False,
        },
        "AniList": {
                "chiave_config": None,
                "etichetta_chiave": "Chiave (non serve):",
                "aiuto": "Manga: trama in inglese, autori e personaggi",
                "url_aiuto": "https://anilist.co",
                "cerca": al_cerca,
                "dettagli": None,
                "query_iniziale": lambda serie, numero: serie.strip(),
                "formatta_titoli": False,
        },
        "ComicsBox": {
                "chiave_config": None,
                "etichetta_chiave": "Chiave (non serve):",
                "aiuto": "Fumetti pubblicati in Italia: comicsbox.it",
                "url_aiuto": CB_SITO,
                "cerca": cb_cerca,
                "dettagli": cb_dettagli,
                "query_iniziale": lambda serie, numero: f"{serie} {numero}".strip(),
                "formatta_titoli": False,
                "memoria": cb_memoria,
        },
}
FONTE_PREDEFINITA = "ComicVine"
