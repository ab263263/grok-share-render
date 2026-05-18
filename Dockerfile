FROM lyy0709/grok-share-server:dev

# Install MariaDB + Redis + Nginx on Alpine-based image
RUN apk add --no-cache \
    mariadb \
    mariadb-client \
    redis \
    curl \
    python3 \
    bash \
    nginx

# Database init script (sequential: mysql → redis → app → tokens)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Token import script. Tokens are provided at runtime by Render env vars,
# not copied into the image or committed to Git.
COPY import-tokens.py /app/import-tokens.py
COPY mirror-broker.py /app/mirror-broker.py
COPY nginx.conf /etc/nginx/http.d/default.conf

# MariaDB low memory config for Render free plan
RUN mkdir -p /etc/my.cnf.d /run/mysqld /var/lib/mysql /var/log /app/data && \
    printf "[mysqld]\nskip-name-resolve\ninnodb_buffer_pool_size=64M\nmax_connections=50\ntable_open_cache=64\nperformance_schema=OFF\nbind-address=127.0.0.1\n" > /etc/my.cnf.d/lowmem.cnf

# Redis low memory config
RUN printf "maxmemory 32mb\nmaxmemory-policy allkeys-lru\nbind 127.0.0.1\nport 6379\n" > /etc/redis.conf

# Overwrite app config to use localhost
COPY config.yaml /app/config.yaml

# Custom login page and front-end enhancements
COPY login.html /app/resource/public/login.html
COPY list.js /app/resource/public/list.js

EXPOSE 8001

CMD ["/entrypoint.sh"]
