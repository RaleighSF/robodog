# OmniControl Platform — Design Specification

**Version:** 1.0 · **Date:** 2026-09-02 · **Author:** Raleigh Murch, NTT DATA Physical AI

---

## What this is

A complete design specification for **OmniControl**, a multi-robot mission authoring and
execution platform. An operator selects a robot archetype, builds or loads a 3D map, composes
a patrol mission by placing waypoints and attaching actions, deploys that mission to a
physical robot, and reviews the data it captured.

The first supported robot is the **Unitree Go2** quadruped. The architecture is explicitly
designed so that the second robot — a Unitree G1 humanoid, an AMR, a drone — requires
writing a driver and a capability descriptor, and **no changes to the platform**.

## Who this is written for

**An engineer or an AI agent with zero prior context on this project.** Every document is
self-contained. Nothing assumes familiarity with the predecessor system, the Unitree SDK,
the team, or prior conversations. Where knowledge came from painful field experience, the
document says so and explains the root cause rather than just stating the rule.

## How to read it

Read in order for full context. Read individually if you know what you need.

| # | Document | Read it when |
|---|---|---|
| **01** | [Overview & Product Definition](01_OVERVIEW.md) | Starting here. Vision, users, scope, glossary. |
| **02** | [System Architecture](02_ARCHITECTURE.md) | Understanding components, processes, deployment topology. |
| **03** | [Contracts & Data Model](03_CONTRACTS.md) | **The heart of the spec.** Every schema, every interface. |
| **04** | [User Experience Specification](04_UX_SPEC.md) | Building the frontend. Screens, flows, interactions. |
| **05** | [Design System](05_DESIGN_SYSTEM.md) | Implementing the visual layer. Tokens, type, motion. |
| **06** | [Go2 Driver Reference](06_GO2_DRIVER_REFERENCE.md) | Writing or debugging the Unitree Go2 driver. |
| **07** | [Safety Model](07_SAFETY.md) | **Read before writing any code that moves a robot.** |
| **08** | [Roadmap & Open Questions](08_ROADMAP.md) | Planning the build. What to do first, what is unresolved. |

## The three rules that shape everything

**1. Safety limits are enforced in the driver, never in the UI or the mission executor.**
The predecessor system placed a robot's velocity limits and its deadman watchdog in a *vision
dashboard* on a different machine. That watchdog eventually knocked a standing 15 kg robot to
the floor, because the remote component could not know that its own stop command was unsafe in
the robot's current posture. See [07_SAFETY.md](07_SAFETY.md) §7.2 and
[06_GO2_DRIVER_REFERENCE.md](06_GO2_DRIVER_REFERENCE.md) §E.5.

Anthropic's Model Hardware Standard reached the same conclusion independently: limits are
enforced "at the hardware interface, independent of the model."

**2. Adopt standards; do not invent schemas.** The mission model is VDA 5050 v3.0.0 order
semantics. The robot capability descriptor is a VDA 5050 `factsheet`. Coordinate frames are
REP-103/REP-105. Recording format is MCAP. Every one of these was checked for currency in
September 2026. Inventing a parallel schema costs interoperability and buys nothing.

**3. State clearly what is unverified.** This spec distinguishes confirmed facts from
inferences and open questions throughout, and [08_ROADMAP.md](08_ROADMAP.md) §8.5 collects
every open question in one place. A specification that presents guesses as facts produces
software built on sand.

## A note on the Model Hardware Standard

Anthropic announced **MHS** on 27 August 2026 — six days before this spec was written. It is
directly relevant: an open standard for AI agents to operate physical hardware.

**As of 2026-09-02 there is no published MHS specification.** There is one announcement blog
post and an application-gated research preview. No schema, no SDK, no reference
implementation, no license, no open-source date. Several third-party sites are publishing
invented MHS architecture as fact; none of it is sourced from Anthropic.

This spec therefore designs against MHS's **confirmed semantics** — measure / adjust / limit,
`read`/`write` primitives, driver-level enforcement, shared-memory state — and defines our own
contracts as a labeled extension. When MHS opens up, the MHS adapter becomes a translation
layer, not a rewrite. Details in [03_CONTRACTS.md](03_CONTRACTS.md) §3.9.

## Status of this document

This is a **design specification, not an implementation record.** No OmniControl code exists
yet. Every schema here is a proposal to be validated against reality during Phase 0, and
[08_ROADMAP.md](08_ROADMAP.md) §8.1 exists specifically to make that validation the first
work item rather than an afterthought.
