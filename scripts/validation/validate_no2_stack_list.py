"""
Validate an arbitrary list of GeoTIFFs against a reference grid (same workflow as
validate_tempo_stack.py). Filenames are read from a text file: one name per line;
lines starting with # are ignored.

Usage:
  py -3 scripts/validation/validate_no2_stack_list.py --reference ref.tif --dir data/foo --list expected_files.txt

Requires: rasterio
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_list(path: Path) -> tuple[str, ...]:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return tuple(out)


def main() -> int:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    from validation.grid_stack import validate_layers_against_reference

    p = argparse.ArgumentParser(description="Validate listed GeoTIFFs vs one reference grid.")
    p.add_argument("--reference", type=Path, required=True, help="Reference GeoTIFF path.")
    p.add_argument("--dir", type=Path, required=True, help="Directory containing listed files.")
    p.add_argument(
        "--list",
        type=Path,
        required=True,
        help="Text file: one filename per line (relative to --dir).",
    )
    p.add_argument(
        "--strict-one-band",
        action="store_true",
        help="Fail if any layer is not exactly one band (default: allow multi-band like TEMPO 72-band stacks).",
    )
    args = p.parse_args()

    if not args.list.is_file():
        print(f"ERROR: list file not found: {args.list}", file=sys.stderr)
        return 1

    expected = _load_list(args.list)
    if not expected:
        print("ERROR: no filenames in list file.", file=sys.stderr)
        return 1

    ref_path = args.reference if args.reference.is_absolute() else (args.dir / args.reference)
    ok = validate_layers_against_reference(
        ref_path, args.dir, expected, single_band_only=args.strict_one_band
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
