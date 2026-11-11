"""SYNTHETIC publishers, feeds and newsrooms for the stories tests, the stories browser check and the demo launcher.

Not a test module. Every publisher here is invented (``synthetic=True``, status ``fixture_only``) and its feed answers
only through a simulated network (an httpx MockTransport): nothing can reach a real publisher. Their invented terms
allow their invented reports to be used as brief material, so a shared brief, coverage and Go deeper can be exercised;
every title says "Synthetic". The real registry's publishers are unchanged; tests that use them (TechCrunch, PR
Newswire) answer their registered feed addresses with SYNTHETIC feeds.
"""
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import httpx

from second_order import event_inbox, news_feeds, news_registry, news_views, newsroom_store
from second_order.news_registry import Publisher

START = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)


def _synthetic(key: str, name: str, role: str, interest: str, host: str, kind: str) -> Publisher:
    feed = event_inbox.Source(key, f"{name} (SYNTHETIC)", name, interest.title(), f"https://{host}/feed.xml",
                              f"https://{host}/feeds", f"https://{host}/terms", host, False, kind=kind,
                              attribution=name, keep_raw=False)
    return Publisher(key, name, role, interest, "public_feed", "not_in_feed", "headline_excerpt", "permitted",
                     "fixture_only", f"https://{host}/terms", "SYNTHETIC test publisher; nothing was read.",
                     attribution=name, feed=feed, note="SYNTHETIC: invented reports for tests and the demo.",
                     synthetic=True, material_basis="SYNTHETIC: its invented reports may be used.")


SYNTHETIC = {publisher.key: publisher for publisher in (
    _synthetic("synthetic-ledger", "Synthetic Ledger", "news", "trade", "ledger.example.org", "News report"),
    _synthetic("synthetic-courier", "Synthetic Courier", "news", "markets", "courier.example.org", "News report"),
    _synthetic("synthetic-gazette", "Synthetic Gazette", "news", "trade", "gazette.example.org", "News report"),
    _synthetic("synthetic-maker", "Synthetic Maker Corp. via Synthetic Release Wire", "company", "companies",
               "releases.example.org", "Company statement"),
)}


def publishers(extra: dict | None = None) -> dict[str, Publisher]:
    """The real registry plus the SYNTHETIC publishers (or ``extra``)."""
    return {**news_registry.PUBLISHERS, **(SYNTHETIC if extra is None else extra)}


