import re
from pathlib import Path

# -----------------------------------------
# CONFIG
# -----------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"

DRY_RUN = False


# -----------------------------------------
# Replacement rules
# Order matters
# -----------------------------------------

REPLACEMENTS = [

    # functions
    (r"\bget_billable_unit\b", "get_atomic_unit"),
    (r"\battach_billable_unit\b", "attach_atomic_unit"),
    (r"\bdetach_billable_unit\b", "detach_atomic_unit"),

    # relationship variable
    (r"\bbillable_unit\s*=", "atomic_unit ="),

    # variable usage
    (r"\bbillable_unit\b", "atomic_unit"),

    # comments / text
    (r"Billable Units", "Atomic Units"),
    (r"Billable Unit", "Atomic Unit"),
    (r"billable units", "atomic units"),
    (r"billable unit", "atomic unit"),
]


# -----------------------------------------
# File processor
# -----------------------------------------

def refactor_file(path: Path):

    try:
        original = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False

    updated = original

    for pattern, replacement in REPLACEMENTS:
        updated = re.sub(pattern, replacement, updated)

    if updated != original:

        print(f"\n---- {path.relative_to(PROJECT_ROOT)} ----")

        if DRY_RUN:
            print("CHANGES DETECTED")

        else:
            path.write_text(updated, encoding="utf-8")

        return True

    return False


# -----------------------------------------
# Main
# -----------------------------------------

def main():

    print("\nXBOS Atomic Unit Refactor Sweep #2")
    print("\nMode:", "DRY RUN" if DRY_RUN else "APPLY")
    print("----------------------------------")

    scanned = 0
    modified = 0

    for path in CORE_DIR.rglob("*.py"):

        scanned += 1

        if refactor_file(path):
            modified += 1

    print("\n----------------------------------")
    print("Files scanned:", scanned)
    print("Files modified:", modified)

    if DRY_RUN:
        print("\nNo files were modified.")
        print("Set DRY_RUN = False to apply changes.")


if __name__ == "__main__":
    main()