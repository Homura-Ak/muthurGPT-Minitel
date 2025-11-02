#!/usr/bin/env python3
# -*- coding: latin-1 -*-

import os, sys, time, argparse, subprocess, threading, serial

# ---------- Config par défaut ----------
PAGE_CHUNK = 32
PAGE_GAP   = 0.01
COLS = 80
LINES = 24
SCROLL_DELAY = 0.1
PROMPT = "LAUNCH ? (Y/N) : "

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
                while p.poll() is None and not self.stop.is_set():
                    time.sleep(0.05)
                if p.poll() is None and self.stop.is_set():
                    p.terminate()
            except FileNotFoundError:
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
        if ord(ch) in (8, 127):
            if buf:
                buf.pop()
                if echo:
                    send(ser, '\b \b')
            continue
        if 32 <= ord(ch) <= 126 and len(buf) < maxlen:
            buf.append(ch)
            if echo: send(ser, ch)

def ask_boot(ser):
    send(ser, seq_cup(LINES,1)); send(ser, seq_el())
    send(ser, seq_cup(LINES,1)); send(ser, PROMPT)
    ans = read_line(ser, echo=True, maxlen=4).strip().lower()
    return ans

# ---------- Défilement générique d'un fichier texte avec son ----------
def scroll_text(ser, path, typing_wav, not_found_msg):
    try:
        with open(path, 'r', encoding='latin-1', errors='ignore') as f:
            lines = f.read().splitlines()
    except Exception:
        lines = [not_found_msg]

    top = 1
    bottom = LINES - 1

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
    term_py = os.path.join(here, 'apollo-gpt.py')
    if not os.path.isfile(term_py):
        send(ser, seq_cup(LINES,1)); send(ser, seq_el())
        send(ser, "[terminal.py introuvable]")
        time.sleep(2)
        return
    ser.close()
    env = os.environ.copy()
    args = [sys.executable, term_py, '--device', device, '--baud', str(baud), '--term', TERMNAME]
    subprocess.call(args, env=env)

# ---------- Programme principal ----------
def main():
    parser = argparse.ArgumentParser(description="Boot Minitel 1B simple")
    parser.add_argument('--device', default='/dev/ttyUSB0')
    parser.add_argument('--baud', type=int, default=4800)
    parser.add_argument('--boot-snd', default='boot.wav')
    parser.add_argument('--beep-snd', default='beep.wav')
    parser.add_argument('--type-snd', default='typing_long.wav')  # utilisé pour logo ET boot
    parser.add_argument('--subtlelong-snd', default='subtle_long_type.wav')
    parser.add_argument('--final-snd', default='horn.wav')
    parser.add_argument('--logo', default='1.txt')
    parser.add_argument('--boottxt', default='boot.txt')
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
            # 1) Nettoyer + son de boot + logo avec son de frappe
            clear_screen(ser)
            play_once(args.boot_snd)
            scroll_text(ser, args.logo, args.type_snd, "[1.txt introuvable]")

            # 2) Prompt
            ans = ask_boot(ser)

            # 3) Sortie si N
            if ans in ('n', 'no', 'non'):
                break

            if ans == 'y':
                # Nettoie + beep
                clear_screen(ser)
                play_once(args.beep_snd)

                # 4) boot.txt défilant avec le même son de frappe
                scroll_text(ser, args.boottxt, args.type_snd, "[boot.txt introuvable]")

                # 5) Chargement
                loading_10s(ser, args.subtlelong_snd, seconds=10)

                # 6) Son final puis terminal
                play_once(args.final_snd)
                run_terminal_py(ser, args.device, args.baud)
                continue
            else:
                # Réponse invalide => réafficher le prompt
                send(ser, seq_cup(LINES,1)); send(ser, seq_el())
                continue
    except KeyboardInterrupt:
        pass
    finally:
        try: ser.close()
        except: pass

if __name__ == '__main__':
    main()
