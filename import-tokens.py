#!/usr/bin/env python3
"""Bulk import ssotokens into grok_session table via MySQL."""
import sys
import os
import subprocess
import datetime

TOKENS_FILE = os.environ.get("TOKENS_FILE", "/app/data/tokens.txt")
DB_USER = "root"
DB_NAME = "cool"

def main():
    if not os.path.exists(TOKENS_FILE):
        print(f"Token file not found: {TOKENS_FILE}")
        return

    with open(TOKENS_FILE, "r") as f:
        tokens = [line.strip() for line in f if line.strip()]

    print(f"Found {len(tokens)} tokens to import")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.000")

    # Batch insert in chunks of 500
    batch_size = 500
    total = 0
    for i in range(0, len(tokens), batch_size):
        chunk = tokens[i:i + batch_size]
        values = []
        for j, token in enumerate(chunk):
            idx = i + j
            email = f"pool_{idx:06d}"
            # Escape single quotes in token
            safe_token = token.replace("'", "\\'")
            values.append(f"(NOW(), NOW(), '{email}', '', 1, 0, '{safe_token}', 'auto-import', 0, 0)")

        sql = f"INSERT INTO grok_session (createTime, updateTime, email, password, status, isPro, officialSession, remark, sort, count) VALUES {','.join(values)};"

        try:
            result = subprocess.run(
                ["mysql", "-u", DB_USER, DB_NAME, "-e", sql],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                total += len(chunk)
                print(f"Batch {i // batch_size + 1}: imported {len(chunk)} tokens (total: {total})")
            else:
                print(f"Batch {i // batch_size + 1} FAILED: {result.stderr[:200]}")
                # Fallback: insert one by one for failed batch
                for k, token in enumerate(chunk):
                    idx = i + k
                    email = f"pool_{idx:06d}"
                    safe_token = token.replace("'", "\\'")
                    single_sql = f"INSERT INTO grok_session (createTime, updateTime, email, password, status, isPro, officialSession, remark, sort, count) VALUES (NOW(), NOW(), '{email}', '', 1, 0, '{safe_token}', 'auto-import', 0, 0);"
                    r = subprocess.run(["mysql", "-u", DB_USER, DB_NAME, "-e", single_sql], capture_output=True, text=True, timeout=30)
                    if r.returncode == 0:
                        total += 1
        except Exception as e:
            print(f"Error in batch {i // batch_size + 1}: {e}")

    print(f"Done. Total imported: {total}/{len(tokens)}")

if __name__ == "__main__":
    main()
