# app.py
# DC-5 Box Generator + Best Straight Picker
from __future__ import annotations
import json, io
from itertools import combinations_with_replacement, permutations
from collections import Counter
import streamlit as st

st.set_page_config(page_title="DC-5: Constrained Boxes → Best Straight(s)", layout="wide")
st.title("DC-5: Constrained Boxes → Best Straight(s)")

LOW_MAX_DEFAULT = 4
EPS = 1e-15

# -------------------- Parsers & helpers --------------------
def parse_mandatory_digits(s: str) -> list[int]:
    out, seen = [], set()
    for t in (s or "").replace(",", " ").split():
        if t.isdigit():
            d = int(t)
            if 0 <= d <= 9 and d not in seen:
                out.append(d); seen.add(d)
    return out

def parse_forbidden_digits(s: str) -> set[int]:
    out = set()
    for t in (s or "").replace(",", " ").split():
        if t.isdigit():
            d = int(t)
            if 0 <= d <= 9:
                out.add(d)
    return out

def longest_consecutive_run_length(uniq_sorted: list[int]) -> int:
    if not uniq_sorted: return 0
    run = best = 1
    for i in range(1, len(uniq_sorted)):
        if uniq_sorted[i] == uniq_sorted[i-1] + 1:
            run += 1; best = max(best, run)
        else:
            run = 1
    return best

def violates_patterns(counts: Counter, allow_quints, allow_quads, allow_triples, allow_double_doubles):
    vals = list(counts.values())
    if not allow_quints and any(v == 5 for v in vals): return True
    if not allow_quads  and any(v == 4 for v in vals): return True
    if not allow_triples and any(v == 3 for v in vals): return True
    pairs = sum(1 for v in vals if v == 2)
    if not allow_double_doubles and pairs >= 2: return True
    return False

def normalize_row(row):
    s = sum(row)
    if
