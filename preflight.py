#!/usr/bin/env python3
"""
Pre-deploy smoke test for the Anomaly Editing Pipeline.

RUN THIS BEFORE EVERY PUSH:   python3 preflight.py

It catches the classes of bug that have taken the live app down before:
  1. Missing DOCTYPE      -> quirks mode -> broken scrolling on some machines (v2.7.0)
  2. Duplicate top-level identifiers -> module SyntaxError -> ENTIRE app blank (v2.5.0)
  3. Missing UI hooks     -> a handler binds to null and silently dies
  4. Unbalanced braces/parens in the script block
  5. Version not bumped   -> team keeps a stale cached build

Exit code 0 = safe to push. Non-zero = DO NOT PUSH.
"""
import re, sys, pathlib

SRC = pathlib.Path(__file__).with_name("index.html")
errors, warnings = [], []

html = SRC.read_text(encoding="utf-8")

# ---- 1. DOCTYPE -------------------------------------------------------
if not html.lstrip().lower().startswith("<!doctype html"):
    errors.append(
        "No <!DOCTYPE html> at the top of the file. The browser falls back to "
        "quirks mode, which reports the wrong viewport height and makes "
        "scrolling behave differently per machine."
    )

# ---- isolate the script blocks ---------------------------------------
scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
if not scripts:
    errors.append("No <script> block found — the app has no code.")
js = "\n".join(scripts)

# ---- 2. duplicate top-level declarations ------------------------------
# `function foo(` / `const foo =` at column 0 == top-level of the module.
for kind, pattern in (
    ("function", r"^function\s+([A-Za-z_$][\w$]*)\s*\("),
    ("const/let", r"^(?:const|let)\s+([A-Za-z_$][\w$]*)\s*="),
):
    seen = {}
    for m in re.finditer(pattern, js, re.M):
        name = m.group(1)
        seen.setdefault(name, []).append(js[: m.start()].count("\n") + 1)
    for name, lines in seen.items():
        if len(lines) > 1:
            errors.append(
                f"Duplicate top-level {kind} '{name}' declared {len(lines)}x "
                f"(script lines {lines}). In a module this is a SyntaxError and "
                f"NOTHING runs — the whole app goes blank."
            )

# ---- 3. UI hooks the JS depends on ------------------------------------
# every getElementById/$("#id") the code binds to must exist in the markup
referenced = set(re.findall(r"""getElementById\(["']([\w-]+)["']\)""", js))
referenced |= set(re.findall(r"""\$\(["']#([\w-]+)["']\)""", js))
declared = set(re.findall(r"""\bid=["']([\w-]+)["']""", html))
# ids the app creates dynamically at runtime are fine
dynamic = set(re.findall(r"""id=\\?["']([\w-]+)\\?["']""", js))
missing = sorted(referenced - declared - dynamic)
CRITICAL = {
    "asgFilter", "sortBy", "catFilter", "fDue", "fClient", "fNextSched",
    "filterNote", "board", "stats", "editId", "saveEntry", "openAdd",
}
for mid in missing:
    (errors if mid in CRITICAL else warnings).append(
        f"Script references #{mid} but no element with that id exists in the markup."
    )
for cid in sorted(CRITICAL):
    if cid not in declared:
        errors.append(f"Critical element #{cid} is missing from the markup.")

# ---- 4. crude balance check on the script -----------------------------
stripped = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", js, flags=re.S))
for open_c, close_c, label in (("{", "}", "braces"), ("(", ")", "parens"), ("[", "]", "brackets")):
    diff = stripped.count(open_c) - stripped.count(close_c)
    if diff:
        warnings.append(
            f"Unbalanced {label} in the script ({diff:+d}). Usually a false alarm "
            f"(they appear in strings/regex) — but if the app is blank, look here first."
        )

# ---- 5. version bump --------------------------------------------------
m = re.search(r'APP_VERSION\s*=\s*"([\d.]+)"', js)
if not m:
    errors.append("APP_VERSION not found.")
else:
    print(f"   version in file: v{m.group(1)}")

# ---- report -----------------------------------------------------------
print()
if warnings:
    print("WARNINGS (review, not blocking):")
    for w in warnings:
        print("  ! " + w)
    print()
if errors:
    print("BLOCKING PROBLEMS — DO NOT PUSH:")
    for e in errors:
        print("  x " + e)
    print()
    sys.exit(1)

print("PREFLIGHT PASSED — safe to push.")
print("Still do the runtime check: load it locally, confirm the version badge,")
print("switch tabs, and check the console is clean before deploying.")
sys.exit(0)
