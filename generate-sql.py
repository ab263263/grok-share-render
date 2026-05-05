#!/usr/bin/env python3
"""Generate SQL import file from tokens.txt at build time."""
import os
import sys

TOKENS_FILE = os.environ.get("TOKENS_FILE", "/app/data/tokens.txt")
SQL_OUTPUT = "/app/data/tokens_import.sql"
BATCH_SIZE = 500

def main():
    if not os.path.exists(TOKENS_FILE):
        print(f"Token file not found: {TOKENS_FILE}")
        sys.exit(1)

    with open(TOKENS_FILE, "r") as f:
        tokens = [line.strip() for line in f if line.strip()]

    print(f"Generating SQL for {len(tokens)} tokens...")

    with open(SQL_OUTPUT, "w") as out:
        for i in range(0, len(tokens), BATCH_SIZE):
            chunk = tokens[i:i + BATCH_SIZE]
            header = "INSERT INTO grok_session (createTime, updateTime, email, password, status, isPro, officialSession, remark, sort, count) VALUES\n"
            rows = []
            for j, token in enumerate(chunk):
                idx = i + j
                email = f"pool_{idx:06d}"
                safe_token = token.replace("'", "\\'").replace("\\", "\\\\")
                rows.append(f"(NOW(), NOW(), '{email}', '', 1, 0, '{safe_token}', 'auto-import', 0, 0)")
            out.write(header + ",\n".join(rows) + ";\n")

    size = os.path.getsize(SQL_OUTPUT)
    print(f"Generated {SQL_OUTPUT} ({size} bytes)")

if __name__ == "__main__":
    main()
