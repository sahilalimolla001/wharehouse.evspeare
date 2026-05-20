FROM caddy:2-alpine

WORKDIR /srv

COPY . .
COPY Caddyfile /etc/caddy/Caddyfile
RUN chmod +x /srv/start.sh

CMD ["/srv/start.sh"]
