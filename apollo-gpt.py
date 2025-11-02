# infocmp minitel1b-80

# Pour lancer le programme :
# python -m venv venv
# source venv/bin/activate
# pip install pyserial
# pip install openai
# python apollo-gpt.py --device /dev/ttyUSB0 --baud 4800 --term minitel1b-80

#!/usr/bin/env python3
"""
appolo-gpt.py

Contrôle simple du Minitel 1B via port série.
- Envoie la mise en page demandée.
- Lit les touches du Minitel et fournit un encart d'écriture en ligne 24.

Prérequis: pyserial, tic compilé pour le terminfo fourni.
Configurez TERMNAME si vous avez compilé l'entry avec un autre nom.

Usage:
  python apollo-gpt.py --device /dev/ttyUSB0 --baud 4800 --term minitel1b-80

Explications minimales inline.
"""

import os
import sys
import time
import argparse
import subprocess
import serial
import threading
import unicodedata
from openai import OpenAI
from pathlib import Path
import textwrap
from dotenv import load_dotenv
load_dotenv()

# CONFIG
TERMNAME = os.environ.get('MINITEL_TERM', 'minitel1b-80')  # change if your terminfo entry has another name
SERIAL_DEVICE = '/dev/ttyUSB0'
PAGE_CHUNK = 32
PAGE_GAP   = 0.01
BAUD = 4800
COLS = 80
LINES = 24
TRANSLIT_MAP = {
    '“':'"', '”':'"', '‘':"'", '’':"'", '—':'-', '–':'-',
    '•':'*', '…':'...', '\u00a0':' ', '\u2009':' ', '\u202f':' ',
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

# Sanitize
def sanitize_text(s: str) -> str:
    # remplacements ciblés
    for k,v in TRANSLIT_MAP.items():
        s = s.replace(k, v)
    # normalisation générale
    s = unicodedata.normalize('NFKC', s)
    # supprime/convertit contrôles hors CR/LF/TAB
    s = ''.join(ch if ch in '\r\n\t' or 32 <= ord(ch) <= 255 else '?' for ch in s)
    return s

# helper: get a terminfo control string via tput
def tput(name, *args):
    cmd = ['tput', '-T', TERMNAME, name]
    if args:
        cmd += [str(a) for a in args]
    try:
        out = subprocess.check_output(cmd)
        return out
    except subprocess.CalledProcessError:
        return b''

# low-level write to serial, ensure bytes
def send(ser, b):
    if isinstance(b, str):
        # nettoie et convertit en Latin-1
        b = sanitize_text(b).encode('latin-1', errors='replace')
    # pagination physique
    for i in range(0, len(b), PAGE_CHUNK):
        ser.write(b[i:i+PAGE_CHUNK])
        ser.flush()
        time.sleep(PAGE_GAP)

# build commonly used sequences (fall back to simple ANSI-style if not in terminfo)
def seq_cup(row, col):
    s = tput('cup', row - 1, col - 1)
    if s:
        return s
    # fallback: ANSI
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

def clear_area(ser, row_start, row_end):
    for r in range(row_start, row_end + 1):
        send(ser, seq_cup(r, 1)); send(ser, seq_el())

def print_wrapped(ser, text, row_start=6, row_end=22, width=COLS-2, left_col=2):
    lines = []
    for para in text.split('\n'):
        lines.extend(textwrap.wrap(para, width=width) or [''])
    r = row_start
    for ln in lines:
        if r > row_end: break
        send(ser, seq_cup(r, left_col)); send(ser, seq_el()); send(ser, ln[:width])
        r += 1

# --- Layout constants ---
ROW_USER = 5          # [VOUS] ici
ROW_ASSIST = ROW_USER + 2  # [APOLLO] deux lignes sous [VOUS]
CONTENT_LEFT = 2
CONTENT_RIGHT = 79     # 80 colonnes, on garde 1 colonne de marge
CONTENT_WIDTH = CONTENT_RIGHT - CONTENT_LEFT + 1
ROW_CONTENT_START = ROW_ASSIST + 1  # texte assistant commence sous le label
ROW_CONTENT_END = 22   # on réserve la 23 pour statut et 24 pour la saisie
ROW_STATUS = 23

def clear_area(ser, row_start, row_end):
    for r in range(row_start, row_end + 1):
        send(ser, seq_cup(r, 1)); send(ser, seq_el())

def wrap_lines(text, width):
    import textwrap
    out = []
    for para in text.split('\n'):
        out.extend(textwrap.wrap(para, width=width) or [''])
    return out

def wait_enter(ser):
    while True:
        b = ser.read(1)
        if not b:
            continue
        c = b.decode('latin1', errors='ignore')
        if c in ('\r', '\n'):
            return

def show_paged(ser, lines, row_start=ROW_CONTENT_START, row_end=ROW_CONTENT_END, left_col=CONTENT_LEFT):
    """Affiche lines avec pagination. Enter pour continuer, Q pour quitter l’affichage."""
    r = row_start
    i = 0
    total = len(lines)
    while i < total:
        # remplir la page
        clear_area(ser, row_start, row_end)
        r = row_start
        while i < total and r <= row_end:
            lp = LoopPlayer('typing_long.wav'); lp.start()
            send(ser, seq_cup(r, left_col)); send(ser, seq_el()); send(ser, lines[i][:CONTENT_WIDTH])
            r += 1; i += 1
            lp.stop_now()
        # statut
        if i < total:
            send(ser, seq_cup(ROW_STATUS, CONTENT_LEFT))
            send(ser, seq_el()); send(ser, "[Suite: ENVOI]  [Stop: Q]")
            # attendre entrée ou Q
            while True:
                b = ser.read(1)
                if not b:
                    continue
                ch = b.decode('latin1', errors='ignore')
                if ch in ('\r', '\n'):
                    break
                if ch.upper() == 'Q':
                    return
        else:
            # fin, efface statut
            send(ser, seq_cup(ROW_STATUS, 1)); send(ser, seq_el())
            return


# No real multi-level highlight on Minitel via text attributes.
# Keep a helper for border-only standout.

def draw_border_two_lines(ser, cols=COLS):
    # Top and bottom borders in standout, side borders too
    top = 1
    bottom = 2
    # full-width top
    send(ser, seq_cup(top, 1)); send(ser, seq_smso()); send(ser, ' ' * cols); send(ser, seq_rmso())
    # full-width bottom
    send(ser, seq_cup(bottom, 1)); send(ser, seq_smso()); send(ser, ' ' * cols); send(ser, seq_rmso())
    # left and right side on both lines
    for r in (top, bottom):
        send(ser, seq_cup(r, 1)); send(ser, seq_smso()); send(ser, ' '); send(ser, seq_rmso())
        send(ser, seq_cup(r, cols)); send(ser, seq_smso()); send(ser, ' '); send(ser, seq_rmso())

# Render layout once

def highlight_chars(ser, row, start_col, text, charset):
    # Overlay standout for selected characters only
    for i, ch in enumerate(text):
        if ch in charset:
            send(ser, seq_cup(row, start_col + i))
            send(ser, seq_smso()); send(ser, ch); send(ser, seq_rmso())

def render_layout(ser):
    init = tput('is2')
    if init: send(ser, init)
    send(ser, seq_clear())
    draw_border_two_lines(ser, COLS)

    # Draw border-only highlight around the 2-line fixed zone
    draw_border_two_lines(ser, COLS)

    # --- LIGNES 1 À 3 : titre, message, séparation ---

    # Choix direct dans le code
    HIGHLIGHT_LINE1 = True   # mettre False pour normal
    HIGHLIGHT_LINE2 = True  # mettre True pour highlight

    # ligne 1 : titre centré
    title = '#  -  A.P.O.L.L.O -                       CENTRAL ARTIFICIAL INTELLIGENCE'
    col = max(2, (COLS - len(title)) // 2 + 1)
    send(ser, seq_cup(1, col))
    if HIGHLIGHT_LINE1:
        lp = LoopPlayer('typing_long.wav'); lp.start()
        send(ser, seq_smso()); send(ser, title[:COLS-2]); send(ser, seq_rmso())
        lp.stop_now()
    else:
        lp = LoopPlayer('typing_long.wav'); lp.start()
        send(ser, title[:COLS-2])
        lp.stop_now()

    # ligne 2 : message
    msg = '================================'
    send(ser, seq_cup(2, 4))
    if HIGHLIGHT_LINE2:
        lp = LoopPlayer('typing_long.wav'); lp.start()
        send(ser, seq_smso()); send(ser, msg[:max(0, COLS-23)]); send(ser, seq_rmso())
        lp.stop_now()
    else:
        lp = LoopPlayer('typing_long.wav'); lp.start()
        send(ser, msg[:max(0, COLS-23)])
        lp.stop_now()

    # ligne 3 : séparation
    sep = '_' * (COLS - 2)
    send(ser, seq_cup(3, 2))
    send(ser, sep[:COLS-2])

    # Nettoie les zones d'affichage
    clear_area(ser, 4, ROW_STATUS)  # 4..23

    # boîte de saisie en ligne 24
    send(ser, seq_cup(LINES, 1)); send(ser, seq_el())
    send(ser, '[ENTER QUERY]'); send(ser, seq_cup(LINES, 15))
    ser.flush()
    time.sleep(0.02)   # 20 ms suffisent sur 1B à 4800 bauds

# Replacer le cuseur sur la ligne []
def reset_input_cursor(ser):
    send(ser, seq_cup(LINES, 1)); send(ser, seq_el())
    send(ser, '[ENTER QUERY]'); send(ser, seq_cup(LINES, 15))


# Simple input loop writing characters into the box and echoing them on the Minitel
def input_loop(ser, chat, debug=False):
    max_input = COLS - 15
    buffer = []
    col = 15
    send(ser, seq_cup(LINES, col))
    while True:
        b = ser.read(1)
        if debug and b:
            sys.stdout.write(f"[RX 0x{b[0]:02X}]"); sys.stdout.flush()
        if not b:
            continue
        c = b.decode('latin1', errors='ignore')

        # ENVOI
        if c in ('\r', '\n'):
            user_text = ''.join(buffer).strip()
            # nettoie la ligne d'entrée
            send(ser, seq_cup(LINES, 15)); send(ser, ' ' * max_input); send(ser, seq_cup(LINES, 15))
            buffer = []; col = 15

            if user_text:
                # 1) Ligne [VOUS] + question, côte à côte, une ligne plus haut (ROW_USER)
                send(ser, seq_cup(ROW_USER, CONTENT_LEFT)); send(ser, seq_el())
                send(ser, "[YOU] ")
                start_col = CONTENT_LEFT + len("[YOU] ")
                send(ser, seq_cup(ROW_USER, start_col));
                # question sur la même ligne, tronquée si trop longue
                send(ser, user_text[:CONTENT_WIDTH - len("[YOU] ")])

                # 2) Label [APOLLO] deux lignes dessous
                send(ser, seq_cup(ROW_ASSIST, CONTENT_LEFT)); send(ser, seq_el()); send(ser, "[APOLLO] ")

                # 3) Appel API + pagination de la réponse
                try:
                    lp = LoopPlayer('subtle_long_type.wav'); lp.start()
                    reply = chat.ask(user_text)
                    reply = sanitize_text(reply)
                    lp.stop_now()
                except Exception as e:
                    lp.stop_now()
                    reply = f"Erreur API: {e}"

                # texte assistant paginé sous le label
                lines = wrap_lines(reply, CONTENT_WIDTH)
                show_paged(ser, lines, row_start=ROW_CONTENT_START, row_end=ROW_CONTENT_END, left_col=CONTENT_LEFT); reset_input_cursor(ser)
            continue

        # RETOUR ARRIÈRE
        if ord(c) in (8, 127):
            if buffer:
                buffer.pop()
                col -= 1
                send(ser, seq_cup(LINES, col)); send(ser, ' '); send(ser, seq_cup(LINES, col))
            continue

        # imprimables
        if 32 <= ord(c) <= 126 and len(buffer) < max_input:
            buffer.append(c)
            send(ser, c)
            col += 1
            continue

# Noyau conversationnel OpenAI

class ChatCore:
    def __init__(self, model, prompt_file):
        self.client = OpenAI()  # lit OPENAI_API_KEY
        sys_prompt = Path(prompt_file).read_text(encoding='utf-8').strip() if prompt_file and Path(prompt_file).exists() else ""
        self.model = model
        self.history = []
        if sys_prompt:
            self.history.append({"role": "system", "content": sys_prompt})

    def ask(self, user_text):
        # mémorise
        self.history.append({"role": "user", "content": user_text})
        # Vous pouvez utiliser soit Chat Completions soit Responses.
        # Version Chat Completions (simple et stable) :
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=self.history,
        )  # API doc: chat.completions.create :contentReference[oaicite:2]{index=2}
        reply = resp.choices[0].message.content.strip()
        # mémorise la réponse
        self.history.append({"role": "assistant", "content": reply})
        # borne la mémoire pour éviter l’enflure
        if len(self.history) > 40:
            # garde le system + 38 derniers tours
            self.history = [self.history[0]] + self.history[-38:]
        return reply
# Main

def main():
    global TERMNAME  # declare first to avoid SyntaxError
    parser = argparse.ArgumentParser(description='Minitel UI')
    parser.add_argument('--device', default=SERIAL_DEVICE)
    parser.add_argument('--baud', type=int, default=BAUD)
    parser.add_argument('--term', default=None)
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--model', default='gpt-5-mini')  # exigé
    parser.add_argument('--prompt-file', default='prompt.txt')
    args = parser.parse_args()

    # set TERMNAME from arg or keep existing default
    if args.term:
        TERMNAME = args.term

    # open serial
    ser = serial.Serial(
        args.device,
        baudrate=args.baud,
        bytesize=serial.SEVENBITS,
        parity=serial.PARITY_EVEN,
        stopbits=serial.STOPBITS_ONE,
        xonxoff=True,
        rtscts=False,
        dsrdtr=False,
        timeout=0.1,
        write_timeout=1.0,
        inter_byte_timeout=0.05,

    )

    chat = ChatCore(model=args.model, prompt_file=args.prompt_file)

    try:
        render_layout(ser)
        print('Layout sent to Minitel. Entering input loop. Ctrl-C to exit.')
        input_loop(ser, chat, debug=args.debug)
    except KeyboardInterrupt:
        print('Exiting.')
    finally:
        ser.close()


if __name__ == '__main__':
    main()
