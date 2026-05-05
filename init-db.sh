#!/bin/bash
# Wait for MySQL to be ready
for i in $(seq 1 60); do
    if mysqladmin ping -u root --silent 2>/dev/null; then
        echo "MySQL is ready"
        break
    fi
    echo "Waiting for MySQL... ($i/60)"
    sleep 2
done

# Check if database already exists
DB_EXISTS=$(mysql -u root -e "SHOW DATABASES LIKE 'cool';" 2>/dev/null | grep -c cool)

if [ "$DB_EXISTS" = "0" ]; then
    echo "Creating database and importing schema..."
    mysql -u root -e "CREATE DATABASE IF NOT EXISTS cool CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    mysql -u root -e "CREATE USER IF NOT EXISTS 'cool'@'localhost' IDENTIFIED BY '123123'; GRANT ALL PRIVILEGES ON cool.* TO 'cool'@'localhost'; FLUSH PRIVILEGES;"

    # Import schema
    if [ -f /docker-entrypoint-initdb.d/cool-20250228-123947.sql ]; then
        mysql -u root cool < /docker-entrypoint-initdb.d/cool-20250228-123947.sql
        echo "Schema imported successfully"
    else
        echo "Schema file not found, will rely on autoMigrate"
    fi

    # Import tokens if file exists
    if [ -f /app/data/tokens.txt ]; then
        echo "Importing ssotokens..."
        COUNT=0
        while IFS= read -r token; do
            [ -z "$token" ] && continue
            mysql -u root cool -e "INSERT INTO grok_session (createTime, updateTime, email, password, status, isPro, officialSession, remark, sort, count) VALUES (NOW(), NOW(), 'imported_$COUNT', '', 1, 0, '$token', 'auto-import', 0, 0);" 2>/dev/null
            COUNT=$((COUNT + 1))
        done < /app/data/tokens.txt
        echo "Imported $COUNT tokens"
    fi
else
    echo "Database 'cool' already exists, skipping init"

    # Still try to import tokens if table is empty
    TOKEN_COUNT=$(mysql -u root -N -e "SELECT COUNT(*) FROM cool.grok_session;" 2>/dev/null)
    if [ "$TOKEN_COUNT" = "0" ] && [ -f /app/data/tokens.txt ]; then
        echo "Table empty, importing ssotokens..."
        COUNT=0
        while IFS= read -r token; do
            [ -z "$token" ] && continue
            mysql -u root cool -e "INSERT INTO grok_session (createTime, updateTime, email, password, status, isPro, officialSession, remark, sort, count) VALUES (NOW(), NOW(), 'imported_$COUNT', '', 1, 0, '$token', 'auto-import', 0, 0);" 2>/dev/null
            COUNT=$((COUNT + 1))
        done < /app/data/tokens.txt
        echo "Imported $COUNT tokens"
    fi
fi

echo "Init complete"
