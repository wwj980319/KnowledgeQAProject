# SDD Progress Ledger — KnowledgeQAProject MVP
Plan: docs/superpowers/plans/2026-07-16-knowledge-qa-mvp.md (no git in this project; "commits" columns omitted)

Task 0: complete (review clean)
Task 1: complete (review approved; user-approved deviation: get_db() now commit-on-success — plan version never committed, would lose writes in production; Redis 6379 conflict with tradingagents-redis resolved per user: stop that container)
  Minor findings deferred to final review: datetime.utcnow deprecated (models.py, plan-mandated, fine on py3.11)
Task 2: complete (review approved; requirements.txt += email-validator==2.* — plan omission, EmailStr needs it; schemas.py datetime import unused until Task 5 adds DocumentOut — intentional)
  Minor deferred: bcrypt==4.0.1 exact pin style inconsistency (plan-mandated)
Task 3: complete (review approved; controller added missing ValueError-branch test per reviewer Important finding — 5/5 pass)
  Note: passlib 'crypt' DeprecationWarning appears in test output (third-party, py3.13-forward; harmless on 3.11) — deferred
Task 4: complete (review clean; bge model downloaded to HF cache, 3/3 + full suite 10/10)
Task 5: complete (review approved after fix loop: tasks.py error path restored to brief canonical — implementer had added swallowing except guards; test harness _bind_session now no-ops rollback, reviewer judged sound)
  Known design residue for final review: route enqueues BEFORE get_db commits → tiny race where worker sees no doc and returns silently (brief-mandated flush-then-enqueue; good interview talking point)
  Minor deferred: whole file read into memory before 413 check (plan-mandated); suffix logic duplicated between router and extraction; dead original_rollback var + superfluous embed_texts patch in test_tasks.py
FINAL REVIEW (opus, whole project): READY. No Critical. One non-gating Important: enqueue-before-commit race (documents.py flush→enqueue→get_db commit; worker may see no doc and strand status=processing; suggested one-line fix: raise in process_document when doc is None so RQ retries). All deferred minors triaged acceptable-for-MVP. Suite 29/29, health ok. — ALL 11 TASKS COMPLETE.
Task 10: complete (review approved; README + docs/面试问答准备.md accurate vs code; DoD 8/8; output_config.effort doubt resolved — real API accepted it in smoke)
Task 9: complete (review approved; 4 containers up, health ok; Step 5 real-Claude smoke PASSED: register→upload→query with [1] citation 4.3s→cached repeat 0.01s; claude-sonnet-5 real-API validated)
  USER-APPROVED FIX during smoke: per-user isolation — retrieve_chunks joins Document filtering user_id; cache key now qa:cache:{user_id}:<hash> (smoke had proven cross-user chunk leak: doc 1 test data in demo user's sources; post-fix smoke shows only own doc 56). Suite 29/29.
Task 8: complete (review approved after fix loop: /health no longer uses Depends(get_db) — DI raise on hard PG outage would 500, contradicting plan's own interface spec "degraded 仍 200"; now direct engine.connect() inside guard; suite 27/27)
  Minor deferred: middleware logs skip on unhandled handler exceptions (FastAPI limitation); get_redis broken-singleton retry; method concatenated into path log key (brief-ambiguous)
Task 7: complete (review approved; ⚠️ resolved by controller: QueryLog persistence relies on get_db commit-on-success ✓; claude-sonnet-5 validity confirmed last session from official docs, real-API check due at Task 9 smoke)
  Minor deferred: SourceOut.snippet no schema-level max_length; dead answer_question patch on test_history_empty
Task 6: complete (review clean after controller intervention: implementer hit stale redis container lacking host port mapping — created during Task 1's port conflict — and invented a docker-exec bridge hack; controller force-recreated container (root cause), deleted tests/redis_docker_bridge.py, reverted get_redis()/conftest.py to canonical; suite 20/20 on real Redis)
