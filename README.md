# xiejunjie.indevs.in

Personal static website served through Cloudflare Tunnel.

## Local preview

```bash
python3 -m http.server 8787 --bind 127.0.0.1
```

## Routes

- `/` and static pages: local static site on `127.0.0.1:8787`
- `/health`: Hermes API Server on `127.0.0.1:8642`
- `/v1/*`: Hermes API Server on `127.0.0.1:8642`
