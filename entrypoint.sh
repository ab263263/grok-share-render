#!/bin/bash
# entrypoint.sh - Sequential init, all logs visible in Render

echo "=== ENTRYPOINT START $(date) ==="

# Init MariaDB data directory
mkdir -p /run/mysqld /var/lib/mysql /var/log
chown -R root:root /run/mysqld /var/lib/mysql /var/log 2>/dev/null || true

if [ ! -d "/var/lib/mysql/mysql" ]; then
    echo "Initializing MariaDB..."
    MYSQL_INIT_BIN=$(command -v mariadb-install-db || command -v mysql_install_db)
    "$MYSQL_INIT_BIN" --user=root --datadir=/var/lib/mysql 2>&1 || true
fi

# Start MySQL in background
echo "Starting MySQL..."
MYSQLD=$(command -v mariadbd || command -v mysqld)
"$MYSQLD" --user=root --datadir=/var/lib/mysql &
MYSQL_PID=$!

# Wait for MySQL
echo "Waiting for MySQL..."
for i in $(seq 1 60); do
    if mysqladmin ping -u root --silent 2>/dev/null; then
        echo "MySQL ready (attempt $i)"
        break
    fi
    sleep 2
done

# Setup database
echo "Setting up database..."
mysql -u root -e "CREATE DATABASE IF NOT EXISTS cool CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>&1
mysql -u root -e "CREATE USER IF NOT EXISTS 'cool'@'localhost' IDENTIFIED BY '123123'; CREATE USER IF NOT EXISTS 'cool'@'127.0.0.1' IDENTIFIED BY '123123'; CREATE USER IF NOT EXISTS 'cool'@'%' IDENTIFIED BY '123123'; ALTER USER 'cool'@'localhost' IDENTIFIED BY '123123'; ALTER USER 'cool'@'127.0.0.1' IDENTIFIED BY '123123'; ALTER USER 'cool'@'%' IDENTIFIED BY '123123'; GRANT ALL PRIVILEGES ON cool.* TO 'cool'@'localhost'; GRANT ALL PRIVILEGES ON cool.* TO 'cool'@'127.0.0.1'; GRANT ALL PRIVILEGES ON cool.* TO 'cool'@'%'; FLUSH PRIVILEGES;" 2>&1
echo "Database ready"

# Start Redis
echo "Starting Redis..."
mkdir -p /var/lib/redis /var/log/redis
redis-server /etc/redis.conf --daemonize no --loglevel notice 2>&1 &
REDIS_PID=$!
sleep 2
# Check if Redis is running
if kill -0 $REDIS_PID 2>/dev/null; then
    echo "Redis started (PID $REDIS_PID)"
else
    echo "WARNING: Redis failed to start! Trying default config..."
    redis-server --daemonize no --loglevel notice 2>&1 &
    REDIS_PID=$!
fi

# Start Go app (autoMigrate will create tables)
echo "Starting grok-app..."
cd /app
./main &
APP_PID=$!

