# Security Policy

Please do not open a public issue for a vulnerability.

Report it privately to Mohsen Al-Taie on Telegram: [@K0_MG](https://t.me/K0_MG), or through GitHub's private vulnerability reporting on this repository.

Include the affected version, steps to reproduce and the impact.

## Built-in protections

- `/check` accepts `tiktok.com` links only.
- User-controlled text shown in messages is HTML-escaped.
- File-size limits, per-user job locks and a concurrency cap protect the host.
- The Docker image runs as a non-root user.
- No secrets are stored in the repository.
