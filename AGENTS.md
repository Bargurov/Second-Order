# Second Order v2
1. Measure whether market observations are consistent with a frozen hypothesis. Do not claim causality or recommend trades.
2. Keep prospective and replay results separate. Showcase cases never enter research scores.
3. Freeze inputs, engine metadata and data/rule provenance. New versions append; existing hypotheses and evaluations stay.
4. Scores, clocks, anchors, benchmarks and observables belong to deterministic code. Model output must pass the schema.
5. Reads never fetch from providers. Any billed request must be an explicit action with a visible cost decision.
6. Build one complete slice at a time. Keep scheduling and ingestion outside milestone 1. Crack spreads may appear only as explicitly refreshed, computed reference figures on the fuels page; as research observables they wait for milestone 2.
7. Verify changed behavior with unittest; run the full suite and offline demo before claiming completion.
8. Review scope when a source file approaches 800 lines. Add a rule only for a recurring, broadly relevant problem.
