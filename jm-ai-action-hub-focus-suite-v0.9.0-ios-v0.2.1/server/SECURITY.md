# Security Policy

JM-AI Action Hub 0.1.x is designed for a single operator and should be deployed behind HTTPS or a private network.

Do not report secrets in issues. Revoke any exposed Todoist, GitHub, Google, or Action Hub token immediately.

Operational requirements:

- Set a strong `ACTION_HUB_API_KEY`.
- Use `ACTION_HUB_APP_ENV=production` outside local development.
- Keep `ACTION_HUB_EXECUTION_MODE=dry_run` until each connector is verified.
- Never commit `.env`.
- Use least-privilege external tokens.
