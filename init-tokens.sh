#!/bin/bash
# init-tokens.sh - Import tokens AFTER grok-app autoMigrate creates tables
# This runs as a separate supervisor process with priority 50

echo "=== INIT-TOKENS START ==="
echo "Date: $(date)"

# Wait for grok_session table to exist (created by autoMigrate)
echo "Waiting for grok_session table..."
for i in $(seq 1 120); do
    EXISTS=$(mysql -u root -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='cool' AND table_name='grok_session';" 2>/dev/null || echo "0")
    if [ "$EXISTS" != "0" ]; then
        echo "grok_session table exists at attempt $i"
        break
    fi
    echo "Waiting... $i/120"
    sleep 5
done

# Check current token count
TOKEN_COUNT=$(mysql -u root -N -e "SELECT COUNT(*) FROM cool.grok_session;" 2>/dev/null || echo "0")
echo "Current grok_session rows: $TOKEN_COUNT"

if [ "$TOKEN_COUNT" = "0" ]; then
    # Try SQL file
    if [ -f /app/data/tokens_import.sql ] && [ -s /app/data/tokens_import.sql ]; then
        echo "Loading from /app/data/tokens_import.sql..."
        mysql -u root cool < /app/data/tokens_import.sql 2>&1
    # Try tokens.txt with Python
    elif [ -f /app/data/tokens.txt ] && [ -s /app/data/tokens.txt ]; then
        echo "Loading from /app/data/tokens.txt via Python..."
        TOKENS_FILE=/app/data/tokens.txt python3 /app/import-tokens.py 2>&1
    else
        echo "NO TOKEN FILES FOUND"
    fi

    FINAL=$(mysql -u root -N -e "SELECT COUNT(*) FROM cool.grok_session;" 2>/dev/null || echo "ERROR")
    echo "Final grok_session rows: $FINAL"
else
    echo "Already have $TOKEN_COUNT tokens, skip"
fi

echo "=== INIT-TOKENS COMPLETE ==="
