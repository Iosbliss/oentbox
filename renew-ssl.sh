#!/bin/bash
cd /opt/oentbox
docker compose stop nginx
certbot renew --quiet
docker compose start nginx
