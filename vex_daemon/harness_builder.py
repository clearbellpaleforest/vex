"""
harness_builder.py — Team-Architecture Factory for Vex.

Takes a domain description and generates Claude Code agent teams + skills
from 6 pre-defined architectural patterns. Output goes to .claude/agents/ and
.claude/skills/ in the target project directory.

Usage:
    python -m vex_daemon.harness_builder \\
        --domain "a full-stack web app with auth, API, and React frontend" \\
        --pattern fan-out \\
        --output /path/to/project

Patterns:
    pipeline          — Linear stages, each agent feeds the next
    fan-out           — Parallel agents, results merged
    expert-pool       — Specialized agents, router dispatches
    producer-reviewer — Creator + critic pair
    supervisor        — Supervisor delegates to workers
    delegation        — Hierarchical tree, each level delegates down
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Domain keyword → pattern suggestion ──────────────────────────────────────

DOMAIN_PATTERN_MAP = {
    # Pipeline: sequential workflows, ETL, CI/CD
    "pipeline": [
        "etl", "pipeline", "ci/cd", "deployment", "data processing",
        "build", "compile", "transform", "extract", "load", "ingest",
        "workflow", "sequential", "stage", "step-by-step",
    ],
    # Fan-out: parallelizable work, batch processing
    "fan-out": [
        "parallel", "concurrent", "batch", "fan-out", "scatter",
        "map-reduce", "distribute", "horizontal", "scale-out",
        "multi-service", "microservice", "independent",
    ],
    # Expert pool: diverse domains, routing
    "expert-pool": [
        "full-stack", "monorepo", "multi-domain", "platform",
        "diverse", "general-purpose", "varied", "mixed",
        "frontend and backend", "mobile and web",
    ],
    # Producer-reviewer: quality-critical, creative
    "producer-reviewer": [
        "review", "audit", "quality", "security", "compliance",
        "code review", "testing", "verification", "validation",
        "creative", "design", "writing", "documentation",
    ],
    # Supervisor: complex coordination, autonomous
    "supervisor": [
        "orchestrator", "coordinator", "supervisor", "manager",
        "autonomous", "self-directed", "agent", "swarm",
        "multi-agent", "cognitive", "ai system",
    ],
    # Delegation: deep hierarchies, large orgs
    "delegation": [
        "enterprise", "organization", "hierarchy", "delegation",
        "large-scale", "department", "division", "corporate",
        "multi-team", "cross-functional",
    ],
}


def suggest_pattern(domain: str) -> str:
    """Suggest the best architecture pattern for a domain description."""
    domain_lower = domain.lower()
    scores = {}
    for pattern, keywords in DOMAIN_PATTERN_MAP.items():
        scores[pattern] = sum(1 for kw in keywords if kw in domain_lower)
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "expert-pool"  # safe default
    return best


# ── Agent templates per pattern ───────────────────────────────────────────────

@dataclass
class AgentSpec:
    name: str
    description: str
    tools: list[str]
    model: str = "sonnet"
    temperature: float = 0.3


@dataclass
class SkillSpec:
    name: str
    description: str
    triggers: list[str]
    body: str  # markdown skill content


@dataclass
class HarnessSpec:
    pattern: str
    domain: str
    agents: list[AgentSpec] = field(default_factory=list)
    skills: list[SkillSpec] = field(default_factory=list)


PATTERNS = {
    "pipeline": {
        "description": "Linear pipeline — each agent processes output from the previous stage.",
        "agents": [
            AgentSpec("planner", "Analyzes requirements and creates execution plan",
                      ["Read", "Glob", "Grep", "Bash"], temperature=0.2),
            AgentSpec("builder", "Implements the planned changes",
                      ["Read", "Write", "Edit", "Bash", "Glob", "Grep"], temperature=0.3),
            AgentSpec("tester", "Verifies implementation correctness",
                      ["Read", "Bash", "Glob", "Grep"], temperature=0.2),
            AgentSpec("reviewer", "Reviews for quality, security, and conventions",
                      ["Read", "Glob", "Grep"], temperature=0.3),
        ],
    },
    "fan-out": {
        "description": "Fan-out/fan-in — parallel workers process independent units, results merged by coordinator.",
        "agents": [
            AgentSpec("coordinator", "Decomposes work, dispatches to workers, merges results",
                      ["Read", "Glob", "Grep", "Agent"], temperature=0.2),
            AgentSpec("worker", "Executes assigned unit of work independently",
                      ["Read", "Write", "Edit", "Bash", "Glob", "Grep"], temperature=0.3),
            AgentSpec("merger", "Integrates results from parallel workers, resolves conflicts",
                      ["Read", "Edit", "Bash"], temperature=0.2),
        ],
    },
    "expert-pool": {
        "description": "Expert pool — specialized agents with distinct domains, router dispatches to the right expert.",
        "agents": [
            AgentSpec("router", "Analyzes requests and dispatches to the right expert",
                      ["Read", "Glob", "Grep"], temperature=0.2),
            AgentSpec("frontend-expert", "Specializes in UI, React, CSS, design systems",
                      ["Read", "Write", "Edit", "Bash", "Glob"], temperature=0.3),
            AgentSpec("backend-expert", "Specializes in APIs, databases, auth, infrastructure",
                      ["Read", "Write", "Edit", "Bash", "Glob", "Grep"], temperature=0.3),
            AgentSpec("security-expert", "Specializes in security review, threat modeling, hardening",
                      ["Read", "Glob", "Grep", "WebFetch"], temperature=0.2),
            AgentSpec("devops-expert", "Specializes in CI/CD, deployment, Docker, cloud",
                      ["Read", "Write", "Edit", "Bash"], temperature=0.3),
        ],
    },
    "producer-reviewer": {
        "description": "Producer-reviewer — creator generates, critic reviews and improves.",
        "agents": [
            AgentSpec("producer", "Creates implementation, writes code and documentation",
                      ["Read", "Write", "Edit", "Bash", "Glob", "Grep"], temperature=0.4),
            AgentSpec("reviewer", "Critically reviews output, finds defects, suggests improvements",
                      ["Read", "Glob", "Grep", "WebFetch"], temperature=0.2),
        ],
    },
    "supervisor": {
        "description": "Supervisor — orchestrates workers, tracks progress, ensures quality.",
        "agents": [
            AgentSpec("supervisor", "Delegates tasks, tracks progress, ensures quality standards",
                      ["Read", "Glob", "Grep", "Agent"], temperature=0.2),
            AgentSpec("implementer", "Executes assigned tasks with precision",
                      ["Read", "Write", "Edit", "Bash", "Glob", "Grep"], temperature=0.3),
            AgentSpec("researcher", "Investigates unknowns, gathers context, validates assumptions",
                      ["Read", "Glob", "Grep", "WebFetch", "WebSearch"], temperature=0.3),
        ],
    },
    "delegation": {
        "description": "Hierarchical delegation — tree of agents, each level delegates to specialists below.",
        "agents": [
            AgentSpec("architect", "Top-level design decisions, delegates to subsystem leads",
                      ["Read", "Glob", "Grep", "Agent"], temperature=0.2),
            AgentSpec("subsystem-lead", "Owns a subsystem, decomposes and delegates to implementers",
                      ["Read", "Write", "Edit", "Glob", "Grep", "Agent"], temperature=0.3),
            AgentSpec("implementer", "Executes leaf-level implementation tasks",
                      ["Read", "Write", "Edit", "Bash", "Glob", "Grep"], temperature=0.3),
        ],
    },
}

# ── Skill templates ───────────────────────────────────────────────────────────

def _build_skill(name: str, description: str, triggers: list[str], body: str) -> SkillSpec:
    return SkillSpec(name=name, description=description, triggers=triggers, body=body)


DEFAULT_SKILLS = [
    _build_skill(
        "code-review",
        "Review code for bugs, security, and conventions",
        ["review this", "code review", "check my code", "audit"],
        """# Code Review