# Wait for grok_session table (autoMigrate)
echo "Waiting for grok_session table..."
for i in $(seq 1 120); do
    EXISTS=$(mysql -u root -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='cool' AND table_name='grok_session';" 2>/dev/null || echo "0")
    if [ "$EXISTS" != "0" ]; then
        echo "grok_session table exists (attempt $i)"
        break
    fi
    sleep 5
done

# Import tokens if table is empty
mkdir -p /app/data
echo "=== Token import phase ==="
TOKEN_COUNT=$(mysql -u root -N -e "SELECT COUNT(*) FROM cool.grok_session;" 2>/dev/null || echo "ERROR")
echo "Current grok_session rows: $TOKEN_COUNT"

if [ "$TOKEN_COUNT" = "0" ]; then
    SQL_FILE="/app/data/tokens_import.sql"
    TOKENS_FILE="/app/data/tokens.txt"

    if [ -n "${GROK_TOKENS_B64:-}" ]; then
        echo "Writing tokens from GROK_TOKENS_B64 env..."
        printf '%s' "$GROK_TOKENS_B64" | base64 -d > "$TOKENS_FILE" 2>/dev/null || echo "WARNING: Failed to decode GROK_TOKENS_B64"
    elif [ -n "${GROK_TOKENS:-}" ]; then
        echo "Writing tokens from GROK_TOKENS env..."
        printf '%s\n' "$GROK_TOKENS" | tr ',;' '\n\n' | sed '/^[[:space:]]*$/d' > "$TOKENS_FILE"
    elif [ -n "${TOKENS_URL:-}" ]; then
        echo "Downloading tokens from TOKENS_URL env..."
        if [ -n "${GITHUB_TOKEN:-}" ]; then
            if ! curl -fsSL -H "Authorization: token ${GITHUB_TOKEN}" -H "Accept: application/vnd.github.raw" "$TOKENS_URL" -o "$TOKENS_FILE"; then
                echo "WARNING: Failed to download TOKENS_URL directly"
                if printf '%s' "$TOKENS_URL" | grep -q "api.github.com/repos/.*/contents/"; then
                    RAW_TOKENS_URL=$(printf '%s' "$TOKENS_URL" | sed -E 's#https://api.github.com/repos/([^/]+)/([^/]+)/contents/(.*)#https://raw.githubusercontent.com/\1/\2/main/\3#')
                    echo "Trying GitHub raw fallback..."
                    curl -fsSL -H "Authorization: token ${GITHUB_TOKEN}" "$RAW_TOKENS_URL" -o "$TOKENS_FILE" || echo "WARNING: Failed to download GitHub raw fallback"
                fi
            fi
        elif ! curl -fsSL "$TOKENS_URL" -o "$TOKENS_FILE"; then
            echo "WARNING: Failed to download TOKENS_URL"
        fi
    elif [ -n "${TOKENS_FILE:-}" ] && [ -f "$TOKENS_FILE" ]; then
        echo "Using existing TOKENS_FILE env: $TOKENS_FILE"
    fi
    
    if [ -f "$SQL_FILE" ] && [ -s "$SQL_FILE" ]; then
        SQL_SIZE=$(wc -c < "$SQL_FILE")
        echo "Loading from $SQL_FILE ($SQL_SIZE bytes)..."
        mysql -u root cool < "$SQL_FILE" 2>&1
        FINAL=$(mysql -u root -N -e "SELECT COUNT(*) FROM cool.grok_session;" 2>/dev/null || echo "ERROR")
        echo "Result: $FINAL rows"
    elif [ -f "$TOKENS_FILE" ] && [ -s "$TOKENS_FILE" ]; then
        echo "Loading from $TOKENS_FILE via Python..."
        TOKENS_FILE="$TOKENS_FILE" python3 /app/import-tokens.py 2>&1
        FINAL=$(mysql -u root -N -e "SELECT COUNT(*) FROM cool.grok_session;" 2>/dev/null || echo "ERROR")
        echo "Result: $FINAL rows"
    else
        echo "WARNING: No token files found and no GROK_TOKENS/GROK_TOKENS_B64 env provided!"
        ls -la /app/data/ 2>&1
    fi
else
    echo "Already have $TOKEN_COUNT tokens"
fi

echo "=== ENTRYPOINT INIT COMPLETE $(date) ==="

# Auto-register all grok_session tokens into grok_user
echo "=== Auto-register tokens to grok_user ==="
WAIT_LOOP=0
while [ $WAIT_LOOP -lt 60 ]; do
    USER_TABLE=$(mysql -u root -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='cool' AND table_name='grok_user';" 2>/dev/null || echo "0")
    if [ "$USER_TABLE" != "0" ]; then
        echo "grok_user table exists"
        break
    fi
    sleep 5
    WAIT_LOOP=$((WAIT_LOOP + 1))
done

SESSION_COUNT=$(mysql -u root -N -e "SELECT COUNT(*) FROM cool.grok_session;" 2>/dev/null || echo "0")
USER_COUNT=$(mysql -u root -N -e "SELECT COUNT(*) FROM cool.grok_user;" 2>/dev/null || echo "0")
echo "grok_session: $SESSION_COUNT, grok_user: $USER_COUNT"

if [ "$SESSION_COUNT" != "0" ] && [ "$USER_COUNT" = "0" ]; then
    echo "Registering all sessions as users..."
    mysql -u root cool -e "
INSERT INTO grok_user (createTime, updateTime, userToken, expireTime, isPro, remark, count)
SELECT NOW(), NOW(), officialSession, '2026-12-31 00:00:00', isPro, 'auto-register', 0
FROM grok_session
WHERE officialSession IS NOT NULL AND officialSession != '';
" 2>&1
    FINAL_USER=$(mysql -u root -N -e "SELECT COUNT(*) FROM cool.grok_user;" 2>/dev/null || echo "ERROR")
    echo "grok_user after registration: $FINAL_USER"
else
    echo "Skip registration (sessions=$SESSION_COUNT, users=$USER_COUNT)"
fi

echo "=== Prepare lightweight login token ==="
LOGIN_HTML="/app/resource/public/login.html"
TOKEN_JS="/app/resource/public/token.js"
LOGIN_TOKEN=$(mysql -u root -N -e "SELECT userToken FROM cool.grok_user WHERE userToken IS NOT NULL AND userToken != '' ORDER BY count ASC, updateTime ASC LIMIT 1;" 2>/dev/null | head -n 1 || true)
if [ -z "$LOGIN_TOKEN" ]; then
    LOGIN_TOKEN=$(mysql -u root -N -e "SELECT officialSession FROM cool.grok_session WHERE officialSession IS NOT NULL AND officialSession != '' ORDER BY count ASC, updateTime ASC LIMIT 1;" 2>/dev/null | head -n 1 || true)
fi
if [ -z "$LOGIN_TOKEN" ] && [ -f "/app/data/tokens.txt" ]; then
    LOGIN_TOKEN=$(sed '/^[[:space:]]*$/d' /app/data/tokens.txt | head -n 1 || true)
fi
if [ -n "$LOGIN_TOKEN" ]; then
    ESCAPED_TOKEN=$(printf '%s' "$LOGIN_TOKEN" | sed "s/[\\&]/\\\\&/g; s/'/\\\\'/g")
    printf "window.__GROK_LOGIN_TOKEN__ = '%s';\nwindow.__GROK_LOGIN_TOKEN_READY__ = true;\nwindow.__GROK_LOGIN_TOKEN_ERROR__ = '';\n" "$ESCAPED_TOKEN" > "$TOKEN_JS"
    echo "Generated runtime token.js for lightweight login page"
else
    printf "window.__GROK_LOGIN_TOKEN__ = '';\nwindow.__GROK_LOGIN_TOKEN_READY__ = false;\nwindow.__GROK_LOGIN_TOKEN_ERROR__ = 'missing';\n" > "$TOKEN_JS"
    echo "WARNING: No login token available; wrote empty token.js"
fi

echo "=== ALL INIT COMPLETE ==="

# Wait for child processes
wait $APP_PID
