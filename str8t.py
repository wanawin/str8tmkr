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
    if 99.5 <= s <= 100.5:   return [x/100.0 for x in row]
    if 0.99  <= s <= 1.01:   return row
    if s > 0:                return [x/s for x in row]
    return row

def parse_positional_stats(text: str) -> dict[int, list[float]]:
    """
    Accept JSON or shorthand:
      JSON: {"p1":{"0":28.57,...}, ...}
      SH:   p1: 4:28.57, 7:28.57, 0:28.57, 2:14.29; p2: 9:28.57, ...
      (shorthand can be multi-line)
    Returns {1:[p0..p9], ..., 5:[p0..p9]} with probabilities in [0,1].
    """
    text = (text or "").strip()
    if not text:
        return {}
    # Try JSON first
    try:
        obj = json.loads(text)
        out = {}
        for k in ("p1","p2","p3","p4","p5"):
            if k not in obj:
                raise ValueError(f"Missing key '{k}' in JSON.")
            row = [float(obj[k].get(str(d), 0.0)) for d in range(10)]
            out[int(k[1])] = normalize_row(row)
        return out
    except json.JSONDecodeError:
        pass

    # Shorthand: tolerate newlines by converting to semicolons
    out = {}
    segments = [seg.strip() for seg in text.replace("\n",";").split(";") if seg.strip()]
    for seg in segments:
        if ":" not in seg: continue
        head, tail = seg.split(":", 1)
        head = head.strip().lower()
        if not (len(head) == 2 and head[0] == "p" and head[1] in "12345"): continue
        pos = int(head[1]); row = [0.0]*10
        for chunk in tail.split(","):
            chunk = chunk.strip()
            if not chunk: continue
            if ":" in chunk:
                d_str, v_str = [x.strip() for x in chunk.split(":", 1)]
            else:
                parts = chunk.split()
                if len(parts) != 2: continue
                d_str, v_str = parts
            if d_str.isdigit():
                d = int(d_str)
                if 0 <= d <= 9:
                    try: v = float(v_str.replace("%",""))
                    except: v = 0.0
                    row[d] = v
        out[pos] = normalize_row(row)
    if len(out) != 5:
        raise ValueError("Provide p1..p5 positional rows.")
    return out

def prod_score(straight, pos_probs: dict[int, list[float]]) -> float:
    s = 1.0
    for i, d in enumerate(straight, start=1):
        s *= pos_probs.get(i, [0.0]*10)[d]
    return s

def add_score(straight, pos_probs: dict[int, list[float]]) -> float:
    return sum(pos_probs.get(i, [0.0]*10)[d] for i, d in enumerate(straight, start=1))

# -------------------- Sidebar: constraints --------------------
st.sidebar.header("Constraints")

sum_min, sum_max = st.sidebar.slider("Sum range", 0, 45, (0, 45))
low_max = st.sidebar.number_input("Low max digit (low ≤ this value)", 0, 9, LOW_MAX_DEFAULT, 1)

mand_str = st.sidebar.text_input("Mandatory digits (OR logic: at least one must appear)",
                                 help="Comma/space-separated digits, e.g. 7, 0, 2")
mand_digits = parse_mandatory_digits(mand_str)

forbid_str = st.sidebar.text_input("Do NOT use these digits (optional)",
                                   help="Comma/space-separated digits (e.g. 8, 9). Any box containing them will not be generated.")
forbid_digits = parse_forbidden_digits(forbid_str)

st.sidebar.markdown("**H/L/E/O minimums & maximums (defaults: min=2, max=5)**")
c1, c2 = st.sidebar.columns(2)
min_low  = c1.number_input(f"Min Low (≤ {low_max})", 0, 5, 2, 1)
max_low  = c2.number_input(f"Max Low (≤ {low_max})", 0, 5, 5, 1)
c3, c4 = st.sidebar.columns(2)
min_high = c3.number_input("Min High (≥ low_max+1)", 0, 5, 2, 1)
max_high = c4.number_input("Max High (≥ low_max+1)", 0, 5, 5, 1)
c5, c6 = st.sidebar.columns(2)
min_even = c5.number_input("Min Even", 0, 5, 2, 1)
max_even = c6.number_input("Max Even", 0, 5, 5, 1)
c7, c8 = st.sidebar.columns(2)
min_odd  = c7.number_input("Min Odd", 0, 5, 2, 1)
max_odd  = c8.number_input("Max Odd", 0, 5, 5, 1)

