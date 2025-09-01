# app.py
# DC-5 Box Generator + Best Straight Picker
# Adds:
#   - Optional "Do NOT use these digits" (excluded at generation time; leave blank for no effect)
#   - Low/High/Even/Odd MIN & MAX (defaults: min=2, max=5). Set min=max to mimic exact counts.
#   - Download button for final straights
# Keeps EVERYTHING else the same, including:
#   - Best straight only per box, but if exactly ONE position has a TWO-way tie, include BOTH straights.

from __future__ import annotations
import json
import io
from itertools import combinations_with_replacement, permutations
from collections import Counter
import streamlit as st

st.set_page_config(page_title="DC-5: Constrained Boxes → Best Straight(s)", layout="wide")
st.title("DC-5: Constrained Boxes → Best Straight(s)")

# -------------------- Helpers --------------------
LOW_MAX_DEFAULT = 4  # low digits are 0..4, high are 5..9 by default
EPS = 1e-15          # numeric tie tolerance

def parse_mandatory_digits(s: str) -> list[int]:
    out = []
    for token in (s or "").replace(",", " ").split():
        if token.isdigit():
            d = int(token)
            if 0 <= d <= 9:
                out.append(d)
    # dedupe preserving order
    seen = set()
    res = []
    for d in out:
        if d not in seen:
            res.append(d); seen.add(d)
    return res

def parse_forbidden_digits(s: str) -> set[int]:
    out = set()
    for token in (s or "").replace(",", " ").split():
        if token.isdigit():
            d = int(token)
            if 0 <= d <= 9:
                out.add(d)
    return out

def longest_consecutive_run_length(uniq_sorted: list[int]) -> int:
    if not uniq_sorted:
        return 0
    run = best = 1
    for i in range(1, len(uniq_sorted)):
        if uniq_sorted[i] == uniq_sorted[i-1] + 1:
            run += 1; best = max(best, run)
        else:
            run = 1
    return best

def violates_patterns(counts: Counter, allow_quints, allow_quads, allow_triples, allow_double_doubles):
    vals = list(counts.values())
    if not allow_quints and any(v == 5 for v in vals):
        return True
    if not allow_quads  and any(v == 4 for v in vals):
        return True
    if not allow_triples and any(v == 3 for v in vals):
        return True
    pairs = sum(1 for v in vals if v == 2)
    if not allow_double_doubles and pairs >= 2:
        return True
    return False

def normalize_row(row):
    s = sum(row)
    if 99.5 <= s <= 100.5:   # percentages
        return [x/100.0 for x in row]
    if 0.99 <= s <= 1.01:    # probabilities
        return row
    if s > 0:
        return [x/s for x in row]
    return row

def parse_positional_stats(text: str) -> dict[int, list[float]]:
    """
    Accept JSON or shorthand:
      JSON: {"p1":{"0":28.57,"1":0,...}, "p2":{...}, ...}
      SH:   p1: 4:28.57, 7:28.57, 0:28.57, 2:14.29; p2: 9:28.57, ...
    Returns dict {1:[p0..p9], ..., 5:[p0..p9]} with probabilities in [0,1].
    """
    text = (text or "").strip()
    if not text:
        return {}
    # Try JSON
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

    # Shorthand: semicolon-separated segments
    out = {}
    segments = [seg.strip() for seg in text.split(";") if seg.strip()]
    for seg in segments:
        if ":" not in seg:
            continue
        head, tail = seg.split(":", 1)
        head = head.strip().lower()
        if not (len(head) == 2 and head[0] == "p" and head[1] in "12345"):
            continue
        pos = int(head[1]); row = [0.0]*10
        for chunk in tail.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if ":" in chunk:
                d_str, v_str = [x.strip() for x in chunk.split(":", 1)]
            else:
                parts = chunk.split()
                if len(parts) != 2:
                    continue
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

def straight_score(straight, pos_probs: dict[int, list[float]]) -> float:
    score = 1.0
    for i, d in enumerate(straight, start=1):
        score *= pos_probs.get(i, [0.0]*10)[d]
    return score

# -------------------- Sidebar: constraints --------------------
st.sidebar.header("Constraints")

sum_min, sum_max = st.sidebar.slider("Sum range", 0, 45, (0, 45))
low_max = st.sidebar.number_input("Low max digit (low ≤ this value)", 0, 9, LOW_MAX_DEFAULT, 1)

mand_str = st.sidebar.text_input(
    "Mandatory digits (OR logic: at least one must appear)",
    help="Comma/space-separated digits, e.g. 7, 0, 2"
)
mand_digits = parse_mandatory_digits(mand_str)