def rfc822(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def item(host: str, slug: str, title: str, at: datetime | None, excerpt: str | None = None) -> str:
    link = f"https://{host}/news/{slug}"
    parts = [f"<title>{escape(title)}</title>", f"<link>{link}</link>", f"<guid>{link}</guid>"]
    if excerpt is not None:
        parts.append(f"<description>{escape(excerpt)}</description>")
    if at is not None:
        parts.append(f"<pubDate>{rfc822(at)}</pubDate>")
    return "<item>" + "".join(parts) + "</item>"


def rss(items: list[str], title: str = "Synthetic feed") -> bytes:
    return ('<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
            f"<title>{escape(title)}</title>" + "".join(items) + "</channel></rss>").encode("utf-8")


class Feeds:
    """A simulated network answering feed addresses (status, body); every request it received is kept."""

    def __init__(self, answers: dict[str, tuple[int, bytes]]):
        self.answers = dict(answers)
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        answer = self.answers.get(str(request.url))
        if answer is None:
            raise httpx.ConnectError("no SYNTHETIC answer for this address", request=request)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer[0], content=answer[1], headers={"content-type": "application/rss+xml"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def desk_in(root: Path, chosen: dict[str, Publisher] | None = None, network: Feeds | None = None,
            drafting=None) -> news_views.Desk:
    """A desk over folders inside ``root``; its fetcher may request only the chosen publishers' feeds."""
    chosen = chosen if chosen is not None else publishers()
    refreshable = [publisher for publisher in chosen.values() if publisher.feed
                   and (publisher.status == "connected" or publisher.synthetic)]
    fetcher = news_feeds.fetcher_for(refreshable, network.transport()) if network else \
        news_feeds.fetcher_for(refreshable, httpx.MockTransport(_refuse))
    return news_views.Desk(newsroom_store.open_at(root / "newsroom"), root / "event-inbox", root / "news-feeds",
                           root / "story-deeper", chosen, fetcher, drafting, texts=root / "news-texts",
                           index=root / "news-index")


def _refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("this test makes no feed request", request=request)


def clock(start: datetime = START):
    moments = iter(start + timedelta(seconds=n) for n in range(1_000_000))
    return lambda: next(moments)


# ---------------------------------------------------------------- a SYNTHETIC trade-policy topic

LEDGER, COURIER, GAZETTE, MAKER = (SYNTHETIC[key].feed for key in ("synthetic-ledger", "synthetic-courier",
                                                                    "synthetic-gazette", "synthetic-maker"))
TARIFF = "Synthetic Republic announces 15% tariff on imported steel"
RESPONSE = "Synthetic Federation responds with duties on farm goods"
RESPONSE_OWN = "Synthetic Federation hits back at steel tariff with farm duties"  # Its own words: independent.
REVISION = "Synthetic Republic narrows steel tariff after talks"
UNRELATED = "Synthetic Republic steel museum opens new wing"


MOBILE = "Synthetic Republic raises mobile internet tariffs by 40%"
SALES = "Synthetic retail sales reach 745.0 billion in September"
GROWTH = "Synthetic economy grows 2.5% after 2.0%"


def economics_items(now: datetime = START) -> list[str]:
    """Three SYNTHETIC economic reports for the explanation tests: a domestic service's price (a "tariff" that is not
    a duty on imports), a nominal level with its previous month and the year's price change, and two growth rates."""
    hours = lambda value: now - timedelta(hours=value)  # noqa: E731
    return [
        item(COURIER.link_host, "mobile", MOBILE, hours(6), "SYNTHETIC: Mobile internet tariffs charged by the "
             "Synthetic Republic's operators rose 40% this month, the telecoms regulator said."),
        item(COURIER.link_host, "sales", SALES, hours(7), "SYNTHETIC: Retail sales were $745.0 billion in September, "
             "up 0.8 percent from August's $739.1 billion. Consumer prices were 3.1% higher than a year earlier."),
        item(COURIER.link_host, "growth", GROWTH, hours(8), "SYNTHETIC: Real GDP grew at a seasonally adjusted "
             "annual rate of 2.5% in the third quarter, after 2.0% in the second quarter."),
    ]


def trade_feeds(now: datetime = START, courier_extra: list[str] | None = None, ledger_extra: list[str] | None = None,
                gazette_extra: list[str] | None = None, museum: str = "A SYNTHETIC museum about steel opened a wing."
                ) -> dict[str, tuple[int, bytes]]:
    """Three developments of one SYNTHETIC trade dispute, a syndicated copy, a same-keyword unrelated report and a
    company statement (and ``*_extra`` items on the Courier, the Ledger and the Gazette; ``museum`` is the unrelated
    report's excerpt). Times are relative to ``now``."""
    hours = lambda value: now - timedelta(hours=value)  # noqa: E731
    wire = ("SYNTHETIC CAPITAL (Reuters) - The Synthetic Republic said on Monday it would impose a 15% tariff on "
            "imported steel from next month, citing a review of its steel industry.")
    return {
        LEDGER.feed_url: (200, rss([
            item(LEDGER.link_host, "tariff", TARIFF, hours(50), wire),
            item(LEDGER.link_host, "revision", REVISION, hours(2),
                 "The Synthetic Republic said it would exempt three grades of steel from the tariff after talks."),
            item(LEDGER.link_host, "museum", UNRELATED, hours(5), museum),
        ] + list(ledger_extra or []), "Synthetic Ledger")),
        COURIER.feed_url: (200, rss([
            item(COURIER.link_host, "tariff-copy", TARIFF, hours(49), wire),
            item(COURIER.link_host, "response", RESPONSE, hours(26),
                 "The Synthetic Federation said it would impose duties on farm goods in response to the steel "
                 "tariff."),
        ] + list(courier_extra or []), "Synthetic Courier")),
        GAZETTE.feed_url: (200, rss([
            item(GAZETTE.link_host, "response", RESPONSE_OWN, hours(25),
                 "Officials of the Synthetic Federation announced duties on farm goods, their spokesperson said."),
            item(GAZETTE.link_host, "no-time", "Synthetic port reports record container volumes", None,
                 "The SYNTHETIC port said container volumes reached a record."),
        ] + list(gazette_extra or []), "Synthetic Gazette")),
        MAKER.feed_url: (200, rss([
            item(MAKER.link_host, "statement", "Synthetic Maker Corp. comments on steel tariff", hours(48),
                 "Synthetic Maker Corp. said the tariff would raise its input costs."),
        ], "Synthetic Release Wire")),
    }


EXTENSION = "Synthetic Republic extends steel tariff to aluminium imports"
RATES = "Synthetic central bank holds its policy rate at 4.25%"
SHIPYARD = "Synthetic shipyard orders fell 12% in September"
MINE = "Synthetic mine reports higher copper output"


def later_items(at) -> dict:
    """SYNTHETIC entries an update finds later (``at(hours)``: a time relative to the original feeds): a copy of the
    tariff report on another feed, a central bank decision and a new development of the tariff topic, an older
    shipyard report not listed before and an entry with no publication time. Keyword arguments for trade_feeds."""
    return {
        "courier_extra": [
            item(COURIER.link_host, "tariff-again", TARIFF, at(2),
                 "SYNTHETIC: the Synthetic Republic confirmed that its 15% steel tariff takes effect next month."),
            item(COURIER.link_host, "rates", RATES, at(2.5),
                 "SYNTHETIC: The Synthetic central bank held its policy rate at 4.25%, its board said.")],
        "ledger_extra": [item(LEDGER.link_host, "extension", EXTENSION, at(2),
                              "SYNTHETIC CAPITAL - The Synthetic Republic said on Monday that its 15% tariff on steel "
                              "would extend to aluminium imports.")],
        "gazette_extra": [item(GAZETTE.link_host, "shipyard", SHIPYARD, at(-30),
                               "SYNTHETIC: Orders at the Synthetic shipyard fell 12% in September, its owner said."),
                          item(GAZETTE.link_host, "mine", MINE, None,
                               "SYNTHETIC: The Synthetic mine said copper output rose.")],
        "museum": "A SYNTHETIC museum about steel opened a new wing on Tuesday."}


def insufficient_economics(ids=None) -> dict:
    """A SYNTHETIC explanation saying the evidence is insufficient (valid for any story)."""
    from second_order import story_economics
    return {**{key: [] for key in story_economics.FIELDS[5:]}, "status": "insufficient_evidence",
            "insufficient_reason": "SYNTHETIC: the reports give no figures to explain.", "change": None,
            "significance": None, "main_uncertainty": None}


# ---------------------------------------------------------------- a SYNTHETIC model for brief drafting

RELEVANCE_SYSTEM = "You assess whether a news story"
JSON_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def misfits(value: object, schema: dict, path: str = "$") -> list[str]:
    """Where ``value`` does not fit an output format (the keywords output_schema allows): what a provider's
    constrained output would never return. A simulated reply that does not fit was not one the provider could give."""
    if "anyOf" in schema:
        return [] if any(not misfits(value, branch, path) for branch in schema["anyOf"]) else [f"{path}: no branch fits"]
    kind = schema.get("type")
    if kind in ("number", "integer"):
        fits = isinstance(value, (int, float) if kind == "number" else int) and not isinstance(value, bool)
    else:
        fits = kind is None or isinstance(value, JSON_TYPES[kind])
    if not fits:
        return [f"{path}: not {kind}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: {value!r} is not one of the enum"]
    found = []
    if kind == "object":
        if set(value) != set(schema["properties"]) or set(schema["required"]) != set(schema["properties"]):
            return [f"{path}: properties {sorted(value)} are not exactly {sorted(schema['properties'])}"]
        for name, child in schema["properties"].items():
            found += misfits(value[name], child, f"{path}.{name}")
    if kind == "array":
        for index, row in enumerate(value):
            found += misfits(row, schema["items"], f"{path}[{index}]")
    return found


def synthetic_annotation(report: str, quote: str, verdict: str = "relevant") -> dict:
    """A SYNTHETIC relevance annotation quoting ``quote`` from ``report``: a relevant trade development, an item
    outside the scope (a ceremonial message), or one whose sources say too little."""
    evidence = [{"report": report, "quote": quote}]
    if verdict == "relevant":
        return {"report_kind": "development", "event_type": "policy_decision",
                "change": "SYNTHETIC: the sources report a change.", "change_evidence": evidence,
                "affected": [{"name": "SYNTHETIC importers", "kind": "industry", "evidence": evidence}],
                "dimensions": [{"dimension": "trade", "how": "SYNTHETIC: it may change what importers pay.",
                                "evidence": evidence}],
                "scope": {"reach": "national", "magnitudes": []}, "ambiguities": [],
                "missing": ["SYNTHETIC: how long it lasts is not stated."], "verdict": "relevant",
                "explanation": "SYNTHETIC: a reported policy change affecting trade."}
    return {"report_kind": "ceremonial" if verdict == "outside_scope" else "other", "event_type": None,
            "change": "SYNTHETIC: no economic development is reported.", "change_evidence": evidence, "affected": [],
            "dimensions": [], "scope": {"reach": "unclear", "magnitudes": []}, "ambiguities": [], "missing": [],
            "verdict": verdict, "explanation": "SYNTHETIC: the item reports no economic development."}


def wire_facts(answer: dict, contract: str | None = None) -> list:
    """An answer's facts as a first stage under ``contract`` writes them: from brief-evidence-5 each with the claim it
    records (brief_claims), every claim field "" for a fact that records none; earlier contracts as they were."""
    from second_order import brief_stages
    if (contract or brief_stages.STAGE_VERSIONS[1]) not in brief_stages.CLAIMED:
        return answer["facts"]
    claims = {row["id"]: row for row in answer.get("claims") or [] if isinstance(row, dict)}
    rows = []
    for fact in answer["facts"]:
        if not isinstance(fact, dict):
            rows.append(fact)
            continue
        claim = next((claims[name] for name in fact.get("claims") or [] if name in claims), None)
        rows.append({"text": fact.get("text"), "reports": fact.get("reports"),
                     **{f"claim_{name}": "" if claim is None or claim[name] is None else claim[name]
                        for name in ("holder", "holder_name", "modality", "quote", "condition")}})
    return rows


def stage_replies(answer: dict, contract: str | None = None) -> tuple[dict, dict]:
    """The two stages' replies (brief_stages) for one complete application-shaped SYNTHETIC answer: a brief with its
    economics and an ``insufficient_material`` text, under the current first-stage contract unless ``contract`` names
    an earlier one. An inverse projection for fixtures only, not validation: nothing is filled in, and a malformed
    value stays malformed so that negative tests reach the application's checks."""
    blank = lambda value: "" if value is None else value  # noqa: E731
    if answer.get("insufficient_material"):
        first = {"insufficient_material": answer["insufficient_material"], "facts": [], "themes": [], "missing": [],
                 "insufficient_evidence": "", "change_stage": "", "change_instrument": "", "change_form": "",
                 "change_respondents": "", "change_text": "", "change_basis": [], "figures": [], "calculations": []}
        return first, {}
    economics = answer["economics"]
    explained = economics["status"] == "explained"
    change = economics["change"] or {"stage": "", "instrument": "", "form": "", "respondents": None, "text": "",
                                     "basis": []}
    first = {"insufficient_material": "", "facts": wire_facts(answer, contract), "themes": answer["themes"],
             "missing": answer["missing"],
             "insufficient_evidence": "" if explained else economics["insufficient_reason"],
             "change_stage": change["stage"], "change_instrument": change["instrument"],
             "change_form": change.get("form", ""), "change_respondents": blank(change.get("respondents")),
             "change_text": change["text"], "change_basis": change["basis"],
             "figures": [{name: blank(value) if name in ("vintage_label", "sign_words") else value
                          for name, value in row.items() if name not in ("id", "sign")}
                         for row in economics["figures"]],
             "calculations": [{name: row[name] for name in ("op", "inputs", "label")}
                              for row in economics["calculations"]]}
    assumed = lambda row: row["basis"] + [f"assumption:{name}" for name in row["assumptions"]]  # noqa: E731
    second = {"headline": answer["headline"], "summary": answer["summary"],
              "implications": [row["text"] for row in answer["implications"]],
              "uncertainties": answer["uncertainties"], "insufficient_explanation": "",
              "significance": economics["significance"]["text"] if explained else "",
              "significance_basis": economics["significance"]["basis"] if explained else [],
              "main_uncertainty": blank(economics["main_uncertainty"]),
              "assumptions": [row["text"] for row in economics["assumptions"]],
              "channels": [{"scope": row["scope"], "support": row["support"], "note": blank(row["note"]),
                            "text": row["text"], "steps": row["steps"], "affected": row["affected"],
                            "conditions": blank(row["conditions"]), "horizon": row["horizon"], "basis": assumed(row)}
                           for row in economics["channels"]],
              "second_order": [{"from": row["from"], "text": row["text"], "conditions": row["conditions"],
                                "horizon": row["horizon"], "basis": assumed(row)} for row in economics["second_order"]],
              # brief-explanation-6: an alternative says what supports it, its assumptions named in its basis.
              "alternatives": [{"kind": row["kind"], "support": row["support"], "text": row["text"],
                                "basis": assumed(row)} if isinstance(row, dict) and "support" in row else row
                               for row in economics["alternatives"]],
              "watch": economics["watch"]}
    return first, second


class BriefModel:
    """A fake of the Messages API for news preparation (both stages of a brief draft, and relevance annotations),
    answering with one structured reply: a SYNTHETIC brief citing the request's own report IDs, split into the stage
    the request asks for (stage_replies), or a SYNTHETIC annotation quoting the story's first headline. Every request
    body is kept; it can answer with an error (for every request, or for one stage), and ``verdicts`` maps a headline
    to another answer for its annotation (outside_scope, insufficient_information, refuse, invalid)."""

    def __init__(self, key: str):
        self.key, self.requests, self.status, self.echo = key, [], 200, False
        self.error_body: bytes | None = None  # What a non-200 answer carries (default: an overloaded error).
        self.headers: dict[str, str] = {}  # Extra response headers (a SYNTHETIC request-id, for example).
        self.verdicts: dict[str, str] = {}
        self.economics = insufficient_economics  # A callable of the request's report IDs, giving the brief's economics.
        self.fit_format = True  # A brief reply must fit the request's format, as the provider's constrained output does.
        self.brief_reply = None  # A callable turning the default brief (application-shaped) into the one given.
        self.stage_status: dict[int, int] = {}  # A stage answered with this HTTP status instead.
        self.stage_reply: dict[int, object] = {}  # A stage's reply turned by a callable into the one given.
        self.stop: dict[int, str] = {}  # A stage's stop reason, when not end_turn.

    def stages(self) -> list[int]:
        """The stage of each brief request received, in order (relevance requests left out)."""
        import json
        from second_order import brief_stages
        found = []
        for body in self.requests:
            system = json.loads(body)["system"]
            found += [stage for stage, rules in ((1, brief_stages.STAGE_1_RULES), (2, brief_stages.STAGE_2_RULES),
                                                (2, brief_stages.BRIEF_ONLY_RULES))
                      if system.startswith(rules[:60])]
        return found

    def _annotation(self, body: dict) -> tuple[object, str]:
        import json
        material = json.loads(body["messages"][0]["content"].split("\n\n", 1)[1])
        first = material["reports"][0]
        verdict = self.verdicts.get(first["headline"], "relevant")
        if verdict == "refuse":
            return None, "refusal"
        if verdict == "invalid":
            return "not the format", "end_turn"
        quote = " ".join(first["headline"].split()[:5])
        return synthetic_annotation(first["id"], quote, verdict), "end_turn"

    def handler(self, request: httpx.Request) -> httpx.Response:
        import json
        self.requests.append(request.content)
        body = json.loads(request.content)
        from second_order import brief_stages
        stage = next((number for number, rules in ((1, brief_stages.STAGE_1_RULES), (2, brief_stages.STAGE_2_RULES),
                                                   (2, brief_stages.BRIEF_ONLY_RULES))
                      if body["system"].startswith(rules[:60])), None)
        status = self.stage_status.get(stage, self.status)
        if status != 200:
            return httpx.Response(status, content=self.error_body or
                                  b'{"type":"error","error":{"type":"overloaded_error"}}',
                                  headers={"content-type": "application/json", **self.headers})
        stop = self.stop.get(stage, "end_turn")
        if body["system"].startswith(RELEVANCE_SYSTEM):
            answer, stop = self._annotation(body)
        else:
            ids = [line.split(": ", 1)[1] for line in body["messages"][0]["content"].splitlines()
                   if line.startswith("Report ID: ")]
            answer = {"headline": "SYNTHETIC drafted brief", "summary": "SYNTHETIC: the reports state a development.",
                      "facts": [{"text": "SYNTHETIC fact as reported.", "reports": ids[:1]}],
                      "implications": [{"text": "SYNTHETIC: it could matter to the sector if it lasts."}],
                      "themes": [], "uncertainties": ["SYNTHETIC: the duration is not stated."], "missing": [],
                      "insufficient_material": "", "economics": self.economics(ids)}
            if self.brief_reply is not None:
                answer = self.brief_reply(answer)
            answer = stage_replies(answer)[stage - 1]
            if stage == 2 and body["system"].startswith(brief_stages.BRIEF_ONLY_RULES):
                answer = {key: answer[key] for key in brief_stages.BRIEF_ONLY_SCHEMA["properties"]}
            if stage in self.stage_reply:
                answer = self.stage_reply[stage](answer)
            if self.fit_format:
                problems = misfits(answer, body["output_config"]["format"]["schema"])
                assert not problems, f"The SYNTHETIC stage {stage} reply does not fit the request's format: {problems}"
        content = [{"type": "thinking", "thinking": "", "signature": "sig-synthetic"}]
        if answer is not None:
            content.append({"type": "text", "text": answer if isinstance(answer, str) else json.dumps(answer)})
        reply = {"id": "msg_synthetic_news", "type": "message", "role": "assistant", "model": body["model"],
                 "content": content, "stop_reason": stop, "stop_sequence": None,
                 "usage": {"input_tokens": 900, "output_tokens": 300}}
        text = json.dumps(reply)
        if self.echo:  # A reply that carries the key, in either stage.
            text = text.replace("SYNTHETIC drafted brief", self.key).replace("SYNTHETIC fact as reported", self.key)
        return httpx.Response(200, content=text.encode("utf-8"), headers={"content-type": "application/json",
                                                                          **self.headers})

    def sender(self):
        from second_order.paid_drafts import PaidSender

        def factory(observe):
            return httpx.Client(transport=httpx.MockTransport(self.handler), follow_redirects=False, trust_env=False,
                                event_hooks={"response": [observe]})
        return PaidSender(api_key=lambda: self.key, client_factory=factory)


def approve_batch(desk, batch: dict, story_now, actor: str, clock) -> dict:
    """Approve a model batch at the total its preview showed: each saved request is sent once."""
    from second_order import news_batches
    return news_batches.approve(desk, batch["batch_id"], {
        "batch_id": batch["batch_id"], "approve_paid_requests": True,
        "estimated_max_usd_total": batch["estimated_max_usd_total"]}, story_now, actor, clock)


def both_stages(desk, batch: dict, now: datetime, story_now, actor: str, clock) -> dict:
    """As an operator does: approve a model batch of stage-1 requests, then preview the same stories again (their
    stage-2 requests, prepared from the validated stage 1) and approve that batch at its own total. Returns the
    stage-2 batch."""
    from second_order import news_batches
    approve_batch(desk, batch, story_now, actor, clock)
    stories = [item["story_id"] for item in batch["items"]]
    second, _ = news_batches.preview(desk, now, "model", limit=len(stories), story_ids=stories, actor=actor)
    assert {item["draft"]["stage"] for item in second["items"]} == {2}, second["items"]
    approve_batch(desk, second, story_now, actor, clock)
    return second


def assess(desk, now: datetime, verdicts: dict[str, str] | None = None, actor: str = "synthetic-editor",
           synthetic_only: bool = False) -> dict:
    """Record a SYNTHETIC relevance annotation of every story whose material may be sent to a model (each relevant,
    unless ``verdicts`` maps its title to another verdict), as the batch would after a model's reply; with
    ``synthetic_only``, only of SYNTHETIC publishers' stories, so a copy of real records keeps its own assessments.
    Returns {story_id: state}."""
    verdicts = verdicts or {}
    states = {}
    for story_id, story in news_views.world(desk, now)["stories"].items():
        if not story["material"]["reports"] or (synthetic_only and not story["synthetic"]):
            continue
        states[story_id] = annotate(desk, story, now, verdicts.get(story["title"], "relevant"), actor)
    return states


def annotate(desk, story: dict, now: datetime, verdict: str = "relevant", actor: str = "synthetic-editor") -> str:
    """Record one SYNTHETIC annotation of a story's material (as ``assess`` does for every story); its state."""
    from second_order import news_relevance, relevance_requests
    reports = story["material"]["reports"]
    first = reports[0]
    annotation = synthetic_annotation(first["entry_id"], " ".join(first["title"].split()[:5]), verdict)
    checked = news_relevance.check_evidence(annotation, relevance_requests.sources(reports, {}))
    done, _ = news_relevance.record(desk.newsroom, story["story_id"], story["material"]["material_sha256"], {
        "method": "synthetic", "outcome": "annotated", "annotation": annotation, "evidence": checked,
        "versions": relevance_requests.versions(), "preparation": {"synthetic": True}}, actor, now,
        f"syn-{story['story_id'][6:]}-{story['material']['material_sha256'][:12]}")
    return done["state"]


# ---------------------------------------------------------------- a curated SYNTHETIC newsroom

TARIFF_BRIEF = {"headline": "Synthetic Republic announces a 15% steel tariff",
                "summary": "The Synthetic Republic said it would impose a 15% tariff on imported steel from next month.",
                "implications": [{"text": "Steel buyers in the Synthetic Federation could face higher costs if the "
                                          "tariff applies as announced."}],
                "themes": [{"kind": "sector", "name": "Steel", "basis": "The reports concern a tariff on steel."}],
                "uncertainties": ["How long the tariff applies is not stated."],
                "missing": ["Which steel products it covers."]}
TOPIC = "Synthetic steel dispute"


def tariff_economics(fact: str = "fact:1") -> dict:
    """A SYNTHETIC economic explanation of the tariff story (econ-explanation-0.1): a decided import tariff, its
    quoted rate, one micro channel through the tariff mechanism, one conditional second-order effect, an offsetting
    force and what to watch. Every claim rests on the story's first fact or the quoted figure."""
    return {
        "status": "explained", "insufficient_reason": None,
        "change": {"stage": "decision", "instrument": "import_tariff", "form": "announcement_or_decision",
                   "respondents": None, "basis": [fact],
                   "text": "SYNTHETIC: the Synthetic Republic said it would impose a tariff of {f1} on imported "
                           "steel from next month."},
        "significance": {"basis": [fact, "figure:f1"],
                         "text": "SYNTHETIC: steel is an input for many manufacturers, so a duty of {f1} on imported "
                                 "steel may raise costs beyond the steel industry if it is applied broadly."},
        "main_uncertainty": "SYNTHETIC: which steel products the tariff covers.",
        "figures": [{"id": "f1", "label": "SYNTHETIC tariff rate on imported steel", "value": 15, "unit": "percent",
                     "measure": "rate", "period": "from next month", "basis": "not_applicable",
                     "seasonal": "not_applicable", "price": False, "source": "report:" + "{report}",
                     "quote": "a 15% tariff on imported steel", "vintage_label": None, "sign": "as_quoted",
                     "sign_words": None, "bound": "exact", "statistic": "observed",
                     "stock_flow": "not_applicable"}],
        "calculations": [],
        "assumptions": [{"id": "a1", "text": "SYNTHETIC: the tariff covers most imported steel; the reports do not "
                                             "list products."},
                        {"id": "a2", "text": "SYNTHETIC: foreign exporters have margins they could cut."}],
        "channels": [{"id": "m1", "scope": "micro", "support": "framework", "note": "tariff-pass-through",
                      "text": "SYNTHETIC: if the duty is passed into the prices importers pay, firms that use "
                              "imported steel could face higher input costs.",
                      "steps": ["A duty of {f1} is collected on imported steel", "Importers' landed costs could rise",
                                "Steel-using manufacturers could pay more or switch suppliers"],
                      "affected": [{"kind": "firms", "name": "steel importers", "how": "could pay the duty"},
                                   {"kind": "industry", "name": "steel-using manufacturers",
                                    "how": "could face higher input costs"}],
                      "conditions": "If the tariff takes effect as announced", "horizon": "months",
                      "basis": [fact, "figure:f1"], "assumptions": ["a1"]}],
        "second_order": [{"id": "s1", "from": "m1", "horizon": "quarters", "basis": [fact], "assumptions": ["a1"],
                          "conditions": "If domestic producers have spare capacity and buyers can switch",
                          "text": "SYNTHETIC: domestic steelmakers could gain sales if buyers switch away from "
                                  "imported steel."}],
        "alternatives": [{"kind": "offsetting_force", "support": "bounded_inference", "basis": [],
                          "assumptions": ["a2"],
                          "text": "SYNTHETIC: foreign exporters might absorb part of the duty by cutting their "
                                  "prices, which would reduce what buyers pay."}],
        "watch": [{"observable": "SYNTHETIC: the tariff's product list", "would": "support",
                   "text": "A list covering most steel imports would support a broad effect on buyers."},
                  {"observable": "SYNTHETIC: exemptions after talks", "would": "weaken",
                   "text": "Exemptions for major grades would narrow the effect."}]}


def with_report(economics: dict, entry_id: str) -> dict:
    """An explanation whose figures quote ``entry_id`` (the story's material report)."""
    import json
    return json.loads(json.dumps(economics).replace("{report}", entry_id))
DEVELOPMENTS = ((TARIFF, "Tariff announced"), (RESPONSE, "The Federation responds"), (REVISION, "Tariff narrowed"))

# ---------------------------------------------------------------- the SYNTHETIC annual-rate case (econ-fidelity-0.1)
# A statistic at a seasonally adjusted annual rate and a change inside its stated margin: what the fidelity browser
# check reads (tests/news_desk_server.py --fidelity-case). Every word is SYNTHETIC.

HOMES = "Synthetic new home sales at a 676,000 annual rate in September"
HOMES_EXCERPT = ("SYNTHETIC: Sales of new single-family houses in September were at a seasonally adjusted annual rate of "
                 "676,000. This is 0.6 percent (+/- 13.8%) below the revised August estimate of 680,000.")


# ---------------------------------------------------------------- SYNTHETIC surveys (econ-explanation-0.4)
# Two surveys whose answers measure credit conditions: one of banks, one of firms. Every word is SYNTHETIC; what the
# respondents are is stated by the reports themselves.

BANKS = "Synthetic bank lending survey: banks report tighter credit standards"
BANKS_EXCERPT = ("SYNTHETIC: In the quarterly bank lending survey, banks reported a net tightening of credit standards "
                 "for loans to firms (net percentage of 9% of banks) and a net decrease in demand for housing loans "
                 "(net percentage of -27%). Banks expect a further net tightening (net percentage of 7%) next quarter.")
FIRMS = "Synthetic survey of firms: bank loans less available"
FIRMS_EXCERPT = ("SYNTHETIC: In the survey on the access to finance of enterprises, firms reported a decrease in the "
                 "availability of bank loans (net percentage of -5%) and higher bank interest rates (net 46%).")


def survey_items(now: datetime) -> list[str]:
    return [item(COURIER.link_host, "banks", BANKS, now - timedelta(hours=4), BANKS_EXCERPT),
            item(COURIER.link_host, "firms", FIRMS, now - timedelta(hours=5), FIRMS_EXCERPT)]


def banks_brief(entry_id: str) -> dict:
    """A SYNTHETIC brief of the bank lending survey: banks' answers (form survey_answers, respondents banks) about
    credit conditions, its balances as net percentages, explained through the bank survey's framework note."""
    net = lambda **row: {"unit": "percent", "measure": "net_percentage", "period": "this quarter",  # noqa: E731
                         "basis": "not_applicable", "seasonal": "not_applicable", "price": False,
                         "source": f"report:{entry_id}", "vintage_label": None, "sign": "as_quoted", "sign_words": None,
                         "bound": "exact", "statistic": "other_summary", "stock_flow": "not_applicable", **row}
    return {
        "headline": "SYNTHETIC: banks report a net tightening of credit standards for loans to firms",
        "summary": "SYNTHETIC: in the quarterly bank lending survey, banks reported a net tightening of credit "
                   "standards for loans to firms (net percentage of 9% of banks) and a net decrease in demand for "
                   "housing loans (net percentage of -27%).",
        "facts": [{"text": "SYNTHETIC: banks reported a net tightening of credit standards for loans to firms.",
                   "reports": [entry_id]}],
        "implications": [{"text": "SYNTHETIC: firms that rely on bank loans could find credit harder to obtain if "
                                  "the tightening persists."}],
        "themes": [{"kind": "sector", "name": "Banking", "basis": "SYNTHETIC: the survey asks banks."}],
        "uncertainties": ["SYNTHETIC: the survey does not measure lending volumes."],
        "missing": ["SYNTHETIC: actual lending to firms."],
        "economics": {
            "status": "explained", "insufficient_reason": None,
            "change": {"stage": "observation", "instrument": "financial_conditions", "form": "survey_answers",
                       "respondents": "banks", "basis": ["fact:1", "figure:f1"],
                       "text": "SYNTHETIC: banks reported a net tightening of credit standards for loans to firms "
                               "({f1}) and a net decrease in demand for housing loans ({f2})."},
            "significance": {"basis": ["fact:1", "figure:f1"],
                             "text": "SYNTHETIC: tighter reported standards may come before slower lending to firms "
                                     "if they persist; the {f1} balance counts banks, not loans."},
            "main_uncertainty": "SYNTHETIC: whether reported standards show up in lending.",
            "figures": [net(id="f1", label="SYNTHETIC net tightening for loans to firms", value=9,
                            quote="net percentage of 9% of banks"),
                        net(id="f2", label="SYNTHETIC net demand for housing loans", value=-27,
                            quote="net percentage of -27%")],
            "calculations": [],
            "assumptions": [{"id": "a1", "text": "SYNTHETIC: banks apply the standards they report to new loans."}],
            "channels": [{"id": "m1", "scope": "macro", "support": "framework", "note": "bank-lending-survey",
                          "text": "SYNTHETIC: if banks keep stricter approval criteria, firms that rely on bank loans "
                                  "could find credit harder to obtain, which may later weigh on lending.",
                          "steps": ["SYNTHETIC: banks report stricter criteria ({f1})",
                                    "Some firms could find loans harder to get"],
                          "affected": [{"kind": "firms", "name": "SYNTHETIC firms that borrow from banks",
                                        "how": "could find loans harder to obtain"}],
                          "conditions": None, "horizon": "quarters", "basis": ["fact:1", "figure:f1"],
                          "assumptions": ["a1"]}],
            "second_order": [],
            "alternatives": [{"kind": "competing_explanation", "support": "bounded_inference",
                              "basis": ["figure:f2"], "assumptions": ["a1"],
                              "text": "SYNTHETIC: weaker demand for housing loans ({f2}) rather than tighter supply "
                                      "could lie behind slower lending."}],
            "watch": [{"observable": "SYNTHETIC: loan statistics", "would": "weaken",
                       "text": "Steady lending volumes would weaken the reading."}]}}


def publish_banks(desk, now: datetime, actor: str = "synthetic-editor") -> str:
    """Save and publish the SYNTHETIC bank lending survey brief (method synthetic); its story ID."""
    from second_order import news_views, story_briefs
    story = next(row for row in news_views.world(desk, now)["stories"].values()
                 if any(report["title"] == BANKS for report in row["reports"]))
    done, _ = story_briefs.add_version(desk.newsroom, story["story_id"], {
        "content": banks_brief(story["material"]["reports"][0]["entry_id"]), "method": "synthetic", "based_on": None,
        "idempotency_key": f"banks-{now.strftime('%Y%m%d%H%M%S')}"}, story["material"], actor, now,
        method="synthetic", preparation={"model": None, "cost": None})
    if not done["publishable"]:
        raise RuntimeError(f"The SYNTHETIC bank survey brief stops publication: {done['guard']['findings']}")
    story_briefs.publish(desk.newsroom, story["story_id"], {"version": done["version"], "reason": "SYNTHETIC check",
                                                            "idempotency_key": f"banks-p-{now.strftime('%H%M%S')}"},
                         actor, now)
    return story["story_id"]


def homes_item(now: datetime) -> str:
    return item(COURIER.link_host, "homes", HOMES, now - timedelta(hours=3), HOMES_EXCERPT)


def homes_brief(entry_id: str) -> dict:
    """A SYNTHETIC brief whose explanation names an annual-rate level and a change inside its stated margin by
    reference only, so the reader's page must say what each is."""
    figure = lambda **row: {"label": "SYNTHETIC", "unit": "houses", "measure": "level", "period": "September",  # noqa
                            "basis": "not_stated", "seasonal": "seasonally_adjusted", "price": False,
                            "source": f"report:{entry_id}", "vintage_label": None, "sign": "as_quoted",
                            "sign_words": None, "bound": "exact", "statistic": "observed",
                            "stock_flow": "flow_annual_rate", **row}
    return {
        "headline": "SYNTHETIC: new home sales at a 676,000 annual rate, 0.6 percent below August",
        "summary": "SYNTHETIC: the statistics office said sales of new single-family houses were at a seasonally "
                   "adjusted annual rate of 676,000 in September, 0.6 percent below August's revised 680,000.",
        "facts": [{"text": "SYNTHETIC: sales were at a seasonally adjusted annual rate of 676,000 in September.",
                   "reports": [entry_id]}],
        "implications": [{"text": "SYNTHETIC: demand for new homes may have been steady, if the estimate holds."}],
        "themes": [{"kind": "sector", "name": "Housing", "basis": "SYNTHETIC: the report concerns new home sales."}],
        "uncertainties": ["SYNTHETIC: the change is within the stated margin of error."],
        "missing": ["SYNTHETIC: regional detail."],
        "economics": {
            "status": "explained", "insufficient_reason": None,
            "change": {"stage": "observation", "instrument": "housing", "form": "reported_observation",
                       "respondents": None, "basis": ["fact:1"],
                       "text": "SYNTHETIC: new single-family house sales were {f1} in September, {f2} from the revised "
                               "August estimate."},
            "significance": {"basis": ["fact:1", "figure:f2"],
                             "text": "SYNTHETIC: sales may have been about as strong as in August; the {f2} change is "
                                     "small next to its stated margin of error."},
            "main_uncertainty": "SYNTHETIC: whether the estimate is revised.",
            "figures": [figure(id="f1", label="SYNTHETIC September new home sales", value=676000,
                               quote="seasonally adjusted annual rate of 676,000"),
                        figure(id="f2", label="SYNTHETIC change from August", value=-0.6, unit="percent",
                               measure="change", stock_flow="not_applicable", sign="from_words", sign_words="below",
                               period="September against August",
                               quote="0.6 percent (+/- 13.8%) below the revised August estimate")],
            "calculations": [],
            "assumptions": [{"id": "a1", "text": "SYNTHETIC: the rate of {f1} is not revised away."}],
            "channels": [{"id": "m1", "scope": "micro", "support": "framework", "note": "official-statistics",
                          "text": "SYNTHETIC: builders could read the rate of {f1} as steady demand, though the "
                                  "change may be within sampling error.",
                          "steps": ["SYNTHETIC: the rate is {f1}", "Builders could keep their plans"],
                          "affected": [{"kind": "industry", "name": "SYNTHETIC home builders",
                                        "how": "could see steady demand at {f1}"}],
                          "conditions": None, "horizon": "months", "basis": ["fact:1", "figure:f1"],
                          "assumptions": ["a1"]}],
            "second_order": [],
            "alternatives": [{"kind": "competing_explanation", "support": "event_evidence",
                              "basis": ["fact:1", "figure:f2"], "assumptions": [],
                              "text": "SYNTHETIC: the {f2} change may be sampling noise."}],
            "watch": [{"observable": "SYNTHETIC: the next estimate", "would": "weaken",
                       "text": "A large revision of {f1} would weaken the reading."}]}}


def publish_homes(desk, now: datetime, actor: str = "synthetic-editor") -> str:
    """Save and publish the SYNTHETIC annual-rate brief of the HOMES story (method synthetic); its story ID."""
    from second_order import news_views, story_briefs
    story = next(row for row in news_views.world(desk, now)["stories"].values()
                 if any(report["title"] == HOMES for report in row["reports"]))
    done, _ = story_briefs.add_version(desk.newsroom, story["story_id"], {
        "content": homes_brief(story["material"]["reports"][0]["entry_id"]), "method": "synthetic", "based_on": None,
        "idempotency_key": f"homes-{now.strftime('%Y%m%d%H%M%S')}"}, story["material"], actor, now,
        method="synthetic", preparation={"model": None, "cost": None})
    if not done["publishable"]:
        raise RuntimeError(f"The SYNTHETIC annual-rate brief stops publication: {done['guard']['findings']}")
    story_briefs.publish(desk.newsroom, story["story_id"], {"version": done["version"], "reason": "SYNTHETIC check",
                                                            "idempotency_key": f"homes-p-{now.strftime('%H%M%S')}"},
                         actor, now)
    return story["story_id"]


def curate(desk, now: datetime, actor: str = "synthetic-editor", method: str = "editorial",
           economics: bool = True) -> dict:
    """What the SYNTHETIC editors decided, through the real actions: group the reports, merge the two independent
    reports of the response, publish a brief of the tariff story, and link three developments to a topic. Returns
    the story and topic IDs."""
    from second_order import news_reports, news_stories, news_topics, news_views, story_briefs
    keys = iter(f"curate-{now.strftime('%Y%m%d%H%M%S')}-{number:04d}" for number in range(10_000))
    reports = news_reports.pool(desk.inbox, desk.feeds, desk.publishers)["reports"]
    news_stories.group(desk.newsroom, reports, news_reports.publisher_names(desk.publishers), actor, now, next(keys))

    def story(title: str) -> str:
        return next(story_id for story_id, row in news_views.world(desk, now)["stories"].items()
                    if any(report["title"] == title for report in row["reports"]))
    news_stories.merge(desk.newsroom, story(RESPONSE_OWN), {"into": story(RESPONSE), "reason": "SYNTHETIC: one "
                       "response, reported twice in different words", "idempotency_key": next(keys)}, actor, now)
    tariff = news_views.world(desk, now)["stories"][story(TARIFF)]
    first = tariff["material"]["reports"][0]["entry_id"]
    content = {**TARIFF_BRIEF, "facts": [{"text": "The Synthetic Republic said it would impose a 15% tariff on "
                                                  "imported steel.", "reports": [first]}]}
    if economics:
        content["economics"] = with_report(tariff_economics(), first)
    preparation = {"model": None, "cost": None} if method == "synthetic" else None
    done, _ = story_briefs.add_version(desk.newsroom, tariff["story_id"], {
        "content": content, "method": method, "based_on": None, "idempotency_key": next(keys)},
        tariff["material"], actor, now, method=method, preparation=preparation)
    story_briefs.publish(desk.newsroom, tariff["story_id"], {"version": done["version"], "reason": "SYNTHETIC check",
                                                             "idempotency_key": next(keys)}, actor, now)
    topic, _ = news_topics.create(desk.newsroom, {"title": TOPIC, "summary": (
        "SYNTHETIC: a tariff, a response and a revision, invented to show how an ongoing topic is followed."),
        "reason": "SYNTHETIC", "idempotency_key": next(keys)}, actor, now)
    for title, label in DEVELOPMENTS:
        news_topics.link(desk.newsroom, topic["topic_id"], {"story_id": story(title), "action": "link", "label": label,
                                                            "reason": "SYNTHETIC", "idempotency_key": next(keys)},
                         actor, now)
    assess(desk, now, {UNRELATED: "outside_scope"}, actor, synthetic_only=True)
    return {"topic_id": topic["topic_id"], **{title: story(title) for title, _ in DEVELOPMENTS},
            "port": story("Synthetic port reports record container volumes"), "unrelated": story(UNRELATED)}


# ---------------------------------------------------------------- SYNTHETIC White House pages (news_texts)
# SYNTHETIC entries and pages at the registered White House addresses, answered only by a simulated network: the text
# tests, the stories fixtures and the stories browser check read them; no real page is ever requested.

WH = news_registry.PUBLISHERS["whitehouse-news"].feed
FACT = "https://www.whitehouse.gov/fact-sheets/2026/10/synthetic-tariff-fact-sheet/"
ACTION = "https://www.whitehouse.gov/presidential-actions/2026/10/synthetic-tariff-proclamation/"
BROKEN = "https://www.whitehouse.gov/fact-sheets/2026/10/synthetic-broken-page/"
TABLED = "https://www.whitehouse.gov/fact-sheets/2026/10/synthetic-table-page/"
FACT_TITLE = "Fact Sheet: Synthetic tariffs on imported widgets"
WORDS = ("SYNTHETIC: Today the President signed a proclamation imposing a 12% tariff on imported widgets, effective "
         "November 1, 2026. It applies to widgets from every country except two partners named in an annex.")


def wh_page(title: str, paragraphs: list[str], table: bool = False) -> bytes:
    """A SYNTHETIC page in the White House's layout: a topper with the headline and date, then the post's blocks."""
    body = "".join(f'<p class="wp-block-paragraph">{escape(text)}</p>' for text in paragraphs)
    body += '<ul class="wp-block-list"><li>SYNTHETIC first point of the fact sheet.</li><li>SYNTHETIC second point, ' \
            'with <strong>emphasis</strong>.</li></ul>'
    if table:
        body += "<table><tr><td>SYNTHETIC cell</td></tr></table>"
    return ('<!DOCTYPE html><html lang="en-US"><head><meta charset="UTF-8" /><title>x</title></head><body>'
            '<header><h1>The White House</h1></header><main id="wp--skip-link--target">'
            '<div class="entry-content wp-block-post-content"><div class="wp-block-whitehouse-topper">'
            f'<h1 class="wp-block-whitehouse-topper__headline">{escape(title)}</h1>'
            '<div class="wp-block-post-date"><time datetime="2026-10-14T08:30:00-04:00">October 14, 2026</time></div>'
            f'</div>{body}</div></main><footer><p>Share this</p></footer></body></html>').encode("utf-8")


def wh_feed() -> bytes:
    items = []
    for link, title, hours in ((FACT, FACT_TITLE, 3), (ACTION, "SYNTHETIC: Imposing tariffs on imported widgets", 2),
                               (BROKEN, "SYNTHETIC: A fact sheet whose page cannot be read", 4),
                               (TABLED, "SYNTHETIC: A fact sheet holding a table", 5)):
        moment = (START - timedelta(hours=hours)).strftime("%a, %d %b %Y %H:%M:%S GMT")
        items.append(f"<item><title>{escape(title)}</title><link>{link}</link><guid>{link}</guid>"
                     f"<description>SYNTHETIC excerpt: tariffs on imported widgets.</description>"
                     f"<pubDate>{moment}</pubDate></item>")
    return rss(items, "SYNTHETIC White House")


class Pages:
    """A simulated network answering publication pages; every request is kept."""

    def __init__(self, answers: dict[str, tuple[int, bytes, str]]):
        self.answers, self.requests = dict(answers), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        status, body, media = self.answers.get(str(request.url), (404, b"not here", "text/html"))
        return httpx.Response(status, content=body, headers={"content-type": media})


def pages() -> Pages:
    return Pages({FACT: (200, wh_page(FACT_TITLE, [WORDS, "SYNTHETIC: The annex lists the two partners."]),
                         "text/html; charset=UTF-8"),
                  ACTION: (200, wh_page("SYNTHETIC: Imposing tariffs on imported widgets",
                                        ["SYNTHETIC: BY THE PRESIDENT OF THE UNITED STATES OF AMERICA. A PROCLAMATION. "
                                         "1. Imports of widgets threaten to impair the national security, as the "
                                         "Secretary reported. 2. A duty of 12% applies from November 1, 2026."]),
                           "text/html; charset=UTF-8"),
                  BROKEN: (200, b"<html><body><div class='other'>SYNTHETIC page of another layout</div></body></html>",
                           "text/html; charset=UTF-8"),
                  TABLED: (200, wh_page("SYNTHETIC: A fact sheet holding a table", [WORDS], table=True),
                           "text/html; charset=UTF-8")})


def text_desk(root: Path, retrieve: bool = True):
    """A desk over ``root`` holding the SYNTHETIC White House entries, grouped (the proclamation merged into its fact
    sheet's story), with its page network; with ``retrieve``, every page's text retrieved once. Returns (desk,
    pages)."""
    from dataclasses import replace
    from second_order import news_reports, news_stories, news_texts
    served = pages()
    desk = replace(desk_in(root, chosen=dict(news_registry.PUBLISHERS), network=Feeds({WH.feed_url: (200, wh_feed())})),
                   text_fetcher=news_texts.fetcher(httpx.MockTransport(served)))
    news_feeds.refresh(desk.feeds, desk.fetcher, [news_registry.PUBLISHERS["whitehouse-news"]], lambda: START)
    reports = news_reports.pool(desk.inbox, desk.feeds, desk.publishers)["reports"]
    news_stories.group(desk.newsroom, reports, set(), "setup", START, "text-group-0001")
    found = news_views.world(desk, START)["stories"]
    by_title = {report["title"]: story_id for story_id, story in found.items() for report in story["reports"]}
    news_stories.merge(desk.newsroom, by_title["SYNTHETIC: Imposing tariffs on imported widgets"], {
        "into": by_title[FACT_TITLE], "reason": "SYNTHETIC: one development", "idempotency_key": "text-merge-0001"},
        "setup", START)
    if retrieve:
        news_texts.retrieve_all(desk.texts, list(reports.values()), {}, desk.text_fetcher, lambda: START,
                                sleep=lambda seconds: None)
    return desk, served


# ---------------------------------------------------------------- a SIMULATED news index (news_index)
# The GDELT index answered only by a simulated network: the index tests and the stories fixtures read it.

INDEXED = "Steel buyers brace as Synthetic Republic duties hit 15% after Marrowvale review"


def index_answer(articles: list[dict]):
    """A SIMULATED GDELT DOC answer holding ``articles``; every request it received is kept on it."""
    import json

    def answer(request: httpx.Request) -> httpx.Response:
        answer.requests.append(str(request.url))
        return httpx.Response(200, content=json.dumps({"articles": articles}).encode("utf-8"),
                              headers={"content-type": "application/json"})
    answer.requests = []
    return answer


def index_desk(root: Path):
    """A desk over ``root`` with one story covered by three SYNTHETIC indexed domains, attached through the real
    lookup and attach actions. Returns (desk, story_id)."""
    from second_order import news_index, news_reports, news_stories
    seen = lambda hours: (START - timedelta(hours=hours)).strftime("%Y%m%dT%H%M%SZ")  # noqa: E731
    answers = trade_feeds(START)
    answers[COURIER.feed_url] = (200, rss([item(COURIER.link_host, "duties", INDEXED, START - timedelta(hours=40),
                                                "Importers in Marrowvale said the new 15% levy would apply.")]))
    desk = desk_in(root, network=Feeds(answers))
    news_feeds.refresh(desk.feeds, desk.fetcher, [row for row in desk.publishers.values() if row.synthetic],
                       lambda: START)
    reports = news_reports.pool(desk.inbox, desk.feeds, desk.publishers)["reports"]
    news_stories.group(desk.newsroom, reports, set(), "setup", START, "index-group-0001")
    assess(desk, START, synthetic_only=True)
    story_id = next(story_id for story_id, story in news_views.world(desk, START)["stories"].items()
                    if story["title"] == INDEXED)
    articles = [{"url": f"https://www.{domain}/news/{n}", "title": title, "domain": domain, "seendate": seen(hours),
                 "language": "English", "sourcecountry": "Synthetic"} for n, (domain, title, hours) in enumerate((
                     ("synthetic-wire.example", "Marrowvale importers brace for 15% steel duties", 30),
                     ("synthetic-post.example", "Marrowvale importers brace for 15% steel duties", 29),
                     ("synthetic-review.example", "Republic's Marrowvale review ends with 15% duties", 28)))]
    record = news_index.lookup(desk, story_id, START, httpx.MockTransport(index_answer(articles)))
    news_index.attach(desk, story_id, record["lookup_id"], {"reason": "SYNTHETIC: indexed coverage.",
                                                            "idempotency_key": "index-attach-0001"}, "setup", START)
    return desk, story_id



# ---------------------------------------------------------------- SYNTHETIC claims and an opened procedure (brief_claims)
# A SYNTHETIC safeguard investigation, opened but undecided: the duty that may follow is conditional and a bound, so
# its brief records who says what (story-brief-0.4), its development is a procedure (econ-explanation-0.5) and its
# figure is shown as conditional. Read by the stories fixtures and the news fidelity browser check.

WIRE = "Synthetic Republic opens safeguard investigation into imported steel wire"
WIRE_EXCERPT = ("SYNTHETIC: The Synthetic Republic said it had opened a safeguard investigation into imports of steel "
                "wire. A safeguard duty of up to 25% may be imposed only if increased imports are found to cause "
                "serious injury.")
WIRE_OPENED = "The Synthetic Republic said it had opened a safeguard investigation into imports of steel wire"
WIRE_DUTY = ("A safeguard duty of up to 25% may be imposed only if increased imports are found to cause serious "
             "injury")
WIRE_CONDITION = "only if increased imports are found to cause serious injury"


def wire_item(now: datetime) -> str:
    return item(COURIER.link_host, "wire-safeguard", WIRE, now - timedelta(hours=2), WIRE_EXCERPT)


def wire_brief(entry_id: str) -> dict:
    """A SYNTHETIC brief of the opened investigation, recording its two claims: the opening, as the Republic states
    it, and the duty that may follow only under a condition."""
    source = f"report:{entry_id}"
    return {
        "headline": "SYNTHETIC: Synthetic Republic opens a safeguard investigation into steel wire imports",
        "summary": ("SYNTHETIC: the Synthetic Republic said it had opened a safeguard investigation into steel wire "
                    "imports; a duty may follow only if serious injury is found."),
        "facts": [{"text": "SYNTHETIC: the Republic opened a safeguard investigation into steel wire imports.",
                   "reports": [entry_id], "claims": ["k1"]},
                  {"text": "SYNTHETIC: a duty of up to 25% may be imposed only if serious injury is found.",
                   "reports": [entry_id], "claims": ["k2"]}],
        "claims": [{"id": "k1", "holder": "issuer", "holder_name": "Synthetic Republic", "modality": "asserted",
                    "quote": WIRE_OPENED, "condition": None, "source": source},
                   {"id": "k2", "holder": "issuer", "holder_name": "Synthetic Republic", "modality": "conditional",
                    "quote": WIRE_DUTY, "condition": WIRE_CONDITION, "source": source}],
        "implications": [{"text": "SYNTHETIC: wire buyers could pay more if a duty is imposed."}], "themes": [],
        "uncertainties": ["SYNTHETIC: whether serious injury will be found is not known."], "missing": [],
        "economics": {
            "status": "explained", "insufficient_reason": None,
            "change": {"stage": "procedure", "instrument": "trade_remedy", "form": "announcement_or_decision",
                       "respondents": None, "basis": ["fact:1"],
                       "text": "SYNTHETIC: the Synthetic Republic opened a safeguard investigation into steel wire "
                               "imports; no measure is decided."},
            "significance": {"basis": ["fact:2", "figure:f1"],
                             "text": "SYNTHETIC: a duty of {f1} on imported wire could raise costs for wire users."},
            "main_uncertainty": "SYNTHETIC: whether the investigation finds serious injury.",
            "figures": [{"id": "f1", "label": "SYNTHETIC safeguard duty that may be imposed", "value": 25,
                         "unit": "percent", "measure": "rate", "period": "if imposed", "basis": "not_applicable",
                         "seasonal": "not_applicable", "price": False, "source": source,
                         "quote": "A safeguard duty of up to 25%", "vintage_label": None, "sign": "as_quoted",
                         "sign_words": None, "bound": "upper_bound", "statistic": "observed",
                         "stock_flow": "not_applicable"}],
            "calculations": [], "assumptions": [],
            "channels": [{"id": "m1", "scope": "micro", "support": "event_evidence", "note": None,
                          "text": "SYNTHETIC: if a duty is imposed, firms that use imported wire could pay more.",
                          "steps": ["A duty of up to {f1} is imposed", "Importers' costs could rise"],
                          "affected": [{"kind": "firms", "name": "SYNTHETIC wire users", "how": "could pay more"}],
                          "conditions": "If serious injury is found and a duty is imposed", "horizon": "months",
                          "basis": ["fact:2", "figure:f1"], "assumptions": []}],
            "second_order": [],
            "alternatives": [{"kind": "competing_explanation", "support": "event_evidence", "basis": ["fact:1"],
                              "assumptions": [],
                              "text": "SYNTHETIC: the investigation may end without any measure."}],
            "watch": [{"observable": "SYNTHETIC: the injury finding", "would": "support",
                       "text": "A finding of serious injury would make a duty more likely."}]}}


def publish_wire(desk, now: datetime, actor: str = "synthetic-editor") -> str:
    """Save and publish the SYNTHETIC opened-investigation brief (method synthetic), checked against its evidence; its
    story ID."""
    from second_order import news_views, story_briefs, story_economics
    story = next(row for row in news_views.world(desk, now)["stories"].values()
                 if any(report["title"] == WIRE for report in row["reports"]))
    basis = story_economics.evidence(story["material"], desk.texts, None, story["first_at"])
    done, _ = story_briefs.add_version(desk.newsroom, story["story_id"], {
        "content": wire_brief(story["material"]["reports"][0]["entry_id"]), "method": "synthetic", "based_on": None,
        "idempotency_key": f"wire-{now.strftime('%Y%m%d%H%M%S')}"}, story["material"], actor, now,
        method="synthetic", preparation={"model": None, "cost": None}, basis=basis)
    if not done["publishable"]:
        raise RuntimeError(f"The SYNTHETIC investigation brief stops publication: {done['guard']['findings']}")
    story_briefs.publish(desk.newsroom, story["story_id"], {"version": done["version"], "reason": "SYNTHETIC check",
                                                            "idempotency_key": f"wire-p-{now.strftime('%H%M%S')}"},
                         actor, now)
    return story["story_id"]