st.sidebar.markdown("**Pattern allowances** (check to allow; uncheck to filter out):")
allow_quints = st.sidebar.checkbox("Allow quints (aaaaa)", value=False)
allow_quads  = st.sidebar.checkbox("Allow quads  (aaaab)", value=False)
allow_triples= st.sidebar.checkbox("Allow triples (aaabc)", value=True)
allow_dd     = st.sidebar.checkbox("Allow double doubles (aabbc)", value=True)
allow_runs4p = st.sidebar.checkbox("Allow runs ≥4 (e.g., 1-2-3-4)", value=False)

st.sidebar.markdown("---")
st.sidebar.markdown("**Positional stats (optional, to pick best straight)**")
st.sidebar.caption(
    "Paste JSON with keys p1..p5 mapping digits 0..9 to % or prob. "
    'Example: {"p1":{"4":28.57,"7":28.57,"0":28.57,"2":14.29}, ...}  '
    "Or shorthand: p1: 4:28.57,7:28.57,0:28.57,2:14.29; p2: 9:28.57, ..."
)
pos_stats_text = st.sidebar.text_area("Positional stats", height=160, value="")

go = st.sidebar.button("Generate")

# -------------------- Debug tester --------------------
with st.expander("🔍 Debug a specific combo (why excluded?)"):
    test_combo_str = st.text_input("Enter a 5-digit combo to test (e.g., 23579)")
    if st.button("Test this combo"):
        if not (test_combo_str.isdigit() and len(test_combo_str) == 5):
            st.error("Please enter exactly 5 digits.")
        else:
            comb = tuple(sorted(int(c) for c in test_combo_str))
            s = sum(comb); counts = Counter(comb)
            msgs, ok = [], True
            if forbid_digits and any(d in forbid_digits for d in comb):
                ok = False; msgs.append("❌ Forbidden digits present.")
            if not (sum_min <= s <= sum_max):
                ok = False; msgs.append(f"❌ Sum {s} outside [{sum_min}, {sum_max}].")
            evens = sum(1 for d in comb if d % 2 == 0); odds = 5 - evens
            lows  = sum(1 for d in comb if d <= low_max); highs = 5 - lows
            if not (min_low  <= lows  <= max_low):  ok=False; msgs.append(f"❌ Lows={lows} not in [{min_low},{max_low}] (low≤{low_max}).")
            if not (min_high <= highs <= max_high): ok=False; msgs.append(f"❌ Highs={highs} not in [{min_high},{max_high}].")
            if not (min_even <= evens <= max_even): ok=False; msgs.append(f"❌ Evens={evens} not in [{min_even},{max_even}].")
            if not (min_odd  <= odds  <= max_odd):  ok=False; msgs.append(f"❌ Odds={odds} not in [{min_odd},{max_odd}].")
            mand_digits = parse_mandatory_digits(mand_str)
            if mand_digits and not any(d in counts for d in mand_digits):
                ok=False; msgs.append(f"❌ Mandatory digits {mand_digits} not present (OR logic).")
            if violates_patterns(counts, allow_quints, allow_quads, allow_triples, allow_dd):
                ok=False; msgs.append("❌ Pattern filtered.")
            if not allow_runs4p:
                uniq_sorted = sorted(set(comb))
                if longest_consecutive_run_length(uniq_sorted) >= 4:
                    ok=False; msgs.append("❌ Run ≥ 4 not allowed.")
            if ok: st.success(f"✅ {test_combo_str} passes all filters.")
            else:  st.error(f"{test_combo_str} was excluded for:"); st.write("\n".join(msgs))

