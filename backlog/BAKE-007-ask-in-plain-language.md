# BAKE-007 Ask greenrun in plain language

**As** a household user
**I want** to ask in my own words when to run an appliance
**so that** I do not need to know the commands.

## Acceptance criteria

1. `python -m greenrun ask "When should I run my dishwasher tonight?"` answers with a start and end time in the
   zone's local time and the reason (average price and renewable share of the run window), in at most five sentences.
2. The agent gets its facts from tools: the recommendation from BAKE-006 and the completeness report from BAKE-004.
   Every number in the answer appears in a tool result.
3. If data for the run window is missing or incomplete, the answer says so and does not guess.
4. Questions outside running appliances and electricity get a short, polite refusal.
5. The LLM provider and model are set by environment variables. No key or secret is committed.
6. `evals/agent_cases.jsonl` holds at least 10 cases (question, expected tool calls, expected outcome), and
   `python -m greenrun eval` runs them and prints a pass rate. At least 9 of 10 pass.
7. Unit tests do not call an LLM: tools are tested directly, and the agent loop with a scripted fake model.

## Out of scope

A web or chat UI, memory between questions, voice.
