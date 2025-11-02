# infocmp minitel1b-80

# Pour lancer le programme :
# python -m venv venv
# source venv/bin/activate
# pip install pyserial
# python terminal.py --device /dev/ttyUSB0 --baud 4800 --term minitel1b-80



#!/usr/bin/env python3
# -*- coding: latin-1 -*-
"""
minitel_menu.py

UI Minitel 1B avec menu:
- Lignes 1-3: en-tête comme l'ancien programme.
- Lignes 7-12: options "1" à "6".
- Ligne 25: [ENTER QUERY] avec saisie.
- '1' lance apollo.py (dans le même dossier).
- '2' défile etat_vaisseau.txt puis retour menu après Entrée.
- '3'-'6' défilent d'autres fichiers texte puis retour menu.

Prérequis: pyserial, terminfo Minitel déjà installé (tput -T).
"""

import os
import sys
import time
import argparse
import subprocess
import serial
import threading

# CONFIG
TERMNAME = os.environ.get('MINITEL_TERM', 'minitel1b-80')
SERIAL_DEVICE = '/dev/ttyUSB0'
BAUD = 4800
COLS = 80
LINES = 24
SCROLL_DELAY = 0.10  # secondes entre lignes lors du défilement

# pacing série pour Minitel
PAGE_CHUNK = 32      # taille des bursts
PAGE_GAP   = 0.01    # pause entre bursts

# Fichiers associés aux options
FILES = {
    '2': '2.txt',
    '3': '3.txt',
    '4': '4.txt',
    '5': '5.txt',
}

PAGING_PROMPT = "[SUITE. Appuyez ENTREE pour voir la suite]"
MODES = {
    '2': 'paged',  # défilement auto
    '3': 'paged',   # pagination par Entrée
    '4': 'paged',
    '5': 'paged',
}

# Gestion du son
class LoopPlayer:
    def __init__(self, wav_path):
        self.wav = wav_path
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
    def _run(self):
        while not self.stop.is_set():
            try:
                p = subprocess.Popen(['aplay', '-q', self.wav])
                while p.poll() is None and not self.stop.is_set():
                    time.sleep(0.05)
                if p.poll() is None and self.stop.is_set():
                    p.terminate()
            except FileNotFoundError:
                break
    def start(self): self.thread.start()
    def stop_now(self):
        self.stop.set()
        self.thread.join(timeout=1.0)

def play_once(wav_path):
    try:
        subprocess.call(['aplay', '-q', wav_path])
    except FileNotFoundError:
        pass

# ----- terminfo helpers -----
def tput(name, *args):
    cmd = ['tput', '-T', TERMNAME, name]
    if args:
        cmd += [str(a) for a in args]
    try:
        out = subprocess.check_output(cmd)
        return out
    except subprocess.CalledProcessError:
        return b''

def send(ser, b):
    if isinstance(b, str):
        b = b.encode('latin-1', errors='ignore')
    # envoi en petits blocs + pauses pour éviter le débordement
    for i in range(0, len(b), PAGE_CHUNK):
        ser.write(b[i:i+PAGE_CHUNK])
        ser.flush()
        time.sleep(PAGE_GAP)

def seq_cup(row, col):
    s = tput('cup', row - 1, col - 1)
    if s:
        return s
    return f"\x1b[{row};{col}H".encode()

def seq_clear():
    s = tput('clear')
    if s:
        return s
    return b"\x1b[2J\x1b[H"

def seq_smso():
    s = tput('smso')
    if s:
        return s
    return b"\x1b[7m"

def seq_rmso():
    s = tput('rmso')
    if s:
        return s
    return b"\x1b[27m"

def seq_el():
    s = tput('el')
    if s:
        return s
    return b"\x1b[K"

def seq_civis():
    s = tput('civis');  return s if s else b""
def seq_cnorm():
    s = tput('cnorm');  return s if s else b""
def seq_dl1():
    s = tput('dl1');    return s if s else b"\x1b[M"

# ----- Utilitaires d'écran -----

def clear_window(ser, top=4, bottom=23):
    for r in range(top, bottom + 1):
        send(ser, seq_cup(r, 1)); send(ser, seq_el())

def show_footer_message(ser, text):
    send(ser, seq_cup(LINES, 1)); send(ser, seq_el()); send(ser, text[:COLS-2])

def seq_nel():
    s = tput('nel')
    return s if s else b"\x1bE"  # NEL = CR+LF atomique

TRANS = str.maketrans({
    '’':"'", '‘':"'", '“':'"', '”':'"',
    '–':'-', '—':'-', '…':'...', '\u00A0':' '
})
def safe_line(s: str) -> str:
    # texte “propre” en latin-1
    return s.translate(TRANS).encode('latin-1','ignore').decode('latin-1','ignore')

# ------ Pagination "suite" -----

