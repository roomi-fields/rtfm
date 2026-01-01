#!/usr/bin/env python3
"""Tag chunks using Gemini Flash - fast and free."""

import json
import os
import sqlite3
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import DB_PATH

# Gemini API config
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash-exp"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Batch size for efficiency (tag multiple chunks per request)
BATCH_SIZE = 10

TAGGING_PROMPT = """Analyze these text excerpts and extract 3-5 relevant topic tags for EACH.

{chunks}

Return a JSON array with one array of tags per text. Example for 3 texts:
[["tag1", "tag2", "tag3"], ["tag4", "tag5"], ["tag6", "tag7", "tag8"]]

ONLY output the JSON array, nothing else."""


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Get DB connection with resilient settings."""
    db_path = db_path or DB_PATH
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 60000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def update_schema(conn: sqlite3.Connection) -> None:
    """Add tags column if needed."""
    cursor = conn.execute("PRAGMA table_info(chunks)")
    existing = {row[1] for row in cursor.fetchall()}
    if "tags" not in existing:
        conn.execute("ALTER TABLE chunks ADD COLUMN tags TEXT")
        print("Added 'tags' column")
        conn.commit()


def call_gemini(prompt: str, timeout: int = 30, max_retries: int = 3) -> Optional[str]:
    """Call Gemini API with retry on rate limit."""
    if not GEMINI_API_KEY:
        print("Error: GEMINI_API_KEY not set")
        return None

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 1024,
        }
    }).encode('utf-8')

    for attempt in range(max_retries):
        req = urllib.request.Request(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            data=payload,
            headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt  # 1s, 2s, 4s
                print(f"    Rate limit, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    API error: {e}")
                return None
        except Exception as e:
            print(f"    API error: {e}")
            return None

    print("    Max retries exceeded")
    return None


def parse_batch_tags(response: str, expected_count: int) -> list[list[str]]:
    """Parse batch tags from Gemini response."""
    if not response:
        return [[] for _ in range(expected_count)]

    response = response.strip()
    # Find JSON array
    start = response.find('[')
    end = response.rfind(']')

    if start != -1 and end != -1:
        try:
            result = json.loads(response[start:end+1])
            if isinstance(result, list):
                # Normalize: ensure we have list of lists
                normalized = []
                for item in result:
                    if isinstance(item, list):
                        normalized.append([t.lower().strip() for t in item if isinstance(t, str)])
                    elif isinstance(item, str):
                        # Single tag, wrap in list
                        normalized.append([item.lower().strip()])
                    else:
                        normalized.append([])
                # Pad if needed
                while len(normalized) < expected_count:
                    normalized.append([])
                return normalized[:expected_count]
        except json.JSONDecodeError:
            pass

    return [[] for _ in range(expected_count)]


def tag_batch(chunks: list[dict]) -> list[list[str]]:
    """Generate tags for a batch of chunks."""
    # Format chunks for prompt
    formatted = []
    for i, chunk in enumerate(chunks, 1):
        content = chunk['content']
        if len(content) > 1500:
            content = content[:1500] + "..."
        formatted.append(f"--- Text {i} ---\n{content}")

    prompt = TAGGING_PROMPT.format(chunks="\n\n".join(formatted))
    response = call_gemini(prompt)
    return parse_batch_tags(response, len(chunks))


def tag_all_chunks(db_path: Optional[Path] = None, limit: int = 0, force: bool = False, batch_size: int = BATCH_SIZE) -> dict:
    """Tag all chunks in the database using batched requests."""
    db_path = db_path or DB_PATH
    if not Path(db_path).exists():
        print(f"Error: Database not found at {db_path}")
        return {"error": "Database not found"}

    if not GEMINI_API_KEY:
        print("Error: Set GEMINI_API_KEY environment variable")
        return {"error": "No API key"}

    conn = get_connection(db_path)
    update_schema(conn)

    sql = "SELECT id, content FROM chunks WHERE tags IS NULL ORDER BY id"
    if force:
        sql = "SELECT id, content FROM chunks ORDER BY id"
    if limit > 0:
        sql += f" LIMIT {limit}"

    chunks = [dict(row) for row in conn.execute(sql).fetchall()]

    if not chunks:
        print("All chunks already tagged. Use --force to re-tag.")
        return {"tagged": 0, "failed": 0}

    print(f"Tagging {len(chunks)} chunks in batches of {batch_size}...")
    print(f"Using model: {GEMINI_MODEL}\n")

    stats = {"tagged": 0, "failed": 0, "tags_count": {}}
    start_time = time.time()

    # Process in batches
    for batch_start in range(0, len(chunks), batch_size):
        batch = chunks[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (len(chunks) + batch_size - 1) // batch_size

        elapsed = time.time() - start_time
        processed = batch_start
        rate = processed / elapsed if elapsed > 0 else 0
        eta = (len(chunks) - processed) / rate if rate > 0 else 0

        print(f"[Batch {batch_num}/{total_batches}] {processed}/{len(chunks)} chunks, {rate:.1f}/s, ETA: {eta/60:.1f}min")

        batch_tags = tag_batch(batch)

        for chunk, tags in zip(batch, batch_tags):
            if tags:
                conn.execute("UPDATE chunks SET tags = ? WHERE id = ?",
                            (json.dumps(tags), chunk['id']))
                stats["tagged"] += 1
                for tag in tags:
                    stats["tags_count"][tag] = stats["tags_count"].get(tag, 0) + 1
            else:
                stats["failed"] += 1

        conn.commit()

        # Delay to avoid rate limits (Gemini free tier: 15 RPM)
        time.sleep(4)

    conn.close()
    elapsed = time.time() - start_time
    print(f"\n=== Summary ===")
    print(f"Tagged: {stats['tagged']}, Failed: {stats['failed']}")
    print(f"Time: {elapsed/60:.1f}min, Rate: {len(chunks)/elapsed:.1f} chunks/s")
    print(f"Unique tags: {len(stats['tags_count'])}")
    return stats


def show_tags(db_path: Optional[Path] = None) -> None:
    """Show tag statistics."""
    db_path = db_path or DB_PATH
    conn = get_connection(db_path)

    total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    tagged = conn.execute("SELECT COUNT(*) FROM chunks WHERE tags IS NOT NULL").fetchone()[0]
    print(f"Chunks: {tagged}/{total} tagged ({100*tagged/total:.1f}%)")

    cursor = conn.execute("SELECT tags FROM chunks WHERE tags IS NOT NULL")
    tag_counts = {}
    for row in cursor:
        for tag in json.loads(row['tags']):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    print(f"\nUnique tags: {len(tag_counts)}")
    print(f"\nTop 30 tags:")
    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1])[:30]:
        print(f"  {tag}: {count}")
    conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Tag chunks using Gemini Flash")
    parser.add_argument("--limit", "-l", type=int, default=0, help="Limit chunks to tag")
    parser.add_argument("--force", action="store_true", help="Re-tag already tagged chunks")
    parser.add_argument("--stats", action="store_true", help="Show tag statistics")
    parser.add_argument("--batch", "-b", type=int, default=BATCH_SIZE, help=f"Batch size (default: {BATCH_SIZE})")
    parser.add_argument("-d", "--db", help="Database path")
    args = parser.parse_args()

    db = Path(args.db) if args.db else None
    if args.stats:
        show_tags(db)
    else:
        tag_all_chunks(db, args.limit, args.force, args.batch)
