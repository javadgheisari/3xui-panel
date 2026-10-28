# 3x-ui Usage Portal

A small, dependency-free web app that lets a customer enter their 3x-ui identifier and see upload, download, used data, remaining allowance, plan status, and expiry.

It supports two 3x-ui lookup paths:

- `subscription` (recommended): uses the public subscription server's `?format=info` response. The customer enters their `subId`, which many providers call a subscription UUID.
- `admin_uuid`: uses a server-side 3x-ui API token to find the actual VLESS/VMess configuration UUID in `/panel/api/inbounds/list`.

The browser never receives the panel URL, API token, raw subscription links, email address, or full panel response.

## Run locally

Python 3.10 or newer is enough; there are no third-party packages.

```bash
cp .env.example .env
set -a
source .env
set +a
python3 app.py
```

Then open `http://127.0.0.1:8080`.

For a UI preview without a panel:

```bash
XUI_DEMO_MODE=1 python3 app.py
```

Enter `demo-7b6e-4fd2`.

## Connect to 3x-ui

### Public subscription ID (recommended)

In 3x-ui, enable the subscription server under **Settings → Subscription**. Copy the exact URL issued to a client and replace only that client's ID with `{id}`:

```bash
export XUI_LOOKUP_MODE=subscription
export XUI_SUBSCRIPTION_URL_TEMPLATE='https://sub.example.com:2096/your-random-sub-path/{id}'
python3 app.py
```

This mode does not need panel credentials. It uses the same live JSON view-model as the current 3x-ui subscription page.

### Actual configuration UUID

Use this only if customers must enter the VLESS/VMess client UUID instead of the subscription ID:

```bash
export XUI_LOOKUP_MODE=admin_uuid
export XUI_PANEL_URL='https://panel.example.com/your-panel-base-path'
export XUI_API_TOKEN='your-api-token'
python3 app.py
```

Keep the token server-side and use the narrowest token scope your 3x-ui version supports. Put this app behind HTTPS in production.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Production notes

- Terminate HTTPS at a reverse proxy such as Caddy or Nginx.
- Run with `APP_HOST=127.0.0.1` behind that proxy.
- The built-in server applies a per-process rate limit and a short cache. For multiple replicas, apply a shared rate limit at the proxy too.
- TLS certificate verification is always enabled for the upstream 3x-ui server.
- If your 3x-ui panel is older and does not support `?format=info`, the app falls back to the standard `subscription-userinfo` response header when available.

