#!/usr/bin/env python3
"""Bulk import ssotokens into grok_session table via SQL file."""
import sys
import os
import subprocess

TOKENS_FILE = os.environ.get("TOKENS_FILE", "/app/data/tokens.txt")
SQL_FILE = "/tmp/tokens_import.sql"
DB_USER = "root"
DB_NAME = "cool"
BATCH_SIZE = 200

def generate_sql(tokens):
    """Generate SQL INSERT statements in batches."""
    header = "INSERT INTO grok_session (createTime, updateTime, email, password, status, isPro, officialSession, remark, sort, count) VALUES\n"
    footer = ";\n"
    
    for i in range(0, len(tokens), BATCH_SIZE):
        chunk = tokens[i:i + BATCH_SIZE]
        rows = []
        for j, token in enumerate(chunk):
            idx = i + j
            email = f"pool_{idx:06d}"
            safe_token = token.replace("'", "\\'").replace("\\", "\\\\")
            rows.append(f"(NOW(), NOW(), '{email}', '', 1, 0, '{safe_token}', 'auto-import', 0, 0)")
        yield header + ",\n".join(rows) + footer

def main():
    if not os.path.exists(TOKENS_FILE):
        print(f"Token file not found: {TOKENS_FILE}")
        sys.exit(1)

    with open(TOKENS_FILE, "r") as f:
        tokens = [line.strip() for line in f if line.strip()]

    print(f"Found {len(tokens)} tokens to import")

    # First: truncate existing data
    print("Truncating grok_session...")
    result = subprocess.run(
        ["mysql", "-u", DB_USER, DB_NAME, "-e", "TRUNCATE TABLE grok_session;"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        print(f"Truncate failed: {result.stderr[:200]}")

    # Generate and load SQL in batches
    total = 0
    batch_num = 0
    for sql_stmt in generate_sql(tokens):
        batch_num += 1
        # Write to temp file
        with open(SQL_FILE, "w") as f:
            f.write(sql_stmt)
        
        # Load via mysql
        try:
            with open(SQL_FILE, "r") as f:
                result = subprocess.run(
                    ["mysql", "-u", DB_USER, DB_NAME],
                    stdin=f, capture_output=True, text=True, timeout=120
                )
            if result.returncode == 0:
                chunk_size = min(BATCH_SIZE, len(tokens) - (batch_num - 1) * BATCH_SIZE)
                total += chunk_size
                print(f"Batch {batch_num}: OK ({total}/{len(tokens)})")
            else:
                print(f"Batch {batch_num} FAILED: {result.stderr[:200]}")
        except Exception as e:
            print(f"Batch {batch_num} ERROR: {e}")

    # Cleanup
    try:
        os.remove(SQL_FILE)
    except:
        pass

    # Verify
    try:
        result = subprocess.run(
            ["mysql", "-u", DB_USER, "-N", "-e",
             "SELECT COUNT(*) FROM cool.grok_session;"],
            capture_output=True, text=True, timeout=10
        )
        final_count = result.stdout.strip() if result.returncode == 0 else "ERROR"
        print(f"Verification: grok_session has {final_count} rows (expected {len(tokens)})")
    except Exception as e:
        print(f"Verification failed: {e}")

if __name__ == "__main__":
    main()
