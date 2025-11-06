## Overview

**muthurGPT-Minitel** is a chat bot that simulates an onboard computer such as MU/TH/UR or APOLLO for Alien RPG or other TTRPGs. I was only made for running of a Minitel. Maybe it can work on any dumb terminal but I didn't tested it.

It runs via OpenAI's API, and requires that you make a paid account with them to run. These are charged by OpenAI per token.

This is a modified version of the original program, adapted to run on Minitel. It was built in a single day to play the "Destroyer of Worlds" campaign, which explains why the computer here is named APOLLO.

## Video
[Reddit video of muthurGPT in action](https://www.reddit.com/r/alienrpg/comments/1nmb625/comment/nmdcn6p/?context=1)

## Setup

### Suggested hardware
Recommend using at least a Minitel 1B configured in 80-column mode, with local echo disabled and the 4800 baud mode enabled. The program should run on any model of Raspberry Pi using the official OS. Use a USB Male to DIN 5-Pin RS232 UART TTL adapter cable (tested with an FT232RL controller): [Link](https://www.ebay.com/itm/315958961464) (Not affiliated)

### Preparation

Retrieve the terminfo file from:  
http://canal.chez.com/terminfo.htm  

Install the terminfo on your system so that the terminal type `minitel1b-80` is recognized.

Copy the `.env.example` file and modify it as needed for your setup.

## Installation and launch

This project runs entirely in Python. It’s best to use a virtual environment for isolation.

1. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
````

2. Install the required packages:

   ```bash
   pip install pyserial openai python-dotenv
   ```

3. To start the program:

   ```bash
   python boot.py --device /dev/ttyUSB0 --baud 4800 --term minitel1b-80
   ```

For continuous operation, you can use a systemd service:

```ini
[Unit]
Description=Boot Minitel 1B
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/muthur/minitel
ExecStart=/home/muthur/minitel/venv/bin/python /home/muthur/minitel/boot.py --device /dev/ttyUSB0 --baud 4800 --term minitel1b-80
Restart=always
User=muthur
Group=muthur
Environment=MINITEL_TERM=minitel1b-80
ExecStartPre=/usr/bin/amixer set PCM 80%

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl enable minitel.service
sudo systemctl start minitel.service
```

### Config

#### OpenAI key and model

Copy the `.env.example` file and modify it as needed for your setup. To change your OpenAI API key, edit the `.env` file. To change the model, edit the `apollo-gpt` file and modify the line `parser.add_argument('--model', default='gpt-5-mini')  # required`. The `gpt-5-mini` model is used because it’s inexpensive and performs well for this project, while the `gpt-5-nano` model is cheaper but does not follow prompts reliably.


## How to use ?

## Outstanding work (in vague order of priority)
- Clean the code, it's so ugly sorry.
- Better use of .env
- Support of plugins
