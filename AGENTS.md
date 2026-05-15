# AGENTS.md

## Project goal

This project implements a learning-oriented QA system with three layers:

1. QAGraph QA subgraph:
   - Handles explanation, tutoring, notebook/course-based QA, evidence retrieval, answer generation, answer repair, and learning event emission.

2. Decision boundary router:
   - Decides whether a user request should be answered directly, routed to practice generation, handled as tool-trace/meta inquiry, require realtime web search, or enter the full QAGraph.

3. Mobile synchronous delivery layer:
   - Supports mini-program/mobile clients using a sync-first API.
   - Returns completed responses inline when possible.
   - Returns pending jobs when the request exceeds the inline budget.
   - Allows polling by job_id.

## Non-negotiable design rules

- Do not route simple facts such as "1+1等于几" through RAG.
- Do not perform web search unless the route or policy explicitly allows it.
- If notebook_only is true and internal evidence is insufficient, do not fabricate an answer.
- Web search results must pass an external evidence judge before being merged into answer evidence.
- answer_repair must have a maximum retry count.
- Tool traces must not be injected into normal QA context by default.
- Tool traces may only be read when the user intent is meta_tool_usage.
- Learning events must not block the final user response.
- Mobile job state must be durable, not only in process memory.
- Polling must have retry_after_ms and server-side job expiration.

## Implementation expectations

- Prefer small, reviewable PRs.
- Add or update tests for every behavioral change.
- Run lint/typecheck/test commands before reporting completion.
- Keep public interfaces typed.
- Do not introduce new production dependencies unless necessary.
- If the existing repo already has conventions, follow them.
- If architecture is ambiguous, implement the smallest compatible abstraction and document assumptions.

## Required test coverage

Add tests for:

- simple_fact direct answer
- practice_generation direct route
- meta_tool_usage route
- realtime_or_fresh with allow_web=true
- realtime_or_fresh with allow_web=false
- explanation/tutoring entering QAGraph
- internal evidence sufficient
- internal evidence insufficient + allow_web=true
- internal evidence insufficient + notebook_only=true
- web evidence insufficient
- answer_repair capped retries
- mobile sync completed response
- mobile sync pending response
- mobile job polling completed
- mobile job polling failed
- duplicate client_request_id idempotency
