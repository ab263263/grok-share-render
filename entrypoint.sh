#!/bin/bash
set -e

mkdir -p /run/mysqld /var/lib/mysql /var/log
chown -R root:root /run/mysqld /var/lib/mysql /var/log || true

MYSQL_INIT_BIN=""
if command -v mariadb-install-db >/dev/null 2>&1; then
  MYSQL_INIT_BIN="$(command -v mariadb-install-db)"
elif command -v mysql_install_db >/dev/null 2>&1; then
  MYSQL_INIT_BIN="$(command -v mysql_install_db)"
fi

if [ ! -d "/var/lib/mysql/mysql" ]; then
    echo "Initializing MariaDB..."
    if [ -z "$MYSQL_INIT_BIN" ]; then
        echo "No MariaDB init binary found" >&2
        exit 127
    fi
    "$MYSQL_INIT_BIN" --user=root --datadir=/var/lib/mysql >/var/log/mariadb-install.log 2>&1
fi

SUPERVISOR_BIN="$(command -v supervisord || true)"
if [ -z "$SUPERVISOR_BIN" ]; then
    echo "supervisord not found" >&2
    exit 127
fi

# Start supervisor (manages MariaDB, Redis, and the app)
exec "$SUPERVISOR_BIN" -c /etc/supervisord.conf
