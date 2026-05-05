#!/bin/bash
set -e

TOKENS_FILE="${TOKENS_FILE:-/app/data/tokens.txt}"
TOKENS_URL="${TOKENS_URL:-}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"

fetch_tokens_if_needed() {
    if [ -f "$TOKENS_FILE" ] && [ -s "$TOKENS_FILE" ]; then
        echo "Using local tokens file: $TOKENS_FILE"
        return 0
    fi

    if [ -n "$TOKENS_URL" ]; then
        echo "Fetching tokens from remote source..."
        mkdir -p "$(dirname "$TOKENS_FILE")"
        if [ -n "$GITHUB_TOKEN" ]; then
            curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github.raw+json" "$TOKENS_URL" -o "$TOKENS_FILE"
        else
            curl -fsSL "$TOKENS_URL" -o "$TOKENS_FILE"
        fi
        echo "Remote tokens downloaded to $TOKENS_FILE"
    fi
}

import_tokens_if_needed() {
    TOKEN_COUNT=$(mysql -u root -N -e "SELECT COUNT(*) FROM cool.grok_session;" 2>/dev/null || echo "0")
    echo "Current grok_session rows: $TOKEN_COUNT"

    fetch_tokens_if_needed
    if [ ! -f "$TOKENS_FILE" ] || [ ! -s "$TOKENS_FILE" ]; then
        echo "No tokens file found; skip token import"
        return 0
    fi

    FILE_LINES=$(grep -c '.' "$TOKENS_FILE")
    echo "Token file has $FILE_LINES lines, DB has $TOKEN_COUNT rows"

    # Always re-import if file has more tokens or DB is empty
    if [ "$TOKEN_COUNT" -ge "$FILE_LINES" ] 2>/dev/null; then
        echo "DB already has enough tokens ($TOKEN_COUNT >= $FILE_LINES), skip import"
        return 0
    fi

    echo "Re-importing tokens..."
    mysql -u root -e "TRUNCATE TABLE cool.grok_session;" 2>/dev/null || true

    # Generate SQL file and load in one shot (fast + low memory)
    SQL_FILE="/tmp/tokens_import.sql"
    echo "INSERT INTO grok_session (createTime, updateTime, email, password, status, isPro, officialSession, remark, sort, count) VALUES" > "$SQL_FILE"
    IDX=0
    FIRST=1
    while IFS= read -r TOKEN; do
        [ -z "$TOKEN" ] && continue
        SAFE_TOKEN=$(echo "$TOKEN" | sed "s/'/\\\\'/g")
        EMAIL="pool_$(printf '%06d' $IDX)"
        if [ "$FIRST" -eq 1 ]; then
            FIRST=0
        else
            echo "," >> "$SQL_FILE"
        fi
        printf "(NOW(), NOW(), '%s', '', 1, 0, '%s', 'auto-import', 0, 0)" "$EMAIL" "$SAFE_TOKEN" >> "$SQL_FILE"
        IDX=$((IDX + 1))
    done < "$TOKENS_FILE"
    echo ";" >> "$SQL_FILE"

    echo "Generated SQL with $IDX rows, loading..."
    mysql -u root cool < "$SQL_FILE" 2>&1
    RESULT=$?
    rm -f "$SQL_FILE"

    if [ $RESULT -eq 0 ]; then
        FINAL_COUNT=$(mysql -u root -N -e "SELECT COUNT(*) FROM cool.grok_session;" 2>/dev/null || echo "?")
        echo "Token import complete: $FINAL_COUNT rows in DB"
    else
        echo "SQL import failed (exit $RESULT), trying Python fallback..."
        TOKENS_FILE="$TOKENS_FILE" python3 /app/import-tokens.py
    fi
}

# Wait for MySQL to be ready
for i in $(seq 1 60); do
    if mysqladmin ping -u root --silent 2>/dev/null; then
        echo "MySQL is ready"
        break
    fi
    echo "Waiting for MySQL... ($i/60)"
    sleep 2
done

echo "Ensuring database and application users exist..."
mysql -u root -e "CREATE DATABASE IF NOT EXISTS cool CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -e "CREATE USER IF NOT EXISTS 'cool'@'localhost' IDENTIFIED BY '123123'; CREATE USER IF NOT EXISTS 'cool'@'127.0.0.1' IDENTIFIED BY '123123'; CREATE USER IF NOT EXISTS 'cool'@'%' IDENTIFIED BY '123123'; ALTER USER 'cool'@'localhost' IDENTIFIED BY '123123'; ALTER USER 'cool'@'127.0.0.1' IDENTIFIED BY '123123'; ALTER USER 'cool'@'%' IDENTIFIED BY '123123'; GRANT ALL PRIVILEGES ON cool.* TO 'cool'@'localhost'; GRANT ALL PRIVILEGES ON cool.* TO 'cool'@'127.0.0.1'; GRANT ALL PRIVILEGES ON cool.* TO 'cool'@'%'; FLUSH PRIVILEGES;"

SCHEMA_READY=$(mysql -u root -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='cool' AND table_name='grok_session';" 2>/dev/null || echo "0")

if [ "$SCHEMA_READY" = "0" ]; then
    echo "Schema not found, importing database structure..."

    if [ -f /docker-entrypoint-initdb.d/cool-20250228-123947.sql ]; then
        mysql -u root cool < /docker-entrypoint-initdb.d/cool-20250228-123947.sql
        echo "Schema imported successfully"
    else
        echo "Schema file not found, will rely on autoMigrate"
    fi
fi

import_tokens_if_needed

echo "Init complete"
