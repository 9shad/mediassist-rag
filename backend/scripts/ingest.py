#!/usr/bin/env python3
"""CLI entrypoint for document ingestion.

Usage:
    python scripts/ingest.py                         # Ingest all documents
    python scripts/ingest.py --dry-run               # Preview chunks without writing to Qdrant
    python scripts/ingest.py --file path/to/doc.pdf   # Ingest a single file
"""
import argparse
import sys
from pathlib import Path

# Ensure the backend package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from app.ingestion.pipeline import process_document, run_ingestion


def main():
    parser = argparse.ArgumentParser(description="Ingest PDFs/Markdown into Qdrant via Docling")
    parser.add_argument("--dry-run", action="store_true", help="Preview chunks without writing to Qdrant")
    parser.add_argument("--file", type=str, default=None, help="Ingest a single file instead of the full directory")
    parser.add_argument("--data-dir", type=str, default=None, help="Override the data directory path")
    args = parser.parse_args()

    data_dir = args.data_dir or str(Path(__file__).resolve().parent.parent.parent / "mediassist_data")
    data_path = Path(data_dir)

    if not data_path.exists():
        logger.error(f"Data directory not found: {data_dir}")
        sys.exit(1)

    if args.file:
        process_document(args.file, dry_run=args.dry_run)
    else:
        run_ingestion(data_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
