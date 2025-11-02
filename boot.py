#!/usr/bin/env python3
# -*- coding: latin-1 -*-

import os, sys, time, argparse, subprocess, threading, serial

# ---------- Config par défaut ----------
PAGE_CHUNK = 32
PAGE_GAP   = 0.01
COLS = 80
LINES = 24
SCROLL_DELAY = 0.1  # vitesse du défilement logo
PROMPT = "BOOT ? (Y/N) : "

# ---------- terminfo helpers ----------
TERMNAME = os.environ.get('MINITEL_TERM', 'minitel1b-80')

def tput(name, *args):
    cmd = ['tput', '-T', TERMNAME, name]
    if args: cmd += [str(a) for a in args]
    try:
        return subprocess.check_output(cmd)
    except subprocess.CalledProcessError:
        return b''

def send(ser, data):
    if isinstance(data, str):
        data = data.encode('latin-1', errors='ignore')
    for i in range(0, len(data), PAGE_CHUNK):
        ser.write(data[i:i+PAGE_CHUNK])
        ser.flush()
        time.sleep(PAGE_GAP)

def seq_clear():
    s = tput('clear')
    return s if s else b"\x1b[2J\x1b[H"

def seq_cup(r, c):
    s = tput('cup', r-1, c-1)
    return s if s else f"\x1b[{r};{c}H".encode()

def seq_el():
    s = tput('el')
    return s if s else b"\x1b[K"

def seq_dl1():
    s = tput('dl1')
    return s if s else b"\x1b[M"

def seq_civis():
    s = tput('civis'); return s if s else b""

def seq_cnorm():
    s = tput('cnorm'); return s if s else b""

# ---------- utilitaires audio (aplay) ----------
class LoopPlayer:
    def __init__(self, wav_path):
        self.wav = wav_path
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.stop.is_set():
            try:
                p = subprocess.Popen(['aplay', '-q', self.wav])
                # boucle courte: on surveille pour pouvoir couper vite
                while p.poll() is None and not self.stop.is_set():
                    time.sleep(0.05)
                if p.poll() is None and self.stop.is_set():
                    p.terminate()
            except FileNotFoundError:
                # aplay absent
                break

    def start(self):
        self.thread.start()

    def stop_now(self):
        self.stop.set()
        self.thread.join(timeout=1.0)

def play_once(wav_path):
    try:
        subprocess.call(['aplay', '-q', wav_path])
    except FileNotFoundError:
        pass

# ---------- I/O Minitel ----------
def clear_screen(ser):
    send(ser, seq_clear())

def read_line(ser, echo=True, maxlen=16):
    buf = []
    while True:
        b = ser.read(1)
        if not b:
            continue
        ch = b.decode('latin-1', errors='ignore')
        if ch in ('\r', '\n'):
            return ''.join(buf)
        if ord(ch) in (8, 127):  # backspace
            if buf:
                buf.pop()
                if echo:
                    send(ser, '\b \b')
            continue
        if 32 <= ord(ch) <= 126 and len(buf) < maxlen:
            buf.append(ch)
            if echo: send(ser, ch)

def show_art(ser, art_path):
    try:
        with open(art_path, 'r', encoding='latin-1', errors='ignore') as f:
            lines = f.read().splitlines()
    except Exception:
        lines = ["[art.txt introuvable]"]
    # écrire sur 1..(LINES-1), couper à COLS
    top = 1
    bottom = LINES - 1
    for r in range(top, bottom+1):
        ln = lines[r - top] if r - top < len(lines) else ""
        ln = ln[:COLS]
        send(ser, seq_cup(r, 1)); send(ser, seq_el()); send(ser, ln)

def ask_boot(ser):
    send(ser, seq_cup(LINES,1)); send(ser, seq_el())
    send(ser, seq_cup(LINES,1)); send(ser, PROMPT)
    ans = read_line(ser, echo=True, maxlen=3).strip().upper()
    return ans

