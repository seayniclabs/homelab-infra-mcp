# Safety modes

| Mode | Reads | Writes | Destructive |
|------|-------|--------|-------------|
| `normal` | yes | yes | confirmation token required |
| `readonly` / `read-only` | yes | blocked | blocked |
| `dryrun` / `dry-run` | yes | preview only | preview only |

Destructive tools return a `confirmation_required` payload with a 60-second token. Call `confirm_destructive` with that token to execute.
