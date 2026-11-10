# 3x-ui Client Traffic Portal

Enter a 3x-ui client name to see its current data usage. The server calls this panel endpoint for every lookup:

```text
https://panel.astelacademy.ir:20500/SXdaH36ry3U593ZZCh/panel/api/clients/get/{name}
```

The page displays the response's `obj.usedTraffic`, `obj.client.totalGB`, `obj.client.expiryTime`, `obj.client.enable`, and `obj.inboundIds`. Remaining data is calculated as `totalGB - usedTraffic`. A `totalGB` value of zero means unlimited data. This endpoint does not provide separate upload and download counters.

The panel response also contains connection credentials. The portal sends only the fields listed above to the browser; the Bearer token and raw response stay on the server.

## Run locally

Python 3.10 or newer is required. There are no third-party packages.

```bash
cp -n .env.example .env
# For a new setup, edit .env and set XUI_API_TOKEN to an enabled token with access to clients/get.
set -a
source .env
set +a
python3 app.py
```

Open `http://127.0.0.1:8080`, enter a client name, and select **Check usage**. The `.env` file is ignored by Git.

`XUI_CLIENT_URL_TEMPLATE` in `.env.example` already points to the requested panel API. The `{name}` placeholder is replaced with a URL-encoded client name. The panel API is called from the Python server with `Authorization: Bearer <token>`.

## Browser API

The page requests `GET /api/usage?name=<client-name>`. A successful response contains a safe subset of the panel data:

```json
{
  "data": {
    "name": "alice",
    "usedTraffic": 1073741824,
    "totalGB": 21474836480,
    "remainingTraffic": 20401094656,
    "expiryTime": 0,
    "enable": true,
    "inboundIds": [4],
    "fetchedAt": 1794300000000
  }
}
```

## Deployment

Use HTTPS at a reverse proxy and keep `APP_HOST=127.0.0.1` behind it. Protect access to this portal if client names or usage data should not be public. The built-in server applies a per-process rate limit and a short cache; apply a shared rate limit at the proxy if you run multiple replicas.

The upstream panel connection verifies its TLS certificate. Keep `XUI_API_TOKEN` on the server and out of tracked files. If the panel returns 401, check the token; if it returns 403, use a token permitted to access the client endpoint.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
