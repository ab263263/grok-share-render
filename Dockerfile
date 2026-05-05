FROM lyy0709/grok-share-server:dev

# Install MySQL + Redis + Supervisor
RUN apt-get update && apt-get install -y \
    mysql-server \
    redis-server \
    supervisor \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# MySQL init script
COPY init-db.sh /init-db.sh
RUN chmod +x /init-db.sh

# Token import script
COPY import-tokens.py /app/import-tokens.py

# MySQL config for low memory (Render free = 512MB)
RUN echo "[mysqld]\nskip-name-resolve\ninnodb_buffer_pool_size=64M\nmax_connections=50\ntable_open_cache=64\nperformance_schema=OFF" > /etc/mysql/conf.d/lowmem.cnf

# Redis config for low memory
RUN echo "maxmemory 32mb\nmaxmemory-policy allkeys-lru" >> /etc/redis/redis.conf

# Overwrite app config to use localhost
COPY config.yaml /app/config.yaml

# Init entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8001

CMD ["/entrypoint.sh"]
