FROM lyy0709/grok-share-server:dev

# Install MariaDB + Redis + Supervisor on Alpine-based image
RUN apk add --no-cache \
    mariadb \
    mariadb-client \
    redis \
    supervisor \
    curl \
    python3 \
    bash

# Supervisor config
COPY supervisord.conf /etc/supervisord.conf

# Database init script
COPY init-db.sh /init-db.sh
RUN chmod +x /init-db.sh

# SQL schema
COPY docker-entrypoint-initdb.d /docker-entrypoint-initdb.d

# Token import script
COPY import-tokens.py /app/import-tokens.py

# Token file for auto-import on first startup
COPY tokens.txt /app/data/tokens.txt

# MariaDB low memory config for Render free plan
RUN mkdir -p /etc/my.cnf.d /run/mysqld /var/lib/mysql /var/log && \
    echo "[mysqld]\nskip-name-resolve\ninnodb_buffer_pool_size=64M\nmax_connections=50\ntable_open_cache=64\nperformance_schema=OFF\nbind-address=127.0.0.1" > /etc/my.cnf.d/lowmem.cnf

# Redis low memory config
RUN echo "maxmemory 32mb\nmaxmemory-policy allkeys-lru\nbind 127.0.0.1" > /etc/redis.conf

# Overwrite app config to use localhost
COPY config.yaml /app/config.yaml

# Init entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8001

CMD ["/entrypoint.sh"]
