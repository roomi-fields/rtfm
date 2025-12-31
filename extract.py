#!/usr/bin/env python3
"""CLI wrapper for PDF extraction."""

from src.extractor import extract_single_pdf, extract_batch
from pathlib import Path
import sys

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract PDFs to Markdown using Marker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract a single PDF
  python extract.py biblitest/my-book.pdf

  # Extract all PDFs in default directory (biblitest/)
  python extract.py

  # Extract with custom output directory
  python extract.py -o /path/to/output

  # Force re-extraction of already processed files
  python extract.py -f
"""
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="PDF file or directory (default: biblitest/)"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output directory (default: data/markdown/)"
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Re-extract existing files"
    )

    args = parser.parse_args()

    try:
        if args.input:
            input_path = Path(args.input)
            if input_path.is_file():
                extract_single_pdf(input_path, args.output, args.force)
            elif input_path.is_dir():
                extract_batch(input_path, args.output, args.force)
            else:
                print(f"Error: {input_path} not found")
                sys.exit(1)
        else:
            # Default: process all PDFs in biblitest
            extract_batch(force=args.force)
    except ImportError as e:
        print(f"Import error: {e}")
        print("\nMake sure marker-pdf is installed:")
        print("  pip install marker-pdf")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
