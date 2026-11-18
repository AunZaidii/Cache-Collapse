# My AI Agent Team

A team of 7 AI helpers that build software step by step, like a real team.
You stay in charge: the team stops after each step and waits for your "yes".

## The team

| Agent | Job | Writes to |
|---|---|---|
| **analyst** | Turns your idea into a clear plan. Asks questions if unsure. | docs/spec.md |
| **designer** | Plans the screens, data, folders and tools. | docs/design.md |
| **dev** | Writes the code. | src/ |
| **tester** | Tests the code and reports problems. Never changes code. | docs/test-report.md |
| **deployer** | Writes steps to put the app online. Never publishes by itself. | docs/deploy-plan.md |
| **maintainer** | Fixes bugs with small, safe changes. Records lessons. | src/, docs/lessons.md |
| **manager** | Runs the whole team in order, asking you after each step. | - |

## How to use it

Open this folder in Claude Code and type one of these:

**Run the whole process (easiest):**
```
Use the manager agent to run the full process for this idea: [my idea]
```

**Run just one agent:**
```
Use the analyst agent to turn my idea into a spec: [my idea]
Use the designer agent to write the design from the spec
Use the dev agent to build the app from the spec and design
Use the tester agent to test the app
Use the deployer agent to write a deploy plan
Use the maintainer agent to fix the bugs in docs/bug-reports.md
```

**To report a bug yourself:** write it in `docs/bug-reports.md` (what happened, what you expected),
then ask the maintainer agent to fix it.

## Safety
The rules in `CLAUDE.md` apply to every agent: ask before deleting, never touch real
payments or passwords, never publish without your approval, explain in simple words.

## Try it: a small test project

Copy and paste this to test the whole system:

```
Use the manager agent to run the full process for this idea:
A simple to-do list app that runs in the web browser. I can add a task,
mark it as done, and delete it. My tasks should still be there when I
close and reopen the page. Just for me, no login needed.
```

The manager will stop after each step and ask you to approve. Type "yes" to continue,
or tell it what to change.
