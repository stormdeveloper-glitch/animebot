# Security Notes

This project is primarily a Python Telegram bot plus an aiohttp web app. Do not add unused runtime services just for "extra protection"; every new process and language runtime increases maintenance and attack surface.

## Current App-Level Protections

- Per-IP web rate limits for normal, API, and media routes.
- Per-user Telegram message/callback throttling.
- Request timeout and concurrent request cap.
- Early blocking for common scanner paths such as `/.env`, `/.git`, `/wp-*`, `/xmlrpc.php`, and `phpmyadmin`.
- Security headers and conservative cache headers.
- Small request body limit on the aiohttp server.

## Recommended Edge Setup

Railway already provides platform-level protection, but for higher-risk traffic use one of these in front of the app:

- Cloudflare DNS/proxy with WAF rules and bot fight mode.
- Caddy reverse proxy using `deploy/caddy/Caddyfile`.
- Nginx reverse proxy using `deploy/nginx/animeuz.conf`.

Only run one edge proxy at a time. On Railway, keep using the Python app directly unless you move to a VPS or a container where a proxy is under your control.

## Environment Knobs

```env
WEB_RATE_LIMIT_PER_MIN=180
WEB_API_RATE_LIMIT_PER_MIN=90
WEB_MEDIA_RATE_LIMIT_PER_MIN=120
WEB_MAX_CONCURRENT_REQUESTS=80
WEB_REQUEST_TIMEOUT_SECONDS=25
BOT_USER_RATE_LIMIT_PER_MIN=80
```

Start with the defaults. Lower them if abuse appears; raise them if real users hit limits.

## Incident Checklist

1. Turn on Railway metrics and check request spikes.
2. Temporarily lower API/media limits.
3. Enable Cloudflare proxy/WAF if a domain is attached.
4. If abuse is Telegram-side, lower `BOT_USER_RATE_LIMIT_PER_MIN`.
5. Keep `BOT_TOKEN`, OAuth secrets, and `.env` out of logs and commits.
