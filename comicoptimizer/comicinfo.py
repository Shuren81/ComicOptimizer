"""Lettura e scrittura del ComicInfo.xml e pulizia dei testi. Nessuna dipendenza dall'interfaccia."""
import os
import re
import xml.etree.ElementTree as ET
import zipfile

LINGUE = {
        "italiano": "it", "italian": "it", "ita": "it",
        "inglese": "en", "english": "en", "eng": "en",
        "francese": "fr", "french": "fr", "fra": "fr", "fre": "fr",
        "spagnolo": "es", "spanish": "es", "spa": "es",
        "tedesco": "de", "german": "de", "deu": "de", "ger": "de",
        "portoghese": "pt", "portuguese": "pt", "por": "pt",
        "giapponese": "ja", "japanese": "ja", "jpn": "ja",
        "cinese": "zh", "chinese": "zh",
        "coreano": "ko", "korean": "ko",
        "russo": "ru", "russian": "ru",
        "olandese": "nl", "dutch": "nl",
        "polacco": "pl", "polish": "pl",
        "svedese": "sv", "swedish": "sv",
        "turco": "tr", "turkish": "tr",
        "arabo": "ar", "arabic": "ar",
        "greco": "el", "greek": "el",
        "ceco": "cs", "czech": "cs",
        "ungherese": "hu", "hungarian": "hu",
}

ROMANI_MINUSCOLI = re.compile(r"^(?=[ivx]{2,}$)x{0,3}(?:ix|iv|v?i{0,3})$")
CAMPI_NON_TESTO = {"Year", "LanguageISO", "Number", "Count", "Manga"}
# I campi della finestra Info e rinomina
CAMPI = ("Title", "Series", "Volume", "Writer", "Penciller", "Publisher", "Format", "StoryArc",
         "Characters", "Teams", "Year", "LanguageISO", "Number", "Count", "Summary", "Manga")
# ordine dello schema ComicInfo (alcuni programmi lo vogliono); gli elementi sconosciuti vanno in fondo
CI_ORDER = ("Title", "Series", "Number", "Count", "Volume", "AlternateSeries", "AlternateNumber",
            "AlternateCount", "Summary", "Notes", "Year", "Month", "Day", "Writer", "Penciller",
            "Inker", "Colorist", "Letterer", "CoverArtist", "Editor", "Translator", "Publisher",
            "Imprint", "Genre", "Tags", "Web", "PageCount", "LanguageISO", "Format",
            "BlackAndWhite", "Manga", "Characters", "Teams", "Locations", "ScanInformation",
            "StoryArc", "SeriesGroup", "AgeRating", "Pages", "CommunityRating", "MainCharacterOrTeam",
            "Review", "GTIN")
# Non ammessi in XML: scritti nel file lo renderebbero illeggibile
CARATTERI_VIETATI_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def normalizza_lingua(testo):
    t = testo.strip().lower()
    if t in LINGUE:
        return LINGUE[t]
    m = re.fullmatch(r"([a-z]{2,3})(?:-([a-z]{2}))?", t)
    if m:
        return m.group(1) + ("-" + m.group(2).upper() if m.group(2) else "")
    return None


def formatta_parola(parola):
    if not parola.islower():
        return parola
    return "-".join(formatta_parte(parte) for parte in parola.split("-"))


def formatta_parte(parte):
    if ROMANI_MINUSCOLI.match(parte.strip("()[].,:;!?'\"")):
        return parte.upper()
    return re.sub(r"[^\W\d_]", lambda m: m.group().upper(), parte, count=1)


def formatta_testo_intelligente(testo, normalizza_maiuscole=False):
    if normalizza_maiuscole and testo.isupper():
        testo = testo.lower()
    return " ".join(formatta_parola(p) for p in testo.split())


def ordina_campi(radice):
    ordine = {t: i for i, t in enumerate(CI_ORDER)}
    radice[:] = sorted(radice, key=lambda e: ordine.get(e.tag, len(ordine)))


def cerca(testo, schema):
    """Cerca con i jolly ? e *; il resto del testo vale alla lettera."""
    modello = "".join("." if c == "?" else ".*?" if c == "*" else re.escape(c) for c in schema)
    return re.search(modello, testo)


def estrai_dal_nome(nome, dopo, fino):
    """Il pezzo di nome tra "dopo" e "fino", None se non si trova. "_" vale come spazio."""
    nome = nome.replace("_", " ")
    dopo, fino = dopo.replace("_", " "), fino.replace("_", " ")
    if dopo:
        trovato = cerca(nome, dopo)
        if trovato is None:
            return None
        nome = nome[trovato.end():]
    if fino:
        trovato = cerca(nome, fino)
        if trovato is None:
            return None
        nome = nome[:trovato.start()]
    return formatta_testo_intelligente(nome.strip(), normalizza_maiuscole=True)


