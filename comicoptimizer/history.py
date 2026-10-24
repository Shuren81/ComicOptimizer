"""Cronologia delle rinomine su disco: si possono annullare anche dopo aver chiuso il programma.

Un file di testo (una riga JSON per evento) accanto al log:
  {"batch", "time", "old", "new"}  un file rinominato
  {"batch", "undo": old}           quel file è stato riportato al nome di prima
Ogni riga è scritta subito su disco: un'interruzione a metà non perde le rinomine già fatte.
"""

import json
import os
import time
import uuid

from .logsetup import LOG_PATH, log

HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(LOG_PATH)), "rinomine.jsonl")
MAX_BATCHES = 50


def new_batch():
    """Id di un'operazione (una finestra Rinomina, anche con più passaggi)."""
    return uuid.uuid4().hex[:12]


def _append(entry):
    try:
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except OSError as e:                              # il registro non deve mai fermare una rinomina
        log.warning(f"Cronologia rinomine non scritta: {e}")


def record(batch, old, new):
    _append({"batch": batch, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "old": old, "new": new})


def record_undo(batch, old):
    _append({"batch": batch, "undo": old})


def _read():
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:                            # riga rovinata (es. corrente saltata): si salta
            continue
    return out


def batches():
    """Operazioni dalla più recente: {"id", "time", "pairs": [(vecchio, nuovo)], "pending": [...]}.
    "pending" sono le coppie non ancora annullate, nell'ordine in cui sono state fatte."""
    found, undone = {}, {}
    for e in _read():
        if "undo" in e:
            undone.setdefault(e.get("batch"), set()).add(e["undo"])
        elif "old" in e and "new" in e:
            b = found.setdefault(e.get("batch"), {"id": e.get("batch"), "time": e.get("time", ""), "pairs": []})
            b["pairs"].append((e["old"], e["new"]))
    for b in found.values():
        b["pending"] = [(o, n) for o, n in b["pairs"] if o not in undone.get(b["id"], ())]
    return list(found.values())[::-1]


def prune(keep=MAX_BATCHES):
    """Tiene solo le ultime `keep` operazioni (riscrittura sicura: .tmp poi sostituzione)."""
    entries = _read()
    order = list(dict.fromkeys(e.get("batch") for e in entries))
    if len(order) <= keep:
        return
    kept = set(order[-keep:])
    tmp = HISTORY_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            for e in entries:
                if e.get("batch") in kept:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
        os.replace(tmp, HISTORY_PATH)
    except OSError as e:
        log.warning(f"Cronologia rinomine non accorciata: {e}")