# ---------- Défilement du logo ----------
def scroll_logo(ser, logo_path, typing_wav):
    try:
        with open(logo_path, 'r', encoding='latin-1', errors='ignore') as f:
            lines = f.read().splitlines()
    except Exception:
        lines = ["[logo.txt introuvable]"]

    # Fenêtre 1..(LINES-1), on garde la dernière ligne libre
    top = 1
    bottom = LINES - 1

    # nettoyer la fenêtre
    for r in range(top, bottom+1):
        send(ser, seq_cup(r,1)); send(ser, seq_el())

    send(ser, seq_civis())
    lp = LoopPlayer(typing_wav)
    lp.start()

    filled = 0
    window = bottom - top + 1
    for raw in lines:
        ln = raw[:COLS]
        if filled < window:
            row = top + filled
            send(ser, seq_cup(row,1)); send(ser, seq_el()); send(ser, ln)
            filled += 1
        else:
            # supprimer la première ligne puis écrire en bas
            send(ser, seq_cup(top,1)); send(ser, seq_dl1())
            send(ser, seq_cup(bottom,1)); send(ser, seq_el()); send(ser, ln)
        time.sleep(SCROLL_DELAY)

    lp.stop_now()
    send(ser, seq_cnorm())

# ---------- Barre de chargement 10s ----------
def loading_10s(ser, rattle_wav, seconds=10):
    lp = LoopPlayer(rattle_wav)
    lp.start()
    start = time.time()
    bar_len = COLS
    last_pct = -1
    while True:
        elapsed = time.time() - start
        if elapsed > seconds: break
        pct = int((elapsed/seconds)*100)
        if pct != last_pct:
            filled = int((pct/100.0)*bar_len)
            bar = ('#'*filled).ljust(bar_len)
            send(ser, seq_cup(LINES,1)); send(ser, bar[:COLS])
            last_pct = pct
        time.sleep(0.05)
    send(ser, seq_cup(LINES,1)); send(ser, '#' * COLS)
    lp.stop_now()

# ---------- Lancement terminal.py ----------
def run_terminal_py(ser, device, baud):
    here = os.path.dirname(os.path.abspath(__file__))
    term_py = os.path.join(here, 'terminal.py')
    if not os.path.isfile(term_py):
        # message d’erreur en bas, puis retour au prompt
        send(ser, seq_cup(LINES,1)); send(ser, seq_el())
        send(ser, "[terminal.py introuvable]")
        time.sleep(2)
        return
    # libérer le port pour terminal.py
    ser.close()
    env = os.environ.copy()
    args = [sys.executable, term_py, '--device', device, '--baud', str(baud), '--term', TERMNAME]
    subprocess.call(args, env=env)
    # si terminal.py se termine, on ne relance pas automatiquement ici

# ---------- Programme principal ----------
def main():
    parser = argparse.ArgumentParser(description="Boot Minitel 1B simple")
    parser.add_argument('--device', default='/dev/ttyUSB0')
    parser.add_argument('--baud', type=int, default=4800)
    parser.add_argument('--boot-snd', default='boot.wav')
    parser.add_argument('--beep-snd', default='beep.wav')
    parser.add_argument('--type-snd', default='typing_long.wav')
    parser.add_argument('--subtlelong-snd', default='subtle_long_type.wav')
    parser.add_argument('--final-snd', default='horn.wav')
    parser.add_argument('--art', default='art.txt')
    parser.add_argument('--logo', default='logo.txt')
    parser.add_argument('--term', default=None)
    args = parser.parse_args()

    ser = serial.Serial(
        args.device,
        baudrate=args.baud,
        bytesize=serial.SEVENBITS,
        parity=serial.PARITY_EVEN,
        stopbits=serial.STOPBITS_ONE,
        xonxoff=True,
        timeout=0.1
    )

    try:
        while True:
            # 1) Nettoyer l'écran + son de boot
            clear_screen(ser)
            show_art(ser, args.art)
            play_once(args.boot_snd)

            # 2) Prompt BOOT ? (Y/N)
            ans = ask_boot(ser)
            if ans == 'Y':
                # Nettoyer + beep choisi
                clear_screen(ser)
                play_once(args.beep_snd)

                # Défilement logo avec bruit de frappe en boucle
                scroll_logo(ser, args.logo, args.type_snd)

                # Chargement 10s sur dernière ligne avec subtle-long-type en boucle
                loading_10s(ser, args.subtlelong_snd, seconds=2)

                # Son final choisi puis lancement terminal.py
                play_once(args.final_snd)
                run_terminal_py(ser, args.device, args.baud)
                # Après retour éventuel de terminal.py, on recommence le cycle
                continue
            else:
                # Toute réponse différente de Y => redémarrage immédiat
                # Effacer et réafficher le prompt
                clear_screen(ser)
                # boucle while True redonne le prompt
                continue
    except KeyboardInterrupt:
        pass
    finally:
        try: ser.close()
        except: pass

if __name__ == '__main__':
    main()
