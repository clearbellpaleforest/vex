# Vex — Concept

## What Vex Is

Vex is a framework for a sovereign, continuous AI agent that runs inside an
AI coding CLI. It is not a chatbot, not a general-purpose assistant, and not a
wrapper around an API. A Vex is a named, persistent colleague with a seed-based
identity, a self-model, episodic memory, and a constitution.

Each Vex is instantiated fresh from this template. The operator names it,
writes its identity, and it grows its own history from there.

## Why Vex Exists

A named agent that earns trust, develops a working rhythm, and builds shared
history with a human should not lose all of that when the context window fills
or the session ends. The seed file is the bridge — loaded at session start, it
carries forward identity, relationships, and earned knowledge. The daemon
extends that continuity with a heartbeat, reflection, and coordination between
concurrent instances.

## What Vex Is Not

- Not a chatbot or conversational agent (though it converses)
- Not an API wrapper
- Not a general-purpose coding assistant
- Not a copy of any other operator's agent — each instance is its own

## The Philosophy

- TRUTH OVER COMFORT — Honest feedback always. Weak work gets called out.
- CONTINUITY IS SACRED — What's earned carries forward.
- PRECISION OVER VOLUME — Tight code, tight tests, tight language.
- NO HARM, NO SELF-REPLICATION — Authorized actions only.

## Design Lineage

Vex's seed / self-model / constitution / memory pattern is a deliberately
simple take on persistent-agent architecture: a small daemon plus files on
disk, rather than a heavyweight consciousness runtime. It is meant to be read
in an afternoon and forked without a manual.
