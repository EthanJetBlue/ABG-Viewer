#!/usr/bin/env python3
"""Generate ABGViewer `manifest.json` and copy PDFs into immutable SHA-based URLs.

This script is intended to be run from the root of the GitHub Pages hosting repo.
It will:
  1) scan a folder of canonical PDFs named by airport identifier (e.g. JFK.pdf)
  2) compute SHA-256 + byte size
  3) copy each PDF to: docs/pdfs/<IATA>/<SHA256>.pdf
  4) write:
       - docs/manifest.json              (latest)
       - docs/manifests/manifest-<TS>.json  (immutable snapshot for rollback)

The manifest schema matches the ABGViewer iOS app models:
  - root: schemaVersion, generatedAt, baseURL, airports[]
  - airport: iata, icao, name, city, pdf{ url, sha256, size, updatedAt }

You can optionally provide a template manifest to preserve airport metadata.

Examples
--------
# Using a template that already contains your airport metadata:
python3 tools/generate_manifest.py \
  --source-pdfs ./source-pdfs \
  --template ./templates/manifest_template.json \
  --site-root ./docs \
  --base-url https://<username>.github.io/<repo>/

# Minimal manifest generated purely from filenames (not recommended for production):
python3 tools/generate_manifest.py --source-pdfs ./source-pdfs --site-root ./docs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SCHEMA_VERSION = 1


def iso_z(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    # Python's isoformat gives "+00:00"; ABGViewer uses ISO-8601 and accepts "Z".
    return dt.isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_iata_from_filename(path: Path) -> str:
    # Use the filename stem as identifier (e.g. JFK from JFK.pdf)
    # Normalize to uppercase and strip whitespace.
    return path.stem.strip().upper()


def ensure_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else (url + "/")


@dataclass(frozen=True)
class PdfInfo:
    iata: str
    src_path: Path
    sha256: str
    size: int
    mtime: datetime


def scan_pdfs(source_dir: Path) -> Dict[str, PdfInfo]:
    if not source_dir.exists():
        raise FileNotFoundError(f"source-pdfs folder not found: {source_dir}")

    pdf_map: Dict[str, PdfInfo] = {}

    for p in sorted(source_dir.rglob("*.pdf")):
        if not p.is_file():
            continue
        iata = safe_iata_from_filename(p)
        if not iata:
            continue

        if iata in pdf_map:
            print(f"WARN: duplicate IATA '{iata}' found. Keeping: {pdf_map[iata].src_path}  Skipping: {p}")
            continue

        stat = p.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        digest = sha256_file(p)
        pdf_map[iata] = PdfInfo(
            iata=iata,
            src_path=p,
            sha256=digest,
            size=int(stat.st_size),
            mtime=mtime,
        )

    if not pdf_map:
        raise RuntimeError(f"No PDFs found under: {source_dir}")

    return pdf_map


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def copy_pdf_to_immutable_path(site_root: Path, pdf: PdfInfo) -> str:
    """Copies the PDF to docs/pdfs/<IATA>/<SHA256>.pdf and returns the relative URL path."""

    rel = Path("pdfs") / pdf.iata / f"{pdf.sha256}.pdf"
    dst = site_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists():
        # If it exists, assume it's correct (immutable by sha). Avoid re-copying.
        return rel.as_posix()

    shutil.copy2(pdf.src_path, dst)
    return rel.as_posix()


def normalize_airport_dict(airport: Dict[str, Any], iata: str) -> Dict[str, Any]:
    """Ensure required fields exist for ABGViewer decoding."""
    out = dict(airport)
    out["iata"] = iata
    out.setdefault("icao", iata)
    out.setdefault("name", iata)
    out.setdefault("city", "")
    return out


def build_manifest(
    pdfs: Dict[str, PdfInfo],
    site_root: Path,
    base_url: Optional[str],
    template_manifest_path: Optional[Path],
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)

    airports_out: List[Dict[str, Any]] = []

    if template_manifest_path:
        template = load_json(template_manifest_path)
        template_airports = template.get("airports")
        if not isinstance(template_airports, list):
            raise ValueError("Template manifest must contain an 'airports' array.")

        for a in template_airports:
            if not isinstance(a, dict):
                continue
            iata = str(a.get("iata", "")).strip().upper()
            if not iata:
                continue

            pdf = pdfs.get(iata)
            if not pdf:
                print(f"WARN: template contains airport {iata}, but no PDF found. Skipping it.")
                continue

            rel_url = copy_pdf_to_immutable_path(site_root, pdf)
            a2 = normalize_airport_dict(a, iata)
            a2["pdf"] = {
                "url": rel_url,
                "sha256": pdf.sha256,
                "size": pdf.size,
                "updatedAt": iso_z(pdf.mtime),
                # Extra metadata (ignored by the app if not modeled).
                "version": iso_z(pdf.mtime)[:10],
            }
            airports_out.append(a2)

    else:
        # Minimal manifest from filenames only (useful for initial bootstrap).
        for iata, pdf in sorted(pdfs.items(), key=lambda kv: kv[0]):
            rel_url = copy_pdf_to_immutable_path(site_root, pdf)
            airports_out.append(
                {
                    "iata": iata,
                    "icao": iata,
                    "name": iata,
                    "city": "",
                    "pdf": {
                        "url": rel_url,
                        "sha256": pdf.sha256,
                        "size": pdf.size,
                        "updatedAt": iso_z(pdf.mtime),
                        "version": iso_z(pdf.mtime)[:10],
                    },
                }
            )

    manifest: Dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": iso_z(now),
        "airports": airports_out,
    }

    if base_url:
        manifest["baseURL"] = ensure_trailing_slash(base_url)

    return manifest


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Generate ABGViewer manifest.json for GitHub Pages")
    parser.add_argument("--source-pdfs", required=True, help="Folder containing JFK.pdf style PDFs")
    parser.add_argument("--site-root", required=True, help="Published GitHub Pages folder (typically ./docs)")
    parser.add_argument("--base-url", required=False, help="Public GitHub Pages base URL (https://user.github.io/repo/)")
    parser.add_argument("--template", required=False, help="Template manifest JSON containing airport metadata")
    parser.add_argument(
        "--timestamp",
        required=False,
        help="Override generated timestamp (UTC). Format: YYYYMMDD-HHMMSS. Used for versioned manifest filename.",
    )

    args = parser.parse_args(argv)

    source_dir = Path(args.source_pdfs).expanduser().resolve()
    site_root = Path(args.site_root).expanduser().resolve()
    template_path = Path(args.template).expanduser().resolve() if args.template else None

    pdfs = scan_pdfs(source_dir)

    manifest = build_manifest(pdfs, site_root=site_root, base_url=args.base_url, template_manifest_path=template_path)

    # Write latest manifest
    latest_manifest_path = site_root / "manifest.json"

    # Write a versioned snapshot for rollback
    if args.timestamp:
        ts = args.timestamp
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    versioned_manifest_path = site_root / "manifests" / f"manifest-{ts}.json"

    write_json(latest_manifest_path, manifest)
    write_json(versioned_manifest_path, manifest)

    print("OK: wrote", latest_manifest_path)
    print("OK: wrote", versioned_manifest_path)
    print(f"OK: processed {len(manifest.get('airports', []))} airports")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
