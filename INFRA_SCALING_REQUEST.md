# Infrastructure Scaling Request — OpenWebUI Platform
**Date:** 2026-05-29  
**From:** Platform Team  
**To:** IT / Infrastructure  
**Subject:** Server upgrade required to support 1 000 users and the Open Terminal feature

---

## Executive Summary

Our internal OpenWebUI deployment is growing from **600 to 1 000 users**. We are also activating **Open Terminal**, a feature that lets the AI run Python code and terminal commands on behalf of users — enabling data analysis, script generation, and file processing directly in the chat interface.

The current hardware (4 × 15 GB / 4 vCPU nodes) can be made to work at 1 000 users, but it operates **below the recommended safety margin** for memory and is **CPU-constrained** for data analysis workloads. Any usage spike, misbehaving script, or future user growth will immediately surface as user-facing errors or degraded performance across the entire platform — not just for terminal users.

This document provides the numbers and proposes a targeted upgrade.

---

## Current Setup

| | Value |
|---|---|
| Nodes | 4 (behind a load balancer) |
| RAM per node | 15 GB total / **9.6 GB available** for Open Terminal |
| vCPU per node | 4 cores |
| Current user count | ~600 |
| Target user count | 1 000 |
| New feature | Open Terminal (AI-driven Python / shell execution) |

Each node runs three services: **OpenWebUI** (the chat interface), **LiteLLM** (the model proxy), and **Open Terminal** (the code execution sidecar).

The existing stack (OS + LiteLLM + OpenWebUI) consumes **5.4 GB observed** on each node, leaving **9.6 GB** available for Open Terminal.

---

## Memory Analysis at 1 000 Users

### Cost of a data analysis session

Open Terminal executes Python on behalf of users. A typical session — importing pandas, numpy, and matplotlib, then loading a dataset — consumes:

| Session type | Memory |
|---|---|
| Light (shell navigation, small scripts) | ~100–200 MB |
| Standard (pandas / numpy on a few MB of data) | ~300–500 MB |
| Heavy (scikit-learn training, large datasets) | ~500 MB – 1 GB |

**Conservative average used in calculations: ~400 MB per active session.**

### The math at 1 000 users on 4 nodes

Assuming **5% peak concurrent terminal usage** (a standard enterprise estimate):

```
1 000 users × 5% peak  = 50 concurrent sessions total
50 sessions / 4 nodes  = 12.5 concurrent sessions per node

Memory needed per node:
  Open Terminal sessions (12.5 × 400 MB): 5.0 GB
  Available:                              9.6 GB
  ─────────────────────────────────────────────
  Headroom:                               1.9×
```

**1.9× is below the recommended 2× safety margin for production systems.**

In practice this means: a single heavy user running a large scikit-learn training job or a user who forgot to close a terminal can absorb the entire buffer. During a company-wide onboarding session or any event that pushes usage above 5%, the platform will start rejecting terminal connections.

### Session cap enforces the limit visibly

We have configured `OPEN_TERMINAL_MAX_SESSIONS=25` per node. When this is hit, users receive a hard error: *"Maximum number of terminal sessions reached."* At 1 000 users on 4 nodes, this ceiling will be hit during any significant peak — and those users will open support tickets.

---

## CPU Analysis

This is the tighter constraint. Each node has **4 cores** shared across all services:

| Allocation | Cores |
|---|---|
| OS + LiteLLM + OpenWebUI | 2 |
| Open Terminal | 2 |

Data analysis operations (groupby on large DataFrames, matrix operations in numpy, model fitting in scikit-learn) are CPU-intensive. With 12–13 concurrent terminal sessions competing for 2 cores, **users will experience slow computations**, and CPU contention will bleed into the chat interface response times for *all* users — even those not using the terminal.

Unlike memory (where Docker enforces a hard ceiling), CPU is throttled gradually. Users will notice degraded performance before any hard limit is reached.

---

## Recommended Upgrade

