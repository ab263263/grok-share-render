#!/bin/bash
set -e

# Initialize MySQL data directory if needed
if [ ! -d "/var/lib/mysql/mysql" ]; then
    echo "Initializing MySQL..."
    mysqld --initialize-insecure --user=root
fi

# Start supervisor (manages MySQL, Redis, and the app)
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
