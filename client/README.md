# adele (client)

Library and CLI: `adele list | describe | query`. No dependency beyond Python 3.11.

## Install

You get two things from the person who runs the server: its URL and your API key. Don't share
the key: the server logs each query under its name.

```bash
uv tool install "git+https://github.com/renaud/adele#subdirectory=client"   # uv: https://docs.astral.sh/uv/
export ADELE_URL=https://<the server>:8443                                  # in ~/.bash_profile or ~/.zshrc
export ADELE_API_KEY=<your key>
adele list
```

adele is not on PyPI: install it with this URL only. Update: `uv tool upgrade adele`.

The client accepts only `https://` (`http://` for localhost), because the key travels in a
header. The server's certificate comes from adele's own authority; its root certificate is in
this package (`src/adele/adele-ca.pem`), so there is nothing else to install.

## For an agent

Give your agent the skill. For Claude Code:

```bash
mkdir -p ~/.claude/skills/adele
curl -fsSL -o ~/.claude/skills/adele/SKILL.md \
  https://raw.githubusercontent.com/renaud/adele/main/skills/adele/SKILL.md
```

Then start it in a shell that has both variables, and ask for example:

- With adele: the average day-ahead price in Switzerland, per month of 2025?
- With adele: how much did Swiss nuclear plants produce per month in 2025?
- With adele: on how many days in 2025 did it rain in Zurich?

## Limits

A result shows at most 1,000 rows: aggregate in SQL. A query runs for at most 30 s; two run at
once on the server, the others wait for up to 60 s.

## Errors

| message | what to do |
|---|---|
| `ADELE_URL must start with https://` | the URL lacks `https://` |
| `CERTIFICATE_VERIFY_FAILED` | update the client. Don't turn the check off |
| `missing or unknown API key` | the key is wrong or revoked |
| `the server is busy` | try again, one query at a time |
