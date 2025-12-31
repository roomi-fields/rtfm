#!/usr/bin/env python3
"""Tag chunks using local LLM (Ollama) - with resilient DB handling."""

import json
import sqlite3
import time
import urllib.request
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import DB_PATH

OLLAMA_URL = "http://localhost:11435/api/generate"
MODEL = "mistral:latest"

TAGGING_PROMPT = """Analyze this text excerpt and extract 3-5 relevant topic tags.

Text:
---
{content}
---

Return ONLY a JSON array of lowercase tags. Example: ["self-realization", "ego", "identity"]

Tags:"""


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


def call_ollama(prompt: str, timeout: int = 60) -> Optional[str]:
    """Call Ollama API."""
    payload = json.dumps({
        "model": MODEL, "prompt": prompt, "stream": False,
        "options": {"temperature": 0.3, "num_predict": 100}
    }).encode('utf-8')

    req = urllib.request.Request(
        OLLAMA_URL, data=payload,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get("response", "")
    except Exception as e:
        print(f"    API error: {e}")
        return None


def parse_tags(response: str) -> list[str]:
    """Parse tags from LLM response."""
    if not response:
        return []
    response = response.strip()
    start = response.find('[')
    end = response.rfind(']')
    if start != -1 and end != -1:
        try:
            tags = json.loads(response[start:end+1])
            if isinstance(tags, list):
                return [t.lower().strip() for t in tags if isinstance(t, str)]
        except json.JSONDecodeError:
            pass
    import re
    matches = re.findall(r'"([^"]+)"', response)
    return [m.lower().strip() for m in matches[:5]]


def tag_chunk(content: str) -> list[str]:
    """Generate tags for a chunk."""
    if len(content) > 2000:
        content = content[:2000] + "..."
    prompt = TAGGING_PROMPT.format(content=content)
    return parse_tags(call_ollama(prompt))


def tag_all_chunks(db_path: Optional[Path] = None, limit: int = 0, force: bool = False) -> dict:
    """Tag all chunks in the database."""
    db_path = db_path or DB_PATH
    if not Path(db_path).exists():
        print(f"Error: Database not found at {db_path}")
        return {"error": "Database not found"}

    conn = get_connection(db_path)
    update_schema(conn)

    sql = "SELECT id, content FROM chunks WHERE tags IS NULL ORDER BY id"
    if force:
        sql = "SELECT id, content FROM chunks ORDER BY id"
    if limit > 0:
        sql += f" LIMIT {limit}"

    chunks = conn.execute(sql).fetchall()

    if not chunks:
        print("All chunks already tagged. Use --force to re-tag.")
        return {"tagged": 0, "failed": 0}

    print(f"Tagging {len(chunks)} chunks...\n")
    stats = {"tagged": 0, "failed": 0, "tags_count": {}}
    start_time = time.time()

    for i, chunk in enumerate(chunks, 1):
        if i % 10 == 0 or i == 1:
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(chunks) - i) / rate if rate > 0 else 0
            print(f"[{i}/{len(chunks)}] {rate:.1f} chunks/s, ETA: {eta/60:.1f}min")

        tags = tag_chunk(chunk['content'])
        if tags:
            conn.execute("UPDATE chunks SET tags = ? WHERE id = ?",
                        (json.dumps(tags), chunk['id']))
            conn.commit()
            stats["tagged"] += 1
            for tag in tags:
                stats["tags_count"][tag] = stats["tags_count"].get(tag, 0) + 1
        else:
            stats["failed"] += 1

    conn.close()
    elapsed = time.time() - start_time
    print(f"\n=== Summary ===")
    print(f"Tagged: {stats['tagged']}, Failed: {stats['failed']}")
    print(f"Time: {elapsed/60:.1f}min, Rate: {len(chunks)/elapsed:.1f} chunks/s")
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
    parser = argparse.ArgumentParser(description="Tag chunks using LLM")
    parser.add_argument("--limit", "-l", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("-d", "--db", help="Database path")
    args = parser.parse_args()

    db = Path(args.db) if args.db else None
    if args.stats:
        show_tags(db)
    else:
        tag_all_chunks(db, args.limit, args.force)
