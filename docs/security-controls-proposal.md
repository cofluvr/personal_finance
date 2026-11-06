# Proposal: Project-Level Claude Code Controls

Status: **proposal, not applied.** No `.claude/` folder exists in this repository.

Sources: `code.claude.com/docs/en/permissions`, `settings`, `settings-reference`,
`sandboxing`, `hooks` and `vs-code`, read on 2026-11-05. Those pages were read by a
fetch helper, and part of its report came from a summary of long pages. Items
marked *(summary)* below need checking before being relied on.

## Compatibility: not yet verified

The installed version is unknown. `claude` is not on PATH here, and finding the
extension would mean looking outside this repository. Check `/status` in the
Claude panel, or the extension's version in the Extensions view.

| Needs at least | For |
|---|---|
| v2.1.314 | `permissions.blockWritesOutsideWorkingDirectories` |
| v2.1.285 | A user-level `allowUnsandboxedCommands: false` not being overridden by a project |
| v2.1.280 | The `/sandbox` and `/status` panels in VS Code |
| v2.1.257 | `permissions.blockReadsOutsideWorkingDirectories` |

The VS Code docs show a sandbox control but do not say it behaves identically to
the CLI, so sandbox behaviour must be tested in the extension itself.

## Proposed `.claude/settings.json`

```json
{
  "permissions": {
    "blockReadsOutsideWorkingDirectories": true,
    "blockWritesOutsideWorkingDirectories": true,
    "deny": [
      "Edit(./.claude/**)",
      "Read(./.env)",
      "Read(./.env.*)",
      "mcp__claude-vscode__getDiagnostics"
    ],
    "ask": [
      "WebFetch",
      "WebSearch"
    ]
  },
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "allowUnsandboxedCommands": false,
    "filesystem": {
      "denyRead": ["~/"],
      "allowRead": [".", "~/.gitconfig"]
    }
  }
}
```

No network domains are allowed. The list starts empty, and a new domain prompts for
approval. This is what makes `git push` and `pip install` fail or ask, rather than
a `Bash(git push *)` rule, which the docs call out as easy to sidestep.

## What covers what

| Access path | Control | Strength |
|---|---|---|
| Read, Grep, Glob tools | `blockReadsOutsideWorkingDirectories`, `Read` deny rules | Permission check in Claude Code. Grep and Glob are "best-effort" for deny rules |
| Edit, Write, NotebookEdit tools | `blockWritesOutsideWorkingDirectories`, `Edit` deny rules | Permission check in Claude Code |
| Bash commands that name a file (`cat`, `sed`) | `Read` and `Edit` deny rules, plus the sandbox | Rules match recognized commands only. The sandbox is the real control |
| Python scripts and other subprocesses | Sandbox only | OS-level (Seatbelt on macOS), and covers child processes. Deny rules **do not apply** |
| Network from Bash and subprocesses | Sandbox proxy | OS-level routing with an allowlist |
| WebFetch, WebSearch | `ask` rules | Not sandboxed. Each use prompts |
| Disabling the sandbox for one command | `allowUnsandboxedCommands: false` | Claude Code ignores `dangerouslyDisableSandbox` |
| Claude changing these rules | `Edit(./.claude/**)` deny, which also feeds the sandbox write deny | Stops Claude. You can still edit by hand |

## Required tooling exceptions

| Tool | Need | Handling |
|---|---|---|
| git commits | `~/.gitconfig` holds your identity | `allowRead` entry above, or set `user.name` and `user.email` in this repo and drop the entry |
| Python | Runs from `/Library/Frameworks`, outside `~/` | None needed (location seen in this session) |
| `.venv`, pytest, Hypothesis | Project folder and system temp | None expected. Temp writes are allowed by default |
| Dependency installs | `pypi.org`, `files.pythonhosted.org` | Not allowed by default. Approve per install |
| `git push` | GitHub | Blocked or prompts. Run it yourself |

## Before applying

1. Confirm the version meets v2.1.314. If not, update or drop the key it needs.
2. **Open `personal_finance/` itself as the VS Code folder.** This session began in
   the parent folder. Project settings load from the project root, and the
   working-directory blocks follow the working directories, so opening the parent
   would leave sibling projects in scope.
3. Restart the session after adding the file.

## How it would be verified

Create a harmless canary file yourself, such as `~/pf-canary.txt`, and then:

| Check | Expected |
|---|---|
| Read tool on the canary | Refused |
| `cat` on the canary | Refused |
| A Python script opening the canary | Refused. This is the one that proves the sandbox |
| Python script writing outside the repo | Refused |
| Connecting to any host from Python | Refused or prompts |
| `dangerouslyDisableSandbox` on a command | Ignored |
| Editing `.claude/settings.json` through Claude | Refused |
| `pytest` and a local `git commit` | Work |

Only behaviour that passes these checks should be described as enforced.

## Residual limitations

This does not give complete isolation.

- **Whatever Claude reads is sent to Anthropic to be processed.** No setting here
  changes that for content inside the repo, so real data must stay out of it. This
  is why the synthetic-data rule remains the primary control.
- Built-in file tools are not sandboxed. They rely on Claude Code's own permission
  checks.
- Command hooks, local MCP servers, LSP servers, the status line and commands you
  type at the `!` prompt run with full access.
- Connected services such as Claude Docs and Artifact publishing are separate
  tools that the sandbox does not cover. They can send content off the machine and
  rely on permission prompts. You could also deny them by name.
- Claude Code's own files, the session scratchpad and project memory stay writable
  *(summary)*.
- The docs conflict on how `blockReadsOutsideWorkingDirectories` treats Bash *(summary)*.
  The sandbox is therefore what this proposal relies on for shell reads.
- `.claude/settings.local.json` and user or managed settings can change effective
  behaviour. User-level settings were not inspected.
- Sandbox availability depends on the OS, and a macOS sandbox bug or misconfiguration
  would weaken every control in the shell row.
