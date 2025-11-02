# infocmp minitel1b-80

# Pour lancer le programme :
# python -m venv venv
# source venv/bin/activate
# pip install pyserial
# python apollo.py --device /dev/ttyUSB0 --baud 4800 --term minitel1b-80

#!/usr/bin/env python3
"""
minitel_ui.py

Contrôle simple du Minitel 1B via port série.
- Envoie la mise en page demandée.
- Lit les touches du Minitel et fournit un encart d'écriture en ligne 24.

Prérequis: pyserial, tic compilé pour le terminfo fourni.
Configurez TERMNAME si vous avez compilé l'entry avec un autre nom.

Usage:
  python3 minitel_ui.py --device /dev/ttyUSB0

Explications minimales inline.
"""

import os
import sys
import time
import argparse
import subprocess
import serial

# CONFIG
TERMNAME = os.environ.get('MINITEL_TERM', 'minitel')  # change if your terminfo entry has another name
SERIAL_DEVICE = '/dev/ttyUSB0'
BAUD = 4800
COLS = 80
LINES = 24

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
        b = b.encode('latin1')
    ser.write(b)
    ser.flush()

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
    # optional terminal init from terminfo if available
    init = tput('is2')
    if init:
        send(ser, init)
    send(ser, seq_clear())

    # Draw border-only highlight around the 2-line fixed zone
    draw_border_two_lines(ser, COLS)

    # --- LIGNES 1 À 3 : titre, message, séparation ---

    # Choix direct dans le code
    HIGHLIGHT_LINE1 = True   # mettre False pour normal
    HIGHLIGHT_LINE2 = True  # mettre True pour highlight

    # ligne 1 : titre centré
    title = '#  -  A.P.O.L.L.O                          CENTRAL ARTIFICIAL INTELLIGENCE'
    col = max(2, (COLS - len(title)) // 2 + 1)
    send(ser, seq_cup(1, col))
    if HIGHLIGHT_LINE1:
        send(ser, seq_smso()); send(ser, title[:COLS-2]); send(ser, seq_rmso())
    else:
        send(ser, title[:COLS-2])

    # ligne 2 : message
    msg = '================='
    send(ser, seq_cup(2, 4))
    if HIGHLIGHT_LINE2:
        send(ser, seq_smso()); send(ser, msg[:max(0, COLS-23)]); send(ser, seq_rmso())
    else:
        send(ser, msg[:max(0, COLS-23)])

    # ligne 3 : séparation
    sep = '_' * (COLS - 2)
    send(ser, seq_cup(3, 2))
    send(ser, sep[:COLS-2])


    # prepare input box at line 24
    send(ser, seq_cup(LINES, 1))
    send(ser, seq_el())
    send(ser, '[ENTER QUERY]')  # a small box indicator; cursor will be placed after
    send(ser, seq_cup(LINES, 14))

# Simple input loop writing characters into the box and echoing them on the Minitel
def input_loop(ser, debug=False):
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
        code = ord(c)
        # handle Enter (NL or CR)
        if c in ('\r', '\n'):
            # process the input (here we simply echo on line 6)
            send(ser, seq_cup(6, 1))
            send(ser, seq_el())
            send(ser, b"You typed: ")
            send(ser, ''.join(buffer).encode('latin1'))
            buffer = []
            # clear input box
            send(ser, seq_cup(LINES, 15))
            send(ser, ' ' * max_input)
            send(ser, seq_cup(LINES, 15))
            col = 4
            continue
        # Backspace (DEL 127 or BS 8)
        if ord(c) in (8, 127):
            if buffer:
                buffer.pop()
                col -= 1
                send(ser, seq_cup(LINES, col))
                send(ser, ' ')
                send(ser, seq_cup(LINES, col))
            continue
        # printable
        if 32 <= ord(c) <= 126 and len(buffer) < max_input:
            buffer.append(c)
            send(ser, c)
            col += 1
            continue
        # other control: ignore


def main():
    global TERMNAME  # declare first to avoid SyntaxError
    parser = argparse.ArgumentParser(description='Minitel UI')
    parser.add_argument('--device', default=SERIAL_DEVICE)
    parser.add_argument('--baud', type=int, default=BAUD)
    parser.add_argument('--term', default=None)
    parser.add_argument('--debug', action='store_true')
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
        timeout=0.1
    )
    try:
        render_layout(ser)
        print('Layout sent to Minitel. Entering input loop. Ctrl-C to exit.')
        input_loop(ser, debug=args.debug)
    except KeyboardInterrupt:
        print('Exiting.')
    finally:
        ser.close()


if __name__ == '__main__':
    main()
    main()
