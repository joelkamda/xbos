import os
import difflib
from pathlib import Path

# ==========================
# CONFIG
# ==========================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TARGET_EXTENSIONS = {".py"}

DRY_RUN = False

REPLACEMENTS = {
    "BillableUnitTaxonomy": "AtomicUnitTaxonomy",
    "BillableUnit": "AtomicUnit",
    "billable_unit_id": "atomic_unit_id",
    "billable_units": "atomic_units",
}

EXCLUDE_FOLDERS = {
    "venv",
    ".git",
    "__pycache__",
    "node_modules",
    "migrations",
    "scripts",
    "alembic",
}

files_scanned = 0
files_modified = 0


# ==========================
# SAFE PRICE RENAMING
# ==========================

def replace_price_fields(text: str) -> str:
    """
    Convert 'price' to 'unit_price' safely.

    Avoid touching existing 'unit_price'.
    """

    lines = text.split("\n")
    new_lines = []

    for line in lines:

        # skip if already unit_price
        if "unit_price" in line:
            new_lines.append(line)
            continue

        # rename Column price definition
        if "price = Column(" in line:
            line = line.replace("price", "unit_price")

        # rename JSON outputs
        if '"price":' in line:
            line = line.replace('"price":', '"unit_price":')

        if "'price':" in line:
            line = line.replace("'price':", "'unit_price':")

        new_lines.append(line)

    return "\n".join(new_lines)


# ==========================
# FILE REFACTOR
# ==========================

def refactor_file(file_path: Path) -> bool:
    global files_scanned

    files_scanned += 1

    try:
        original = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False

    modified = original

    # Apply main replacements
    for old, new in REPLACEMENTS.items():
        modified = modified.replace(old, new)

    # Safe price replacement
    modified = replace_price_fields(modified)

    if modified == original:
        return False

    print(f"\n---- {file_path.relative_to(PROJECT_ROOT)} ----")

    diff = difflib.unified_diff(
        original.splitlines(),
        modified.splitlines(),
        fromfile="before",
        tofile="after",
        lineterm="",
    )

    for line in diff:
        print(line)

    if not DRY_RUN:
        file_path.write_text(modified, encoding="utf-8")

    return True


# ==========================
# DIRECTORY WALK
# ==========================

def should_skip(path: Path) -> bool:
    return any(part in EXCLUDE_FOLDERS for part in path.parts)


def main():

    global files_modified

    print("\nXBOS Atomic Unit Refactor")
    print("\nMode:", "DRY RUN" if DRY_RUN else "APPLY")
    print("----------------------------------")

    for root, dirs, files in os.walk(PROJECT_ROOT):

        root_path = Path(root)

        if should_skip(root_path):
            continue

        for file in files:

            file_path = root_path / file

            if file_path.suffix not in TARGET_EXTENSIONS:
                continue

            if refactor_file(file_path):
                files_modified += 1

    print("\n----------------------------------")
    print(f"Files scanned: {files_scanned}")
    print(f"Files modified: {files_modified}")

    if DRY_RUN:
        print("\nNo files were modified.")
        print("Set DRY_RUN = False to apply changes.")


if __name__ == "__main__":
    main()