### Option A — CPU upgrade on existing nodes (minimum viable)

The memory situation is manageable. The immediate bottleneck is CPU.

| | Current | Recommended |
|---|---|---|
| Nodes | 4 | 4 |
| RAM per node | 15 GB | 15 GB *(unchanged)* |
| vCPU per node | 4 cores | **8 cores** |

With 8 cores per node:
- 3 cores for OS + LiteLLM + OpenWebUI (more comfortable than today)
- **5 cores for Open Terminal** — handles 12–13 concurrent data analysis sessions without saturation
- Chat response times remain stable during terminal-heavy peaks

**This is the smallest change that removes the immediate constraint at 1 000 users.**

---

### Option B — RAM and CPU upgrade, future-proofed (recommended)

If the 1 000-user target is a stepping stone rather than a ceiling, addressing both constraints now is more cost-effective than returning in 6–12 months.

| | Current | Recommended |
|---|---|---|
| Nodes | 4 | 4 |
| RAM per node | 15 GB | **32 GB** |
| vCPU per node | 4 cores | **16 cores** |

**Why 32 GB?**

```
Existing stack (observed):            5.4 GB
Peak sessions at 1 000 users:         5.0 GB
2× safety margin:                     × 2
─────────────────────────────────────────────
Recommended minimum:                 ~20 GB  →  32 GB covers growth to ~2 500 users
```

**Why 16 cores?**

Allocating 8 cores to Open Terminal at 1 000 users leaves 8 cores for the rest of the stack — comfortable even with 2 000+ users in the future.

**Headroom with this configuration:**

| Metric | Value |
|---|---|
| Memory available for Open Terminal | ~26.6 GB |
| Safe concurrent sessions per node | ~65 |
| Total safe concurrent sessions (4 nodes) | ~260 |
| Equivalent user base at 5% peak | ~5 200 users |

---

## Comparison

| | Current | Option A | Option B |
|---|---|---|---|
| Nodes | 4 | 4 | 4 |
| RAM per node | 15 GB | 15 GB | 32 GB |
| vCPU per node | 4 cores | 8 cores | 16 cores |
| Memory headroom at 1 000 users | 1.9× ⚠️ | 1.9× ⚠️ | 4.5× ✅ |
| CPU headroom at 1 000 users | Saturated ❌ | Comfortable ✅ | Very comfortable ✅ |
| Safe user ceiling | ~800 | ~800 | ~5 200 |
| Growth path | None | Revisit RAM at ~1 200 | Comfortable to ~5 000 |
| **Recommendation** | — | ✅ Minimum | ✅✅ **Preferred** |

---

## Risk of Not Upgrading

If we proceed to 1 000 users on current hardware with Open Terminal enabled:

| Risk | Likelihood | Impact |
|---|---|---|
| CPU saturation slows chat for all users during peak | High | Medium — degraded UX platform-wide |
| Session cap hit during onboarding events / peaks | High | Low-Medium — users see hard errors |
| Memory buffer exhausted by a single heavy job | Medium | Medium — Docker kills sessions mid-execution |
| No headroom for growth past ~800 users | Certain | High — hardware revisit required within months |

---

## Appendix — Sizing Methodology

- **Observed baseline:** The 5.4 GB existing stack figure is measured from `docker stats` on the current deployment, not estimated.
- **Peak concurrency assumption:** 5% of users active in the terminal simultaneously. Conservative for enterprise (Slack, Notion report 3–8% concurrent active users for feature-specific tools).
- **Session memory estimate:** 400 MB average across light/standard/heavy data analysis workloads (pandas + numpy + matplotlib, CSV files up to ~50 MB). Measured from the Open Terminal container.
- **Safety margin:** 2× is the minimum recommended for production user-facing systems. Below 1.5× is considered high-risk in most infrastructure guidelines.
- **CPU model:** 2 cores allocated to Open Terminal out of 4 total. Data analysis workloads in Python are predominantly single-threaded per session; concurrent sessions compete for the same cores.
