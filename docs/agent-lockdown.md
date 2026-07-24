# Agent lockdown: let the agent model data it cannot read

silueta's profile is only as safe as the rest of the agent's toolbox. If
Claude can run `head data/claims.csv`, the contract is decoration. This
recipe locks a Claude Code project so the **only** way data enters the
session is through a silueta profile.

Three layers, because each one alone has a bypass:

## 1. Deny the Read tool on data paths

`.claude/settings.json`:

```json
{
  "permissions": {
    "deny": [
      "Read(./data/**)",
      "Read(./**/*.csv)",
      "Read(./**/*.xlsx)",
      "Read(./**/*.parquet)",
      "Read(./**/*.sqlite)"
    ],
    "allow": [
      "Bash(silueta *)",
      "Bash(uvx silueta *)"
    ]
  }
}
```

This blocks the Read/Edit tools — but not shell commands.

## 2. Hook the shell bypass

Built-in read-only commands (`cat`, `head`, `tail`, `grep`, `awk`, `cut`,
`sqlite3`, `duckdb`, `python -c "open(...)"`) can read files without a
permission prompt. A `PreToolUse` hook closes that hole
(historically necessary — see anthropics/claude-code#6699):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .claude/hooks/block_data_reads.py"
          }
        ]
      }
    ]
  }
}
```

`.claude/hooks/block_data_reads.py` reads the tool call from stdin and
exits non-zero (blocking the call) when the command references a data path
with anything other than `silueta`:

```python
import json, re, sys

call = json.load(sys.stdin)
cmd = call.get("tool_input", {}).get("command", "")
touches_data = re.search(r"(\bdata/|\.csv\b|\.xlsx\b|\.parquet\b|\.sqlite\b)", cmd)
is_silueta = re.match(r"\s*(uvx\s+)?silueta\b", cmd)
if touches_data and not is_silueta:
    print("blocked: data files are readable only through silueta (see docs/agent-lockdown.md)", file=sys.stderr)
    sys.exit(2)
```

## 3. Give the agent the sanctioned path

Install the skill from this repo (`skills/silueta/`) or tell the agent in
`CLAUDE.md`:

> Data files in `data/` are PII/PHI and must never be read directly.
> Profile them with `silueta scan <files> --out profile.json` and work
> exclusively from the profile. The profile contains no raw values by
> construction and is safe to reason over.

## What this does and does not protect

This stops an agent from *accidentally* pulling raw values into its context,
logs, or generated docs — the realistic failure mode. It is not a sandbox:
a hostile process, or an agent instructed to circumvent the hook, is outside
this threat model. For hard isolation run the session in a container whose
mounts simply don't include raw data — and profile on the host.