# Optional forbidden digits (excluded DURING generation; leave blank for no effect)
forbid_str = st.sidebar.text_input(
    "Do NOT use these digits (optional)",
    help="Comma/space-separated digits (e.g. 8, 9). Any box containing them will not be generated."
)
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
    'Example: {"p1":{"4":28.57,"7":28.57,"0":28.57,"2":14.29}, ...} '
    "Or shorthand: p1: 4:28.57,7:28.57,0:28.57,2:14.29; p2: 9:28.57, ..."
)
pos_stats_text = st.sidebar.text_area("Positional stats", height=160, value="")

go = st.sidebar.button("Generate")
# ------------- Debug: Why a specific combo is excluded? -------------
with st.expander("🔍 Debug a specific combo (why excluded?)"):
    test_combo_str = st.text_input("Enter a 5-digit combo to test (e.g., 23579)")
    if st.button("Test this combo"):
        msg = []
        ok = True
        if not (test_combo_str.isdigit() and len(test_combo_str) == 5):
            st.error("Please enter exactly 5 digits.")
        else:
            # turn into a sorted 'box' like the generator uses
            comb = tuple(sorted(int(c) for c in test_combo_str))
            s = sum(comb)
            from collections import Counter
            counts = Counter(comb)

            # forbidden
            if forbid_digits and any(d in forbid_digits for d in comb):
                ok = False; msg.append("❌ Forbidden digits present.")

            # sum
            if not (sum_min <= s <= sum_max):
                ok = False; msg.append(f"❌ Sum {s} outside [{sum_min}, {sum_max}].")

            # parity
            evens = sum(1 for d in comb if d % 2 == 0)
            odds  = 5 - evens
            # low/high
            lows  = sum(1 for d in comb if d <= low_max)
            highs = 5 - lows

            if not (min_low  <= lows  <= max_low):   ok = False; msg.append(f"❌ Lows={lows} not in [{min_low},{max_low}] (low≤{low_max}).")
            if not (min_high <= highs <= max_high):  ok = False; msg.append(f"❌ Highs={highs} not in [{min_high},{max_high}].")
            if not (min_even <= evens <= max_even):  ok = False; msg.append(f"❌ Evens={evens} not in [{min_even},{max_even}].")
            if not (min_odd  <= odds  <= max_odd):   ok = False; msg.append(f"❌ Odds={odds} not in [{min_odd},{max_odd}].")

            # mandatory (OR)
            if mand_digits and not any(d in counts for d in mand_digits):
                ok = False; msg.append(f"❌ Mandatory digits {mand_digits} not present (OR logic).")

            # patterns
            from collections import Counter
            def violates_patterns_dbg(counts, allow_quints, allow_quads, allow_triples, allow_double_doubles):
                vals = list(counts.values())
                if not allow_quints and any(v == 5 for v in vals): return "quints"
                if not allow_quads  and any(v == 4 for v in vals): return "quads"
                if not allow_triples and any(v == 3 for v in vals): return "triples"
                pairs = sum(1 for v in vals if v == 2)
                if not allow_double_doubles and pairs >= 2: return "double-doubles"
                return None
            v = violates_patterns_dbg(counts, allow_quints, allow_quads, allow_triples, allow_dd)
            if v:
                ok = False; msg.append(f"❌ Pattern filtered: {v}")

            # runs
            def longest_consecutive_run_length(uniq_sorted):
                if not uniq_sorted: return 0
                run = best = 1
                for i in range(1, len(uniq_sorted)):
                    if uniq_sorted[i] == uniq_sorted[i-1] + 1:
                        run += 1; best = max(best, run)
                    else:
                        run = 1
                return best
            if not allow_runs4p:
                uniq_sorted = sorted(set(comb))
                if longest_consecutive_run_length(uniq_sorted) >= 4:
                    ok = False; msg.append("❌ Run ≥ 4 not allowed.")

            if ok:
                st.success(f"✅ {test_combo_str} passes all filters.")
            else:
                st.error(f"{test_combo_str} was excluded for:")
                st.write("\n".join(msg))

