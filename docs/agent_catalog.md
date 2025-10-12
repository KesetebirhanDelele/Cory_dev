# Cory Agent Capability Catalog — C0.1

**Goal:** Define the baseline set of agents and their inputs/outputs/tools so every skill in **F1** and **F2** is covered.

## Summary Matrix

| Agent | Purpose | Inputs | Outputs | Tools / Calls | Notes |
|---|---|---|---|---|---|
| **ContentGenerator** | Produce first-draft outreach content and subject lines | Brief, persona, campaign goals, history | Draft message (text/email/voice script), metadata (tone, length) | LLM (OpenAI), Templates, Telemetry | Deterministic templates when policy requires |
| **ReplyInterpreter** | Classify inbound replies/calls and extract intents/entities | Raw text/transcript, channel, message context | Intent label, entities, next-action suggestion | LLM (classification), Regex/patterns, Telemetry | Must set `correlate_id` for traceability |
| **PolicyAwarePlanner** | Decide next step per policy (quiet hours, consent, caps) | Intent, campaign state, org policy, time | Plan (channel, send_time, template_id) or “deny” | Policy Guard, Schedules, KPI signals | Only source allowed to say **policy_denied** |

## Skills Coverage

- **F1:** drafting outreach, choosing tone, personalizing snippets → **ContentGenerator**
- **F2:** interpreting replies, deciding next action with policy awareness → **ReplyInterpreter** + **PolicyAwarePlanner**

## I/O Contracts (high level)

- **ContentGenerator.in →** `{ brief, persona, goals, history }`  
  **out →** `{ draft_text, channel_hint?, tone, tokens_used }`
- **ReplyInterpreter.in →** `{ text, channel, context }`  
  **out →** `{ intent, entities, confidence, suggested_action }`
- **PolicyAwarePlanner.in →** `{ intent, state, policy, timing }`  
  **out →** `{ decision: send|wait|deny, channel?, when?, template_id? }`

> Operational: All agents emit telemetry (trace id, duration). Planner is the final arbiter for policy.
