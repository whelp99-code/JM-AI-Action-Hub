# Security Policy

## Credential boundary

The iOS app stores only an Action Hub device session in Keychain. It must never contain:

- `X-Action-Hub-Key`
- Todoist token
- GitHub token
- Google OAuth credentials
- LLM provider keys
- APNs `.p8` private key

## Network

- Remote Action Hub servers must use HTTPS.
- Plain HTTP is accepted only for loopback development addresses.
- Pairing payloads are rejected when the server URL is not safe.

## Local data

- Refresh tokens are stored in Keychain with `AfterFirstUnlockThisDeviceOnly`.
- Offline captures use App Group files with Data Protection.
- Widget snapshots contain counts and short titles only; no provider tokens.
- Clipboard is read only after an explicit user action.

## Reporting

Do not attach real customer messages, tokens, pairing QR images, or private repository content to public issues. Reproduce with sanitized data.
