#!/bin/bash
set -e

mkdir -p /run/mysqld /var/lib/mysql /var/log
chown -R root:root /run/mysqld /var/lib/mysql /var/log || true

# Initialize MariaDB data directory if needed
if [ ! -d "/var/lib/mysql/mysql" ]; then
    echo "Initializing MariaDB..."
    mariadb-install-db --user=root --datadir=/var/lib/mysql >/var/log/mariadb-install.log 2>&1
fi

# Start supervisor (manages MariaDB, Redis, and the app)
exec /usr/bin/supervisord -c /etc/supervisord.conf