def nome_da_schema(schema, valori, cifre):
    """Il nome di file (senza estensione) che esce dallo schema con questi valori."""
    def valore(campo, predefinito=""):
        return formatta_testo_intelligente(valori.get(campo) or predefinito)

    numero = valori.get("Number", "") or ""
    if numero.isdigit():
        numero = numero.zfill(cifre)
    sostituzioni = {campo: valore(campo) for campo in CAMPI if campo not in ("Summary", "Manga")}
    sostituzioni.update(Number=numero, LanguageISO=valori.get("LanguageISO", "") or "")
    nome = schema
    for campo, testo in sostituzioni.items():
        if not testo and f"<{campo}>" in nome:      # campo vuoto: via anche il suo " - "
            nome = togli_tag_schema(nome, campo)
    for campo, testo in sostituzioni.items():
        nome = nome.replace(f"<{campo}>", testo)
    # Le barre separano due parole: toglierle e basta le attaccherebbe
    nome = re.sub(r"[\\/]", "-", nome)
    nome = nome.replace(":", " - ")
    nome = re.sub(r'[*?"<>|]', "", nome)
    return re.sub(r"\s+", " ", nome).strip().rstrip(". ")     # Windows non accetta il punto finale


def togli_maiuscole(campo, testo):
    if campo in CAMPI_NON_TESTO or not testo.isupper():
        return testo
    if campo == "Summary":
        return testo.capitalize()
    return formatta_testo_intelligente(testo, normalizza_maiuscole=True)


def togli_tag_schema(schema, campo):
    # Va via anche il separatore del tag, altrimenti "<A> - <B> - <C>" diventerebbe "<A> -  - <C>"
    schema = re.sub(rf"#?<{campo}>\s*[-–_.,]*\s*", "", schema)
    schema = re.sub(r"\(\s*\)|\[\s*\]", "", schema)
    return re.sub(r" {2,}", " ", schema).strip(" -–_.,")


def pulisci_numero(testo):
    if not testo:
        return ""
    t = str(testo).strip()
    if t.isdigit():
        return str(int(t))
    return t


def trova_nome_xml(z):
    return next(
            (n for n in z.namelist() if os.path.basename(n).lower() == "comicinfo.xml"),
            None,
    )


def leggi_radice(percorso):
    with zipfile.ZipFile(percorso) as z:
        nome_xml = trova_nome_xml(z)
        if nome_xml is None:
            return None
        return ET.fromstring(z.read(nome_xml))


def scrivi_cbz(percorso, valori, avanzamento=None):
    radice = leggi_radice(percorso)
    if radice is None:
        radice = ET.Element("ComicInfo")
    for campo, testo in valori.items():
        if campo == "Number" and testo:
            testo = pulisci_numero(testo)
        testo = CARATTERI_VIETATI_XML.sub("", testo)
        elemento = radice.find(campo)
        if testo:
            if elemento is None:
                elemento = ET.SubElement(radice, campo)
            elemento.text = testo
        elif elemento is not None:
            radice.remove(elemento)

    ordina_campi(radice)
    xml_bytes = ET.tostring(radice, encoding="utf-8", xml_declaration=True)
    dimensione_iniziale = os.path.getsize(percorso)
    try:
        with zipfile.ZipFile(percorso, "a") as z:
            nome_xml = trova_nome_xml(z)
            dimensione_dati = sum(v.file_size for v in z.infolist())
            if nome_xml is not None:
                z.filelist = [v for v in z.filelist if v.filename != nome_xml]
                del z.NameToInfo[nome_xml]
            # Riscrivere le immagini è il grosso del tempo: l'XML e il nuovo indice vanno in coda.
            # Partire dalla fine, non dal vecchio indice, lascia il file leggibile se si interrompe.
            # shortcut: lo spazio del vecchio XML e indice non si recupera (circa 8 KB a salvataggio), ricomprimere se mai pesasse
            z.start_dir = dimensione_iniziale
            z.writestr(nome_xml or "ComicInfo.xml", xml_bytes, compress_type=zipfile.ZIP_DEFLATED)
    except Exception:
        os.truncate(percorso, dimensione_iniziale)
        raise
    if avanzamento:
        avanzamento(dimensione_dati)
