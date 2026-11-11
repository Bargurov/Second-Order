# Porting from v1

Source inspected: a36960107e02bc7144c733381fda706ae540a9e0.

No runtime source files have been copied in the first stage.

- stats/event_study.py has only standard-library/numpy dependencies, but its
  market-adjusted return is not the alpha/beta market model specified by v2.
  Keep it as a reference; the v2 measurement function is new code.
- Some other stats modules import db and v1 event-study orchestration. The whole
  directory is not a portable unit.
- price_cache.py imports db. Keep its separation of raw/adjusted prices and source
  provenance as lessons; implement a dedicated v2 data adapter in the next stage.
- news_clustering.py depends on v1 fetch, consensus and token normalization.
  Clustering and automated intake stay in milestone 2.

Port a function only when the MVP uses it and its dependencies and behavioral
tests can be carried over without bringing the v1 product along.
