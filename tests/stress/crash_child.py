"""One pf command that kills itself at its Nth SQL statement (D-077 point 5, the M21.2 slice plan
point 2). Usage: crash_child.py KILL_AT COUNT_FILE pf-words...

KILL_AT 0 never kills: the command runs to its end and the number of statements it ran is written
to COUNT_FILE. Every connection any module opens gets the trace callback, because sqlite3.connect
is wrapped before personal_finance is imported. uuid4 counts from a fixed start, so two runs of
the same command on copies of one ledger make the same IDs. Nothing in src/ knows about this."""

import itertools
import os
import signal
import sqlite3
import sys
import uuid
from pathlib import Path

kill_at, count_file, words = int(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:]
statements = itertools.count(1)
ran = [0]
real_connect = sqlite3.connect


def traced(*arguments, **options):
    conn = real_connect(*arguments, **options)

    def on_statement(_):
        ran[0] = next(statements)
        if ran[0] == kill_at:
            os.kill(os.getpid(), signal.SIGKILL)

    conn.set_trace_callback(on_statement)
    return conn


sqlite3.connect = traced
ids = itertools.count(1)
uuid.uuid4 = lambda: uuid.UUID(int=(0x4000 << 64) | (0x8 << 60) | next(ids), version=4)

from personal_finance.cli import main  # noqa: E402

code = main(words)
count_file.write_text(str(ran[0]))
sys.exit(code)