def paged_file(ser, filename):
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, filename)
    if not os.path.isfile(path):
        show_status(ser, f"Fichier introuvable: {filename}")
        return

    raw = read_text_lines(path)
    lines = [safe_line(ln).expandtabs(8) for ln in raw]

    top, bottom = 4, 23
    window = bottom - top + 1  # 20
    idx = 0

    while True:
        clear_window(ser, top, bottom)
        send(ser, seq_cup(top, 1))  # UNE seule position par page
        # >>> son de “dactylo” pendant l’écriture de page
        lp = LoopPlayer('loud_type_start.wav'); lp.start()

        written = 0
        while idx < len(lines) and written < window:
            ln = lines[idx][:COLS]
            send(ser, ln)
            send(ser, seq_nel())   # saut de ligne atomique
            time.sleep(0.02)       # petite pause après chaque ligne
            idx += 1
            written += 1
        lp.stop_now()  # <<< stop une fois la page rendue

        if idx >= len(lines):
            send(ser, seq_cup(LINES, 1)); send(ser, seq_el())
            send(ser, "[FIN. Appuyez ENTREE pour revenir]")
            wait_enter(ser)
            render_layout(ser)
            return
        else:
            send(ser, seq_cup(LINES, 1)); send(ser, seq_el())
            send(ser, "[SUITE. Appuyez ENTREE pour voir la suite]")
            wait_enter(ser)

# ----- UI helpers -----
def draw_border_two_lines(ser, cols=COLS):
    top = 1
    bottom = 2
    send(ser, seq_cup(top, 1)); send(ser, seq_smso()); send(ser, ' ' * cols); send(ser, seq_rmso())
    send(ser, seq_cup(bottom, 1)); send(ser, seq_smso()); send(ser, ' ' * cols); send(ser, seq_rmso())
    for r in (top, bottom):
        send(ser, seq_cup(r, 1)); send(ser, seq_smso()); send(ser, ' '); send(ser, seq_rmso())
        send(ser, seq_cup(r, cols)); send(ser, seq_smso()); send(ser, ' '); send(ser, seq_rmso())

def render_header(ser):
    init = tput('is2')
    if init:
        send(ser, init)
    send(ser, seq_clear())
    draw_border_two_lines(ser, COLS)

    # L1 titre
    title = '#  -  SEEGSON BIOS 5.3.09.63                                             '
    col = max(2, (COLS - len(title)) // 2 + 1)
    lp = LoopPlayer('typing_long.wav'); lp.start()
    send(ser, seq_cup(1, col)); send(ser, seq_smso()); send(ser, title[:COLS-2]); send(ser, seq_rmso())
    lp.stop_now()

    # L2 message
    msg = '============================'
    lp = LoopPlayer('typing_long.wav'); lp.start()
    send(ser, seq_cup(2, 4)); send(ser, seq_smso()); send(ser, msg[:max(0, COLS-23)]); send(ser, seq_rmso())
    lp.stop_now()

    # L3 séparation
    sep = '_' * (COLS - 2)
    send(ser, seq_cup(3, 2)); send(ser, sep[:COLS-2])

def render_menu(ser):
    items = {
        7: "1 - A.P.O.L.L.O",
        8: "2 - POWER STATUS",
        9: "3 - HVAC",
        10:"4 - LIGHTNING",
        11:"5 - CONTAINMENT PROTOCOL",
    }
    for row in range(7, 13):
        send(ser, seq_cup(row, 4)); send(ser, seq_el())
        txt = items.get(row, '')
        lp = LoopPlayer('typing_long.wav'); lp.start()
        send(ser, txt[:COLS-8])
        lp.stop_now()

def render_input_box(ser):
    send(ser, seq_cup(LINES, 1)); send(ser, seq_el())
    send(ser, '[ENTER QUERY]')
    send(ser, seq_cup(LINES, 15))

def render_layout(ser):
    render_header(ser)
    render_menu(ser)
    render_input_box(ser)

def show_status(ser, text, row=6):
    send(ser, seq_cup(row, 1)); send(ser, seq_el()); send(ser, text[:COLS-2])

# ----- actions -----
def run_apollo(ser):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = os.path.join(here, 'apollo-boot.py')
    if not os.path.isfile(ap):
        show_status(ser, "Erreur: apollo.py introuvable.")
        return

    args = [
        sys.executable, ap,
        "--device", ser.port,
        "--baud", str(ser.baudrate),
        "--term", TERMNAME
    ]
    env = os.environ.copy()
    try:
        ser.close()  # libère /dev/ttyUSB0 pour apollo.py
        rc = subprocess.call(args, env=env)  # apollo tourne; /exit => fin
    except Exception as e:
        show_status(ser, f"Erreur lancement Apollo: {e}")
        # on tente quand même de rouvrir
    finally:
        try:
            ser.open()  # rouvre avec les mêmes paramètres (7E1, xon/xoff, etc.)
        except Exception as e:
            show_status(ser, f"Erreur réouverture série: {e}")
            return

    # de retour au menu
    render_layout(ser)

def read_text_lines(path):
    with open(path, 'r', encoding='latin-1', errors='ignore') as f:
        return f.read().splitlines()

def scroll_text(ser, lines):
    # Zone d’affichage: 4→23 (20 lignes)
    top, bottom = 4, 23
    for line in lines:
        # scroll up: place curseur dernière ligne, effacer, écrire
        send(ser, seq_cup(bottom, 2)); send(ser, seq_el())
        send(ser, line[:COLS-2])
        # défilement: avancer en simulant
        # Pour Minitel sans "scroll region", on réécrit toute la fenêtre
        # Simple: après écriture, remonter et ré-imprimer fenêtre cumulée
        # Mais plus coûteux. Alternative: clear fenêtre chaque fois.
        time.sleep(SCROLL_DELAY)
        # Shift fenêtre manuelle
        # On récupère rien, donc on efface tout et on réimprime les 20 dernières
        # lignes accumulées dans un tampon
        # Implémentation légère:
        pass

def scroll_file(ser, filename):
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, filename)
    if not os.path.isfile(path):
        show_status(ser, f"Fichier introuvable: {filename}")
        return

    lines = read_text_lines(path)

    top, bottom = 4, 23          # fenêtre 4–23
    window = bottom - top + 1    # 20

    # Nettoyer la fenêtre une fois
    for r in range(top, bottom + 1):
        send(ser, seq_cup(r, 2)); send(ser, seq_el())

    # Masquer le curseur pendant l’animation
    send(ser, seq_civis())

    filled = 0
    # >>> son de “dactylo” pendant tout le défilement
    lp = LoopPlayer('loud_type_start.wav'); lp.start()

    for ln in lines:
        txt = ln[:COLS-2]

        if filled < window:
            # Remplissage initial: écrire à la suite
            row = top + filled
            send(ser, seq_cup(row, 2)); send(ser, seq_el()); send(ser, txt)
            filled += 1
        else:
            # Défilement: supprimer ligne 4 puis écrire en bas (23)
            send(ser, seq_cup(top, 2)); send(ser, seq_dl1())
            send(ser, seq_cup(bottom, 2)); send(ser, seq_el()); send(ser, txt)

        time.sleep(SCROLL_DELAY)
    lp.stop_now()  # <<< stop quand le défilement est terminé

    # Message fin + attente Entrée
    send(ser, seq_cup(bottom, 2)); send(ser, seq_el()); send(ser, "[FIN. Appuyez ENTREE pour revenir]")
    send(ser, seq_cnorm())
    wait_enter(ser)
    render_layout(ser)

