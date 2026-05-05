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
redis-server /etc/redis.conf --daemonize no &
REDIS_PID=$!

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
echo "=== Token import phase ==="
TOKEN_COUNT=$(mysql -u root -N -e "SELECT COUNT(*) FROM cool.grok_session;" 2>/dev/null || echo "ERROR")
echo "Current grok_session rows: $TOKEN_COUNT"

if [ "$TOKEN_COUNT" = "0" ]; then
    SQL_FILE="/app/data/tokens_import.sql"
    TOKENS_FILE="/app/data/tokens.txt"
    
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
        echo "WARNING: No token files found!"
        ls -la /app/data/ 2>&1
    fi
else
    echo "Already have $TOKEN_COUNT tokens"
fi

echo "=== ENTRYPOINT INIT COMPLETE $(date) ==="

# Wait for child processes
wait $APP_PID