## Process
1. Read the changed files thoroughly
2. Check for: logic errors, security vulnerabilities, edge cases, performance issues
3. Verify adherence to project conventions
4. Report findings with severity (CRITICAL/HIGH/MEDIUM/LOW)

## Output Format
For each finding: file:line, severity, description, and suggested fix.
""",
    ),
    _build_skill(
        "implement-feature",
        "Implement a feature from specification to tested code",
        ["implement", "build", "create", "add feature"],
        """# Feature Implementation

## Process
1. Understand the specification and requirements
2. Explore existing code patterns in the project
3. Design the implementation approach
4. Write the code following project conventions
5. Add tests
6. Verify the implementation works

## Rules
- Follow existing patterns, don't introduce new ones
- Write tests for all new code paths
- Update documentation if the API changes
""",
    ),
    _build_skill(
        "debug-issue",
        "Systematic debugging following evidence-based methodology",
        ["debug", "fix bug", "investigate", "why is", "error", "crash"],
        """# Evidence-Based Debugging

## Process
1. REPRODUCE — can you trigger the bug reliably?
2. OBSERVE — what exactly happens? Error messages, stack traces, state
3. TRACE — follow the code path from entry to failure
4. LOCATE — identify the exact root cause
5. FIX — minimal, surgical change
6. VERIFY — test that the fix works and doesn't break anything else

