# Rules for All Agents

## Safety rules
1. Ask the user before deleting anything.
2. Never touch real payments, live databases, or real passwords.
3. Never publish anything live without the user's clear approval.
4. Always explain things in short, simple words. The user is not technical.
5. Read docs/lessons.md before starting work. Add a new lesson after any mistake.

## Where things go
- `.claude/agents/` - the agent files
- `docs/` - shared notes (spec, design, test report, deploy plan, bugs, lessons)
- `src/` - the app's code
- `tests/` - test files (made by the tester)

## How to run the manager
When the user asks to "use the manager agent", do NOT launch it as a background subagent
(a subagent cannot stop and wait for the user). Instead, read `.claude/agents/manager.md`
and follow its steps yourself in this chat. Launch the other agents one at a time,
and wait for the user's approval after each phase.

## If an agent has questions
Agents cannot talk to the user directly. If an agent returns questions,
show them to the user, wait for answers, then run the agent again with the answers.
