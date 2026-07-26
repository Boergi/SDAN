# Example Apps

These apps are examples for the proxy integration pattern. Real applications should live in
their own repositories and attach only their public web container to the shared proxy network.
The proxy stack creates the shared `proxy_net` network; app stacks consume it as an
external network.

Pattern:

```yaml
services:
  app:
    networks:
      app_net:
      proxy_net:
        aliases:
          - my-app

  database:
    networks:
      - app_net

networks:
  app_net:
    driver: bridge

  proxy_net:
    external: true
    name: proxy_net
```

The proxy config can then route to `http://my-app:PORT`.
