"""Fast PDF text extraction using pdftext (no OCR).

For PDFs that already have embedded text (not scanned images).
Much faster than Marker - seconds instead of minutes.
"""

import sys
from pathlib import Path
from typing import Optional
import hashlib
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import MARKDOWN_DIR, PDF_INPUT_DIR


def get_pdf_hash(pdf_path: Path) -> str:
    """Generate a short hash for the PDF file."""
    with open(pdf_path, "rb") as f:
        return hashlib.md5(f.read()[:4096]).hexdigest()[:8]


def slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    import re
    text = re.sub(r'\([^)]*\)', '', text)
    text = text.replace('.pdf', '')
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')


def check_pdf_has_text(pdf_path: Path) -> tuple[bool, int]:
    """
    Check if PDF has extractable text.

    Returns:
        (has_text, page_count)
    """
    from pdftext.extraction import plain_text_output

    try:
        # Extract first 3 pages to check if PDF has text
        text = plain_text_output(str(pdf_path), page_range=[0, 1, 2])
        # If we get at least 100 chars from first 3 pages, it has text
        has_text = len(text.strip()) > 100

        # Get page count
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(pdf_path))
        page_count = len(pdf)
        pdf.close()

        return has_text, page_count
    except Exception as e:
        print(f"Error checking PDF: {e}")
        return False, 0


def extract_single_pdf_fast(
    pdf_path: Path,
    output_dir: Optional[Path] = None,
    force: bool = False
) -> Optional[Path]:
    """
    Extract text from a PDF using pdftext (fast, no OCR).

    Args:
        pdf_path: Path to the PDF file
        output_dir: Output directory (default: MARKDOWN_DIR)
        force: Re-extract even if output exists

    Returns:
        Path to the output directory, or None if extraction failed
    """
    from pdftext.extraction import plain_text_output

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output_dir = output_dir or MARKDOWN_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    book_slug = slugify(pdf_path.stem)
    book_output_dir = output_dir / book_slug
    markdown_file = book_output_dir / f"{book_slug}.md"

    if markdown_file.exists() and not force:
        print(f"Already extracted: {pdf_path.name}")
        print(f"  Output: {markdown_file}")
        return book_output_dir

    # Check if PDF has extractable text
    has_text, page_count = check_pdf_has_text(pdf_path)

    if not has_text:
        print(f"WARNING: {pdf_path.name} appears to be scanned/image-based.")
        print("  Use the full Marker extractor for OCR.")
        return None

    print(f"Extracting: {pdf_path.name} ({page_count} pages)")

    # Extract text
    text = plain_text_output(str(pdf_path))

    if not text.strip():
        print(f"  ERROR: No text extracted")
        return None

    # Create output directory
    book_output_dir.mkdir(parents=True, exist_ok=True)

    # Convert to basic markdown (add title)
    title = pdf_path.stem.replace('-', ' ').title()
    markdown_content = f"# {title}\n\n{text}"

    # Write markdown
    with open(markdown_file, "w", encoding="utf-8") as f:
        f.write(markdown_content)

    # Save metadata
    metadata = {
        "source_file": pdf_path.name,
        "source_path": str(pdf_path.absolute()),
        "book_slug": book_slug,
        "file_hash": get_pdf_hash(pdf_path),
        "page_count": page_count,
        "extraction_method": "pdftext_fast",
    }
    with open(book_output_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    char_count = len(text)
    print(f"  Done: {char_count:,} chars extracted")
    print(f"  Output: {markdown_file}")

    return book_output_dir


def extract_batch_fast(
    input_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    force: bool = False
) -> list[Path]:
    """Extract all PDFs in a directory using fast method."""
    input_dir = Path(input_dir) if input_dir else PDF_INPUT_DIR
    output_dir = Path(output_dir) if output_dir else MARKDOWN_DIR

    pdf_files = list(input_dir.glob("*.pdf"))

    if not pdf_files:
        print(f"No PDF files found in {input_dir}")
        return []

    print(f"Found {len(pdf_files)} PDF files")

    results = []
    needs_ocr = []

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"\n[{i}/{len(pdf_files)}]")
        try:
            result = extract_single_pdf_fast(pdf_path, output_dir, force)
            if result:
                results.append(result)
            else:
                needs_ocr.append(pdf_path.name)
        except Exception as e:
            print(f"  ERROR: {e}")

    print(f"\n=== Summary ===")
    print(f"Extracted: {len(results)} PDFs")
    if needs_ocr:
        print(f"Need OCR (use Marker): {len(needs_ocr)} PDFs")
        for name in needs_ocr:
            print(f"  - {name}")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fast PDF text extraction (no OCR)")
    parser.add_argument("input", nargs="?", help="PDF file or directory")
    parser.add_argument("-o", "--output", help="Output directory")
    parser.add_argument("-f", "--force", action="store_true", help="Re-extract existing")

    args = parser.parse_args()

    if args.input:
        input_path = Path(args.input)
        if input_path.is_file():
            extract_single_pdf_fast(input_path, args.output, args.force)
        elif input_path.is_dir():
            extract_batch_fast(input_path, args.output, args.force)
        else:
            print(f"Error: {input_path} not found")
            sys.exit(1)
    else:
        extract_batch_fast(force=args.force)