# -------------------- Core generation --------------------
if go:
    # Parse positional stats (optional)
    pos_probs = {}
    if pos_stats_text.strip():
        try:
            pos_probs = parse_positional_stats(pos_stats_text)
            for i in range(1,6):
                if not any(pos_probs[i]):
                    st.warning(f"Positional row p{i} sums to zero — all straights score 0 at position {i}.")
        except Exception as e:
            st.warning(f"Couldn't parse positional stats — proceeding without scoring straights.\nDetails: {e}")
            pos_probs = {}

    # Enumerate all 5-digit "boxes" (orderless multisets of digits 0..9)
    total = 0
    kept_boxes = []
    for comb in combinations_with_replacement(range(10), 5):
        total += 1

        # Upfront forbidden digits exclusion (never generate these if provided)
        if forbid_digits and any(d in forbid_digits for d in comb):
            continue

        s = sum(comb)
        if not (sum_min <= s <= sum_max):
            continue

        counts = Counter(comb)

        # Parity counts
        evens = sum(1 for d in comb if d % 2 == 0)
        odds  = 5 - evens

        # Low/High counts (based on low_max)
        lows  = sum(1 for d in comb if d <= low_max)
        highs = 5 - lows

        # H/L/E/O ranges
        if not (min_low  <= lows  <= max_low):   continue
        if not (min_high <= highs <= max_high):  continue
        if not (min_even <= evens <= max_even):  continue
        if not (min_odd  <= odds  <= max_odd):   continue

        # mandatory digits (OR)
        mand_digits = parse_mandatory_digits(mand_str)
        if mand_digits and not any(d in counts for d in mand_digits):
            continue

        # pattern constraints
        if violates_patterns(counts, allow_quints, allow_quads, allow_triples, allow_dd):
            continue

        # runs constraint
        if not allow_runs4p:
            uniq_sorted = sorted(set(comb))
            if longest_consecutive_run_length(uniq_sorted) >= 4:
                continue

        kept_boxes.append(comb)

    st.success(f"Found {len(kept_boxes)} box combos (out of {total} total).")

    # If positional stats exist, find best straight(s) for each box — apply your tie rule
    if pos_probs:
        outputs = []
        notes = []

        for box in kept_boxes:
            best_score = -1.0
            best_perms = []

            # Evaluate unique perms (avoid dupes when a pair exists)
            for perm in set(permutations(box)):
                sc = straight_score(perm, pos_probs)
                if sc > best_score + EPS:
                    best_score = sc
                    best_perms = [perm]
                elif abs(sc - best_score) <= EPS:
                    best_perms.append(perm)

            # Zero-score case: collapse to a single canonical straight
            if best_score <= 0.0 + EPS:
                outputs.append(("".join(map(str, box)), best_score))
                if len(best_perms) > 1:
                    notes.append(f"{''.join(map(str, box))}: suppressed {len(best_perms)-1} equal 0-score ties")
                continue

            # Keep both only when exactly one position has exactly two digits among the top-tied perms
            pos_vals = [set() for _ in range(5)]
            for perm in best_perms:
                for i, d in enumerate(perm):
                    pos_vals[i].add(d)

            multi_positions = [i for i, s in enumerate(pos_vals) if len(s) > 1]
            if len(multi_positions) == 1 and len(pos_vals[multi_positions[0]]) == 2:
                # Emit both variants differing at that one position
                idx = multi_positions[0]
                variants = {}
                for perm in best_perms:
                    key = perm[idx]
                    if key not in variants:
                        variants[key] = perm
                    if len(variants) == 2:
                        break
                for perm in variants.values():
                    outputs.append(("".join(map(str, perm)), best_score))
            else:
                # Emit only one canonical best (lexicographically smallest string among best perms)
                best_one = min(("".join(map(str, p)) for p in best_perms))
                outputs.append((best_one, best_score))
                if len(best_perms) > 1:
                    notes.append(f"{''.join(map(str, box))}: suppressed {len(best_perms)-1} equivalent ties")

        # Sort outputs by score desc, then string asc for stable display
        outputs.sort(key=lambda x: (-x[1], x[0]))
        final_list = [s for s, _ in outputs]

        st.markdown("### Best Straight(s) per Box (per your tie rule)")
        st.caption("Best straight only; if exactly one position has a 2-way tie at the top, both are kept.")
        st.code("\n".join(final_list))

        # Download button
        if final_list:
            buf = io.StringIO()
            buf.write("\n".join(final_list))
            st.download_button(
                "Download final straights (.txt)",
                data=buf.getvalue(),
                file_name="final_straights.txt",
                mime="text/plain"
            )

        if notes:
            st.info("Tie reductions:\n" + "\n".join(notes))

    else:
        st.markdown("### Boxes (no positional stats provided)")
        st.caption("Paste positional stats in the sidebar to score and order straights.")
        box_list = ["".join(map(str, b)) for b in kept_boxes]
        st.code("\n".join(box_list))

        # Download button for boxes
        if box_list:
            buf = io.StringIO()
            buf.write("\n".join(box_list))
            st.download_button(
                "Download boxes (.txt)",
                data=buf.getvalue(),
                file_name="boxes.txt",
                mime="text/plain"
            )

else:
    st.info("Set your constraints and click **Generate**.")
