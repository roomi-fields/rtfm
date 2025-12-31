"""PDF extraction using Marker."""

import sys
from pathlib import Path
from typing import Optional
import hashlib
import json

# Add project root to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import MARKDOWN_DIR, PDF_INPUT_DIR


def get_pdf_hash(pdf_path: Path) -> str:
    """Generate a short hash for the PDF file."""
    with open(pdf_path, "rb") as f:
        return hashlib.md5(f.read()[:4096]).hexdigest()[:8]


def slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    import re
    # Remove parentheses content like "(Z-Library)"
    text = re.sub(r'\([^)]*\)', '', text)
    # Remove .pdf extension
    text = text.replace('.pdf', '')
    # Convert to lowercase, replace spaces with hyphens
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')


def extract_single_pdf(
    pdf_path: Path,
    output_dir: Optional[Path] = None,
    force: bool = False
) -> Path:
    """
    Extract a single PDF to Markdown using Marker.

    Args:
        pdf_path: Path to the PDF file
        output_dir: Output directory (default: MARKDOWN_DIR)
        force: Re-extract even if output exists

    Returns:
        Path to the output directory containing the markdown
    """
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output_dir = output_dir or MARKDOWN_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create output subdirectory for this book
    book_slug = slugify(pdf_path.stem)
    book_output_dir = output_dir / book_slug
    markdown_file = book_output_dir / f"{book_slug}.md"

    # Check if already processed
    if markdown_file.exists() and not force:
        print(f"Already extracted: {pdf_path.name}")
        print(f"  Output: {markdown_file}")
        return book_output_dir

    print(f"Extracting: {pdf_path.name}")

    # Create model dict for Marker (CPU mode)
    models = create_model_dict()

    # Create converter and process
    converter = PdfConverter(artifact_dict=models)
    rendered = converter(str(pdf_path))

    # Get text output
    text, _, images = text_from_rendered(rendered)

    # Create output directory
    book_output_dir.mkdir(parents=True, exist_ok=True)

    # Write markdown
    with open(markdown_file, "w", encoding="utf-8") as f:
        f.write(text)

    # Save images if any
    if images:
        images_dir = book_output_dir / "images"
        images_dir.mkdir(exist_ok=True)
        for img_name, img_data in images.items():
            img_path = images_dir / img_name
            with open(img_path, "wb") as f:
                f.write(img_data)
        print(f"  Saved {len(images)} images")

    # Save metadata
    metadata = {
        "source_file": pdf_path.name,
        "source_path": str(pdf_path.absolute()),
        "book_slug": book_slug,
        "file_hash": get_pdf_hash(pdf_path),
    }
    with open(book_output_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"  Output: {markdown_file}")
    return book_output_dir


def extract_batch(
    input_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    force: bool = False
) -> list[Path]:
    """
    Extract all PDFs in a directory.

    Args:
        input_dir: Directory containing PDFs (default: PDF_INPUT_DIR)
        output_dir: Output directory (default: MARKDOWN_DIR)
        force: Re-extract even if output exists

    Returns:
        List of output directory paths
    """
    input_dir = Path(input_dir) if input_dir else PDF_INPUT_DIR
    output_dir = Path(output_dir) if output_dir else MARKDOWN_DIR

    pdf_files = list(input_dir.glob("*.pdf"))

    if not pdf_files:
        print(f"No PDF files found in {input_dir}")
        return []

    print(f"Found {len(pdf_files)} PDF files")

    results = []
    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"\n[{i}/{len(pdf_files)}]")
        try:
            result = extract_single_pdf(pdf_path, output_dir, force)
            results.append(result)
        except Exception as e:
            print(f"  ERROR: {e}")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract PDFs to Markdown using Marker")
    parser.add_argument("input", nargs="?", help="PDF file or directory (default: biblitest/)")
    parser.add_argument("-o", "--output", help="Output directory")
    parser.add_argument("-f", "--force", action="store_true", help="Re-extract existing files")

    args = parser.parse_args()

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
