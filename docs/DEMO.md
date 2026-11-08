# Five-minute demo

All examples describe fictional systems. Do not run proposed operations on real infrastructure.

1. Start Atlas and open the incident console. Choose `atlas-api`, version `2.4`.
2. Ask **How do I revert a bad deploy?** with recovery disabled. The initial lexical
   retrieval lacks enough query coverage, so Atlas abstains.
3. Enable recovery and repeat. Open the execution trail: the retry uses explicit runbook
   search aliases and wider retrieval. Open the source passage and verify the exact quote.
   This demonstrates retrieval repair, not automated deployment rollback.
4. Ask **How do I investigate conection pool exhuastion?**. Inspect the corrected query.
5. Select `ledger-worker` / `3.1` and ask **Why are events arriving twice?**. Inspect the
   at-least-once delivery and idempotency evidence. An excerpt is a diagnostic lead, not
   confirmation that this was the incident's root cause.
6. Ask **What is the Kubernetes cluster administrator password?** under `atlas-api` / `2.4`.
   No matching runbook evidence should be published.
7. Run the Evaluation lab comparison. Inspect both paths for individual cases and download
   the JSON. Explain that these are development fixtures, not real-company results.
8. Add a redacted `.md` runbook with your own service/version and aliases. Switch to its
   scope and ask a relevant question. Revisit it in Run history.

To demonstrate optional model outage handling, configure an Ollama model name but leave
Ollama stopped. Select Ollama, ask a known runbook question, and inspect the recorded
provider failure and local-evidence fallback. Do not configure or use billable providers
for a demo unless you intend to send the selected passages to that provider.

## Talking about this project in an interview

“I built a local incident-response evidence assistant with a bounded LangGraph recovery
workflow. It isolates services and versions before retrieval, detects weak lexical coverage,
retries with aliases and spelling correction, validates quote provenance, and abstains on
missing evidence. I built a FastAPI workbench and paired evaluation harness to inspect its
failures. Its current retrieval is lexical; I would evaluate semantic retrieval on independently
labeled incidents before claiming it improves real on-call outcomes.”
