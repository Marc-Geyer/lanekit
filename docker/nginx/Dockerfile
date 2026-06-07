FROM nginx:1.27-alpine

# dcron: runs "nginx -s reload" every 12 h to pick up renewed certificates
RUN apk add --no-cache dcron

COPY entrypoint.sh /entrypoint.sh
COPY templates  /etc/nginx/templates/

RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
