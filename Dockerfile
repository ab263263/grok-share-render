FROM lyy0709/grok-share-server:dev

# Install MariaDB + Redis on Alpine-based image
RUN apk add --no-cache \
    mariadb \
    mariadb-client \
    redis \
    curl \
    python3 \
    bash

# Database init script (sequential: mysql → redis → app → tokens)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# SQL schema (not used directly, just for reference)
COPY docker-entrypoint-initdb.d /docker-entrypoint-initdb.d

# Token import script
COPY import-tokens.py /app/import-tokens.py

# Token file
COPY tokens.txt /app/data/tokens.txt

# Pre-generate SQL import file at build time
COPY generate-sql.py /app/generate-sql.py
RUN python3 /app/generate-sql.py

# MariaDB low memory config for Render free plan
RUN mkdir -p /etc/my.cnf.d /run/mysqld /var/lib/mysql /var/log && \
    echo "[mysqld]\nskip-name-resolve\ninnodb_buffer_pool_size=64M\nmax_connections=50\ntable_open_cache=64\nperformance_schema=OFF\nbind-address=127.0.0.1" > /etc/my.cnf.d/lowmem.cnf

# Redis low memory config
RUN echo "maxmemory 32mb\nmaxmemory-policy allkeys-lru\nbind 127.0.0.1" > /etc/redis.conf

# Overwrite app config to use localhost
COPY config.yaml /app/config.yaml

EXPOSE 8001

CMD ["/entrypoint.sh"]
