#!/usr/bin/env python3
"""Generate SQL import file from tokens.txt at build time."""
import os, sys

TOKENS_FILE = os.environ.get("TOKENS_FILE", "/app/data/tokens.txt")
SQL_OUTPUT = "/app/data/tokens_import.sql"
BATCH = 500

def main():
    if not os.path.exists(TOKENS_FILE):
        print(f"Token file not found: {TOKENS_FILE}"); sys.exit(1)
    with open(TOKENS_FILE) as f:
        tokens = [l.strip() for l in f if l.strip()]
    print(f"Generating SQL for {len(tokens)} tokens...")
    with open(SQL_OUTPUT, "w") as out:
        for i in range(0, len(tokens), BATCH):
            chunk = tokens[i:i+BATCH]
            rows = []
            for j, t in enumerate(chunk):
                safe = t.replace("'", "\\'").replace("\\", "\\\\")
                rows.append(f"(NOW(), NOW(), 'pool_{i+j:06d}', '', 1, 0, '{safe}', 'auto-import', 0, 0)")
            out.write("INSERT INTO grok_session (createTime, updateTime, email, password, status, isPro, officialSession, remark, sort, count) VALUES\n")
            out.write(",\n".join(rows) + ";\n")
    print(f"Generated {SQL_OUTPUT} ({os.path.getsize(SQL_OUTPUT)} bytes)")

if __name__ == "__main__":
    main()
