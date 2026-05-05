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

import_tokens() {
    SQL_FILE="/app/data/tokens_import.sql"
    
    # Try pre-generated SQL file first (generated at build time)
    if [ -f "$SQL_FILE" ] && [ -s "$SQL_FILE" ]; then
        echo "Found pre-generated SQL file: $SQL_FILE"
        TOKEN_COUNT=$(mysql -u root -N -e "SELECT COUNT(*) FROM cool.grok_session;" 2>/dev/null || echo "0")
        echo "Current grok_session rows: $TOKEN_COUNT"
        
        if [ "$TOKEN_COUNT" = "0" ]; then
            echo "Loading tokens from SQL file..."
            mysql -u root cool < "$SQL_FILE" 2>&1
            FINAL=$(mysql -u root -N -e "SELECT COUNT(*) FROM cool.grok_session;" 2>/dev/null || echo "?")
            echo "Token import complete: $FINAL rows"
        else
            echo "DB already has $TOKEN_COUNT tokens, skip import"
        fi
        return 0
    fi

    # Fallback: use Python import script
    echo "No pre-generated SQL file found, using Python import..."
    fetch_tokens_if_needed
    if [ -f "$TOKENS_FILE" ] && [ -s "$TOKENS_FILE" ]; then
        TOKENS_FILE="$TOKENS_FILE" python3 /app/import-tokens.py
    else
        echo "No tokens file found; skip token import"
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

import_tokens

echo "Init complete"