# -------------------- Core generation --------------------
if go:
    # Parse positional stats
    pos_probs = {}
    if pos_stats_text.strip():
        try:
            pos_probs = parse_positional_stats(pos_stats_text)
            for i in range(1,6):
                if not any(pos_probs[i]):
                    st.error(f"Positional row p{i} has all zeros — straights may tie at 0 on that position.")
        except Exception as e:
            st.warning(f"Couldn't parse positional stats — proceeding without scoring straights.\nDetails: {e}")
            pos_probs = {}

    # Enumerate boxes
    total = 0
    kept_boxes = []
    for comb in combinations_with_replacement(range(10), 5):
        total += 1
        if forbid_digits and any(d in forbid_digits for d in comb): continue
        s = sum(comb)
        if not (sum_min <= s <= sum_max): continue
        counts = Counter(comb)
        evens = sum(1 for d in comb if d % 2 == 0); odds = 5 - evens
        lows  = sum(1 for d in comb if d <= low_max); highs = 5 - lows
        if not (min_low  <= lows  <= max_low):  continue
        if not (min_high <= highs <= max_high): continue
        if not (min_even <= evens <= max_even): continue
        if not (min_odd  <= odds  <= max_odd):  continue
        mand_digits = parse_mandatory_digits(mand_str)
        if mand_digits and not any(d in counts for d in mand_digits): continue
        if violates_patterns(counts, allow_quints, allow_quads, allow_triples, allow_dd): continue
        if not allow_runs4p:
            uniq_sorted = sorted(set(comb))
            if longest_consecutive_run_length(uniq_sorted) >= 4: continue
        kept_boxes.append(comb)

    st.success(f"Found {len(kept_boxes)} box combos (out of {total} total).")

    # With positional stats → pick best straight(s)
    if pos_probs:
        outputs = []
        notes = []

        for box in kept_boxes:
            best_key = (-1.0, -1.0, "")  # (product_score, additive_score, perm_str)
            best_perms = []

            for perm in set(permutations(box)):
                pscore = prod_score(perm, pos_probs)
                ascore = add_score(perm, pos_probs)
                sstr   = "".join(map(str, perm))
                key    = (pscore, ascore, sstr)
                if key > best_key:
                    best_key = key
                    best_perms = [perm]
                elif key == best_key:
                    best_perms.append(perm)

            # Tie logic: keep both only when exactly one position has a 2-way tie
            pos_vals = [set() for _ in range(5)]
            for perm in best_perms:
                for i, d in enumerate(perm):
                    pos_vals[i].add(d)
            multi_positions = [i for i, s in enumerate(pos_vals) if len(s) > 1]

            if len(multi_positions) == 1 and len(pos_vals[multi_positions[0]]) == 2:
                idx = multi_positions[0]
                variants = {}
                for perm in best_perms:
                    k = perm[idx]
                    if k not in variants:
                        variants[k] = perm
                    if len(variants) == 2:
                        break
                for perm in variants.values():
                    outputs.append(("".join(map(str, perm)), best_key[0], best_key[1]))
            else:
                best_one = min(("".join(map(str, p)) for p in best_perms))
                outputs.append((best_one, best_key[0], best_key[1]))

        # Sort by product score desc, then additive score desc, then lex asc
        outputs.sort(key=lambda x: (-x[1], -x[2], x[0]))
        final_list = [s for s, _, _ in outputs]

        st.markdown("### Best Straight(s) per Box (per your tie rule)")
        st.caption("Best straight only; if exactly one position has a 2-way tie at the top, both are kept.")
        st.code("\n".join(final_list))

        if final_list:
            buf = io.StringIO(); buf.write("\n".join(final_list))
            st.download_button("Download final straights (.txt)",
                               data=buf.getvalue(),
                               file_name="final_straights.txt",
                               mime="text/plain")

        if notes:
            st.info("Tie reductions:\n" + "\n".join(notes))

    else:
        # No positional stats → show boxes (informational)
        st.markdown("### Boxes (no positional stats provided)")
        st.caption("Paste positional stats in the sidebar to score and order straights.")
        box_list = ["".join(map(str, b)) for b in kept_boxes]
        st.code("\n".join(box_list))
        if box_list:
            buf = io.StringIO(); buf.write("\n".join(box_list))
            st.download_button("Download boxes (.txt)", data=buf.getvalue(),
                               file_name="boxes.txt", mime="text/plain")
else:
    st.info("Set your constraints and click **Generate**.")
