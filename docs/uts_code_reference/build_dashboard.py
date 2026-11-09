#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gabungkan results.json + dashboard_template.html -> satu file HTML mandiri (100% offline)."""
import argparse, json, os

ap = argparse.ArgumentParser()
ap.add_argument("--results", default="results.json")
ap.add_argument("--template", default="dashboard_template.html")
ap.add_argument("--out", default="UTS_25110200036_AnindyaRahmaLuthfia.html")
a = ap.parse_args()

d = json.loads(open(a.results, encoding="utf-8").read())
def rd(f):
    return open(f, encoding="utf-8").read().strip() if os.path.exists(f) else ""
d["statements"] = {"pernyataan": rd("pernyataan_ai.txt"), "refleksi": rd("refleksi.txt")}
data = json.dumps(d, separators=(",", ":"), ensure_ascii=False)
data = data.replace("</", "<\\/")
html = open(a.template, encoding="utf-8").read().replace("__DATA__", data)
open(a.out, "w", encoding="utf-8").write(html)
print("OK -> %s (%.1f KB)" % (a.out, len(html) / 1024))
