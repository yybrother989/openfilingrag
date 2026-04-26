---
name: Bug report
about: Something is broken or behaving unexpectedly
title: "[bug] "
labels: bug
---

## What happened

<!-- A clear description of what went wrong. -->

## Expected behavior

<!-- What you thought would happen. -->

## Reproduction

Steps to reproduce, ideally as a sequence of shell commands or HTTP requests:

```bash
# e.g.
make edgar-pull TICKER=AAPL TYPES=10-K LIMIT=1
curl -X POST http://localhost:8000/research/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"...","ticker":"AAPL"}'
```

## Environment

- OpenFilingRAG commit / version:
- Python version (`python --version`):
- OS:
- Database: Supabase (region: `____`) | local Postgres
- Mock mode: yes / no  (`OPENAI_API_KEY` set?)
- LLM provider (if real): openai | anthropic
- Browser (UI bugs only):

## Logs / output

<details>
<summary>Full stack trace or relevant log lines</summary>

```
<paste here>
```

</details>