def wait_enter(ser):
    while True:
        b = ser.read(1)
        if not b:
            continue
        c = b.decode('latin-1', errors='ignore')
        if c in ('\r', '\n'):
            return

# ----- boucle d'entrée -----
def process_query(ser, q):
    q = q.strip()
    if q == '1':
        run_apollo(ser)
    elif q in FILES:
        mode = MODES.get(q, 'paged')
        if mode == 'scroll':
            scroll_file(ser, FILES[q])
        else:
            paged_file(ser, FILES[q])
    else:
        show_status(ser, f"Commande inconnue: {q}")

def input_loop(ser, debug=False):
    max_input = COLS - 15
    buffer = []
    col = 15
    send(ser, seq_cup(LINES, col))
    while True:
        b = ser.read(1)
        if not b:
            continue
        c = b.decode('latin-1', errors='ignore')

        if c in ('\r', '\n'):
            query = ''.join(buffer)
            # efface l’écho
            send(ser, seq_cup(LINES, 15)); send(ser, ' ' * max_input); send(ser, seq_cup(LINES, 14))
            buffer = []
            process_query(ser, query)
            continue

        if ord(c) in (8, 127):
            if buffer:
                buffer.pop()
                col = 15 + len(buffer)
                send(ser, seq_cup(LINES, col)); send(ser, ' '); send(ser, seq_cup(LINES, col))
            continue

        if 32 <= ord(c) <= 126 and len(buffer) < max_input:
            buffer.append(c)
            send(ser, c)
            continue
        # ignorer le reste

def main():
    global TERMNAME
    parser = argparse.ArgumentParser(description='Minitel UI Menu')
    parser.add_argument('--device', default=SERIAL_DEVICE)
    parser.add_argument('--baud', type=int, default=BAUD)
    parser.add_argument('--term', default=None)
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    if args.term:
        TERMNAME = args.term

    ser = serial.Serial(
        args.device,
        baudrate=args.baud,
        bytesize=serial.SEVENBITS,
        parity=serial.PARITY_EVEN,
        stopbits=serial.STOPBITS_ONE,
        xonxoff=True,
        rtscts=False,
        dsrdtr=False,
        timeout=0.1
    )
    try:
        render_layout(ser)
        input_loop(ser, debug=args.debug)
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()

if __name__ == '__main__':
    main()
