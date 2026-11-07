#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kestrel 3.12 - the old start file. Since 3.12 the bot is split into files and starts from main.py:

    main.py          the bot and the app window (settings at the top)
    IB.py            market data (IB Gateway)
    Tradezero.py     orders, positions, locates (TradeZero)
    kestrel_discord.py    Discord messages and chart pictures
    jay_read_short.py, max_squeeze_short.py, lh_long_premarket.py   the strategies

Keep them all in one folder. "python kestrel_app.py" still works: it starts main.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    import main
    main.main()
