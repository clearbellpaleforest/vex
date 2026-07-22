---
name: harness-builder
description: Build agent teams and skills for Claude Code projects using 6 architecture patterns. Use when the user asks to "build a harness", "create an agent team", "set up agents for this project", or "design a multi-agent architecture".
---

# Harness Builder — Team-Architecture Factory

Designs domain-specific agent teams and generates the skills they use.
Six pre-defined architecture patterns: Pipeline, Fan-out/Fan-in, Expert Pool,
Producer-Reviewer, Supervisor, Hierarchical Delegation.

## When to Use

- "build a harness for this project"
- "create an agent team for X"
- "set up Claude Code agents for this repo"
- "what architecture pattern should I use?"
- "generate skills for my team"

## Process

### Step 1: Understand the Domain

Ask clarifying questions:
- What does the project do? (one paragraph)
- What's the tech stack?
- How many developers? What's the team structure?
- What are the main types of tasks? (coding, reviewing, debugging, deploying?)
- Any specific security/compliance requirements?

### Step 2: Suggest the Pattern

Run pattern detection:

```bash
python3 -m vex_daemon.harness_builder --domain "<domain description>" --dry-run
```

Or via the daemon API:

```bash
curl -s http://localhost:8520/harness/suggest \
  -H 'Content-Type: application/json' \
  -d '{"domain": "<domain description>"}'
```

Show the user the suggested pattern and 1-2 alternatives. Explain the tradeoff.
Let the user pick.

### Step 3: Generate the Harness

```bash
python3 -m vex_daemon.harness_builder \
  --domain "<domain>" \
  --pattern <chosen-pattern> \
  --output <project-root> \
  --name "<Project Name>"
```

Or via API:

```bash
curl -s http://localhost:8520/harness/build \
  -H 'Content-Type: application/json' \
  -d '{"domain": "<domain>", "pattern": "<pattern>", "output": "<path>", "name": "<name>"}'
```

This creates:
```
project/.claude/
├── agents/
│   ├── <agent-1>.md
│   ├── <agent-2>.md
│   └── ...
├── skills/
│   ├── code-review.md
│   ├── implement-feature.md
│   └── debug-issue.md
└── harness.json
```

### Step 4: Review with the User

Show the generated agent team. Explain each agent's role.
Ask if they want adjustments (add/remove agents, change tools, adjust temperature).

### Step 5: Commit

The harness files are ready to use. The next Claude Code session in that
project directory will pick up the agents and skills automatically.

## Architecture Patterns

| Pattern | Best For | Agent Count |
|---------|----------|-------------|
| **Pipeline** | Sequential workflows (ETL, CI/CD, data processing) | 4 |
| **Fan-out/Fan-in** | Parallelizable work (batch processing, microservices) | 3 |
| **Expert Pool** | Diverse domains (full-stack, monorepo, platform) | 5 |
| **Producer-Reviewer** | Quality-critical (security audit, code review, docs) | 2 |
| **Supervisor** | Complex coordination (autonomous systems, swarms) | 3 |
| **Delegation** | Large organizations (enterprise, multi-team) | 3 |

## Customization

Generated agents have sensible defaults but can be tuned:
- **model**: haiku (fast/cheap), sonnet (balanced), opus (deep reasoning)
- **temperature**: 0.1-0.2 (deterministic), 0.3-0.5 (creative)
- **tools**: add/remove based on what the agent actually needs
- **description**: make it more specific to the project

Edit the generated files in `.claude/agents/` and `.claude/skills/` directly.
