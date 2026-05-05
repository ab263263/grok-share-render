#!/bin/bash
# init-db.sh - Only create database and users, let autoMigrate handle tables
echo "=== INIT-DB START ==="
echo "Date: $(date)"

# Wait for MySQL to be ready
for i in $(seq 1 60); do
    if mysqladmin ping -u root --silent 2>/dev/null; then
        echo "MySQL ready at attempt $i"
        break
    fi
    sleep 2
done

# Create database and users
echo "Creating database and users..."
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

echo "=== INIT-DB COMPLETE ==="