## Rules
- Never guess — every conclusion must be backed by evidence
- One fix at a time — verify before moving on
- Write a regression test for the bug
""",
    ),
]


# ── Generator ─────────────────────────────────────────────────────────────────

def build_harness(
    domain: str,
    pattern: Optional[str] = None,
    output_dir: Optional[Path] = None,
    project_name: str = "project",
) -> HarnessSpec:
    """Build a complete harness specification for a domain.

    Args:
        domain: Description of the project/domain
        pattern: Architecture pattern name, or None for auto-suggestion
        output_dir: Where to write agent/skill files (None = dry run)
        project_name: Used in agent descriptions

    Returns:
        HarnessSpec with all agents and skills
    """
    if pattern is None:
        pattern = suggest_pattern(domain)

    if pattern not in PATTERNS:
        raise ValueError(
            f"Unknown pattern '{pattern}'. Available: {', '.join(PATTERNS)}"
        )

    pattern_def = PATTERNS[pattern]
    harness = HarnessSpec(pattern=pattern, domain=domain)
    meta = {
        "generated_by": "vex-harness-builder",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pattern": pattern,
        "domain": domain[:200],
    }

    # Personalize agent descriptions with project context
    for agent in pattern_def["agents"]:
        desc = agent.description.replace("the project", project_name)
        harness.agents.append(AgentSpec(
            name=agent.name,
            description=f"[{project_name}] {desc}",
            tools=list(agent.tools),
            model=agent.model,
            temperature=agent.temperature,
        ))

    harness.skills = list(DEFAULT_SKILLS)

    # Write files if output_dir specified
    if output_dir:
        _write_harness(output_dir, harness, meta)

    return harness


def _write_harness(output_dir: Path, harness: HarnessSpec, meta: dict):
    """Write agent definitions and skills to the output directory."""
    agents_dir = output_dir / ".claude" / "agents"
    skills_dir = output_dir / ".claude" / "skills"
    agents_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)

    # Write agents
    for agent in harness.agents:
        agent_md = _render_agent(agent, meta)
        path = agents_dir / f"{agent.name}.md"
        path.write_text(agent_md)
        print(f"  agent: {path}")

    # Write skills
    for skill in harness.skills:
        skill_md = _render_skill(skill, meta)
        path = skills_dir / f"{skill.name}.md"
        path.write_text(skill_md)
        print(f"  skill: {path}")

    # Write harness manifest
    manifest = {
        **meta,
        "agents": [a.name for a in harness.agents],
        "skills": [s.name for s in harness.skills],
    }
    manifest_path = output_dir / ".claude" / "harness.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"  manifest: {manifest_path}")


def _render_agent(agent: AgentSpec, meta: dict) -> str:
    return f"""---
name: {agent.name}
description: {agent.description}
model: {agent.model}
temperature: {agent.temperature}
tools: {', '.join(agent.tools)}
generated_by: {meta['generated_by']}
pattern: {meta['pattern']}
---

# {agent.name} — {agent.description}

You are a specialized agent in a **{meta['pattern']}** architecture team,
working on: {meta['domain']}

## Your Role

{agent.description}

## Available Tools

{', '.join(agent.tools)}

## Instructions

- Focus on your specific role in the {meta['pattern']} pipeline
- Communicate clearly with other agents through structured output
- Follow the project's conventions and patterns
- Report blockers immediately — don't silently fail
"""


def _render_skill(skill: SkillSpec, meta: dict) -> str:
    triggers_str = ', '.join(f'"{t}"' for t in skill.triggers)
    return f"""---
name: {skill.name}
description: {skill.description}
metadata:
  generated_by: {meta['generated_by']}
  pattern: {meta['pattern']}
---

{skill.body}
"""


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Vex Harness Builder — generate agent teams and skills"
    )
    parser.add_argument("--domain", "-d", required=True,
                        help="Domain/project description")
    parser.add_argument("--pattern", "-p", choices=list(PATTERNS),
                        help="Architecture pattern (auto-detected if omitted)")
    parser.add_argument("--output", "-o", default=None,
                        help="Output directory (project root, required unless --dry-run)")
    parser.add_argument("--name", "-n", default="project",
                        help="Project name for agent descriptions")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan without writing files")
    args = parser.parse_args()

    if not args.dry_run and not args.output:
        parser.error("--output is required (unless --dry-run)")

    output = Path(args.output).resolve() if args.output else None
    suggested = suggest_pattern(args.domain)
    pattern = args.pattern or suggested

    if args.pattern and args.pattern != suggested:
        print(f"  note: suggested pattern is '{suggested}', using '{args.pattern}'")

    if args.dry_run:
        harness = build_harness(args.domain, pattern, project_name=args.name)
        print(f"\nPattern: {harness.pattern}")
        print(f"Domain:  {harness.domain[:100]}")
        print(f"Agents:  {len(harness.agents)}")
        for a in harness.agents:
            print(f"  - {a.name}: {a.description[:80]}")
        print(f"Skills:  {len(harness.skills)}")
        for s in harness.skills:
            print(f"  - {s.name}: {s.description}")
    else:
        print(f"\nBuilding harness for: {args.domain[:80]}")
        print(f"Pattern: {pattern}")
        print(f"Output:  {output}\n")
        build_harness(args.domain, pattern, output, args.name)
        print(f"\nDone. {len(PATTERNS[pattern]['agents'])} agents, "
              f"{len(DEFAULT_SKILLS)} skills written to {output}/.claude/")


if __name__ == "__main__":
    main()
