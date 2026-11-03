"""LH Short Bot 3.14 - chart notes (core/data/chart_notes.py). No network: "Turso" here is a throwaway SQLite file
(TURSO_DATABASE_URL=file:...), and two temporary folders play two PCs. Run from the bot folder:
    python tests/test_chart_notes.py

1  save / edit / delete on one PC, and the same notes seen on a second PC through Turso
2  Turso down: the note is kept on this PC (pending) and sent when Turso answers again
3  the backtest's old per-strategy notes move into the chart notes once (verdicts stay, nothing is lost)
4  bad input is refused
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="lh_notes_test_")
os.environ["TURSO_DATABASE_URL"] = "file:" + os.path.join(TMP, "cloud.db")     # never the real database
os.environ["TURSO_AUTH_TOKEN"] = "test"
for p in (os.path.join(ROOT, "core", "data"), os.path.join(ROOT, "core", "backtest_engine")):
    sys.path.insert(0, p)
import turso                                                                     # noqa: E402
import chart_notes                                                               # noqa: E402

ok_n = fail_n = 0


def check(name, cond, info=""):
    global ok_n, fail_n
    if cond:
        ok_n += 1
        print(f"  ok    {name}")
    else:
        fail_n += 1
        print(f"  FAIL  {name} {info}")


def cloud_rows(sql, args=()):
    return turso.cloud().execute(sql, args)


pc1, pc2 = os.path.join(TMP, "pc1"), os.path.join(TMP, "pc2")
os.makedirs(pc1)
os.makedirs(pc2)
A, B = chart_notes.Store(pc1), chart_notes.Store(pc2)
T = 1762080000 + 10 * 3600 + 42 * 60                                             # 2025-11-02 10:42 "ET as UTC"

print("1 save, edit, delete, two PCs")
n1 = A.save("weto", "2026-11-02", T, 7.4162, "  wait for the bounce at 11  ", src="live")
check("saved with a cleaned ticker and text", n1["tk"] == "WETO" and n1["text"] == "wait for the bounce at 11" and n1["t"] == T)
check("sent to Turso", A.send() and len(cloud_rows("SELECT id FROM chart_notes WHERE tk='WETO'")) == 1)
check("in this PC's file", n1["id"] in json.load(open(os.path.join(pc1, "chart_notes.json")))["notes"])
time.sleep(1.1)
n2 = A.save("WETO", "2026-11-02", T + 300, 8.0, "second note", src="backtest")
e1 = A.save("WETO", "2026-11-02", text="wait for the bounce at 11.00", nid=n1["id"])
check("edit keeps the id, the pin and the creation time", e1["id"] == n1["id"] and e1["t"] == T and e1["created"] == n1["created"]
      and e1["text"].endswith("11.00"))
A.send()
seen = B.for_ticker("WETO")
check("the other PC sees both notes, oldest first", [n["id"] for n in seen] == [n1["id"], n2["id"]], seen)
check("... with the edited text", seen[0]["text"] == "wait for the bounce at 11.00")
check("other tickers are not mixed in", B.for_ticker("AZTR") == [])
A.delete(n2["id"])
A.send()
check("a delete reaches the other PC", [n["id"] for n in B.for_ticker("WETO")] == [n1["id"]])
check("everything() groups by ticker-day", list(B.everything()) == ["WETO|2026-11-02"])

print("2 Turso not reachable")
real = chart_notes._cloud
chart_notes._cloud = lambda: None
off = A.save("AZTR", "2026-11-03", T, 3.2, "written while offline")
check("saved on this PC", any(n["id"] == off["id"] for n in A.for_ticker("AZTR")))
check("kept as pending", off["id"] in A.pending and not A.send())
check("not in Turso yet", cloud_rows("SELECT id FROM chart_notes WHERE id=?", (off["id"],)) == [])
A2 = chart_notes.Store(pc1)                                                      # the app restarts while offline
check("still pending after a restart", off["id"] in A2.pending)
chart_notes._cloud = real
check("sent once Turso answers", A2.send() and cloud_rows("SELECT text FROM chart_notes WHERE id=?", (off["id"],)) ==
      [("written while offline",)])
check("nothing pending any more", not A2.pending)
chart_notes._cloud = lambda: None
B.save("AZTR", "2026-11-03", T, 3.3, "pc2 offline note")
A2.delete(off["id"])
chart_notes._cloud = real
check("a refresh keeps a note not sent yet", any(n["text"] == "pc2 offline note" for n in B.for_ticker("AZTR")))
B.send()
A2.send()
check("both PCs end with the same notes", [n["text"] for n in A2.for_ticker("AZTR")] == ["pc2 offline note"]
      == [n["text"] for n in B.for_ticker("AZTR")])

print("3 the backtest's old notes move over")
import lh_backtest as LB                                                          # noqa: E402
LB.BT_DIR = os.path.join(TMP, "backtest")
os.makedirs(os.path.join(LB.BT_DIR, "jay_read_2"))
LB.notes_save("jay_read_2", "RDAC", "2026-11-03", verdict="Good trade")
LB.notes_save("jay_read_2", "RDAC", "2026-11-03", text="faded from the open", px=10.26, hms="09:41:00")
LB.notes_save("jay_read_2", "RDAC", "2026-11-03", text="no pin")
LB.notes_save("jay_read_2", "PARA", "2026-11-03", text="spiker")
moved = LB.notes_move("jay_read_2", A2)
rd = [n for n in A2.for_ticker("RDAC") if n["day"] == "2026-11-03"]
check("3 notes moved", moved == 3, moved)
check("pinned to its candle and price", rd[0]["text"] == "faded from the open" and rd[0]["px"] == 10.26
      and time.strftime("%Y-%m-%d %H:%M", time.gmtime(rd[0]["t"])) == "2026-11-03 09:41")
check("an unpinned note stays unpinned", rd[1]["t"] is None and rd[1]["text"] == "no pin")
check("the verdict stays with the strategy", LB.notes_get("jay_read_2", "RDAC", "2026-11-03") == {"verdict": "Good trade", "notes": []})
check("a ticker-day with only notes is gone from the old store", LB.notes_get("jay_read_2", "PARA", "2026-11-03")["notes"] == [])
check("running it again moves nothing twice", LB.notes_move("jay_read_2", A2) == 0 and len(A2.for_ticker("RDAC")) == 2)
A2.send()
check("the moved notes reach Turso", len(cloud_rows("SELECT id FROM chart_notes WHERE tk='RDAC'")) == 2)

print("4 bad input")
for name, kw in (("empty text", dict(tk="WETO", day="2026-11-02", text="   ")),
                 ("not a ticker", dict(tk="WE'TO;--", day="2026-11-02", text="x")),
                 ("not a day", dict(tk="WETO", day="11/02/2026", text="x")),
                 ("an edit of a deleted note", dict(tk="WETO", day="2026-11-02", text="x", nid="nope"))):
    try:
        A2.save(**kw)
        check(f"{name} is refused", False)
    except ValueError:
        check(f"{name} is refused", True)
check("a long note is cut at 4000 characters", len(A2.save("WETO", "2026-11-02", text="x" * 5000)["text"]) == 4000)

turso.reset()
shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{ok_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
