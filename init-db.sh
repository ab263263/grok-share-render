#!/bin/bash
# NO set -e on purpose - log everything

TOKENS_FILE="${TOKENS_FILE:-/app/data/tokens.txt}"
TOKENS_URL="${TOKENS_URL:-}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"

echo "=== INIT-DB START ==="
echo "Date: $(date)"
echo "Tokens file: $TOKENS_FILE"
ls -la "$TOKENS_FILE" 2>/dev/null || echo "Token file not found"
ls -la /app/data/tokens_import.sql 2>/dev/null || echo "SQL file not found"
ls -la /docker-entrypoint-initdb.d/cool-20250228-123947.sql 2>/dev/null || echo "Schema file not found"

# Wait for MySQL
echo "=== Waiting for MySQL ==="
for i in $(seq 1 60); do
    if mysqladmin ping -u root --silent 2>/dev/null; then
        echo "MySQL ready at attempt $i"
        break
    fi
    echo "Waiting... $i/60"
    sleep 2
done

echo "=== Creating DB and users ==="
mysql -u root -e "CREATE DATABASE IF NOT EXISTS cool CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>&1
mysql -u root -e "
CREATE USER IF NOT EXISTS 'cool'@'localhost' IDENTIFIED BY '123123';
CREATE USER IF NOT EXISTS 'cool'@'127.0.0.1' IDENTIFIED BY '123123';
CREATE USER IF NOT EXISTS 'cool'@'%' IDENTIFIED BY '123123';
ALTER USER 'cool'@'localhost' IDENTIFIED BY '123123';
ALTER USER 'cool'@'127.0.0.1' IDENTIFIED BY '123123';
ALTER USER 'cool'@'%' IDENTIFIED BY '123123';
GRANT ALL PRIVILEGES ON cool.* TO 'cool'@'localhost';
GRANT ALL PRIVILEGES ON cool.* TO 'cool'@'127.0.0.1';
GRANT ALL PRIVILEGES ON cool.* TO 'cool'@'%';
FLUSH PRIVILEGES;
" 2>&1
echo "DB setup done"

echo "=== Importing schema ==="
mysql -u root cool -e "SET FOREIGN_KEY_CHECKS=0;" 2>&1
mysql -u root cool < /docker-entrypoint-initdb.d/cool-20250228-123947.sql 2>&1 || echo "SCHEMA_IMPORT_ERROR (continuing...)"
mysql -u root cool -e "SET FOREIGN_KEY_CHECKS=1;" 2>&1

echo "=== Checking grok_session after schema ==="
mysql -u root cool -e "SELECT COUNT(*) as session_count FROM grok_session;" 2>&1

echo "=== Checking if tokens exist ==="
TABLE_EXISTS=$(mysql -u root -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='cool' AND table_name='grok_session';" 2>/dev/null || echo "0")
echo "grok_session table exists: $TABLE_EXISTS"

if [ "$TABLE_EXISTS" != "0" ]; then
    TOKEN_COUNT=$(mysql -u root -N -e "SELECT COUNT(*) FROM cool.grok_session;" 2>/dev/null || echo "0")
    echo "Current token count: $TOKEN_COUNT"
    
    if [ "$TOKEN_COUNT" = "0" ]; then
        echo "=== No tokens! Trying SQL file ==="
        if [ -f /app/data/tokens_import.sql ]; then
            echo "Found tokens_import.sql, loading..."
            mysql -u root cool < /app/data/tokens_import.sql 2>&1 || echo "SQL_IMPORT_ERROR"
            echo "After SQL import:"
            mysql -u root cool -e "SELECT COUNT(*) as session_count FROM grok_session;" 2>&1
        elif [ -f "$TOKENS_FILE" ]; then
            echo "Found $TOKENS_FILE, using Python..."
            TOKENS_FILE="$TOKENS_FILE" python3 /app/import-tokens.py 2>&1 || echo "PYTHON_IMPORT_ERROR"
            echo "After Python import:"
            mysql -u root cool -e "SELECT COUNT(*) as session_count FROM grok_session;" 2>&1
        else
            echo "NO TOKEN FILES FOUND!"
        fi
    fi
fi

echo "=== Final status ==="
mysql -u root cool -e "SELECT COUNT(*) as final_session_count FROM grok_session;" 2>&1
mysql -u root cool -e "SHOW TABLES;" 2>&1 | head -10

echo "=== INIT-DB COMPLETE ==="
