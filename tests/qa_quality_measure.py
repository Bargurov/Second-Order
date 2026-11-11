"""The research-quality measurement used by the released set (test_qa_quality_released_1) and by the private check.

``measure`` runs the reading layer and the lexical research-quality rubric over a set of SYNTHETIC cases and reports four
counts apart (the data owner's protocol, DATA_HANDOFF_20261015): replies the reading layer refuses; correct replies with
any flag; faulty replies flagged at the fault (a flag whose location is the planted fault's); and faulty replies without
one (a flag elsewhere is not a detection). These are counts of a lexical checker on synthetic replies, not a model's
accuracy, and a reply without flags is not shown to be correct: an interpretation the statements do not support is left
to the human review the rubric lists.

RELEASED_1_SHA256 and RELEASED_1_BASELINE are the committed fingerprint and the recorded measurements of released set 1
(tests/qa_quality_released_1.json, written after research-quality-0.2, measured on 0.2 and on 0.3 at data ed3a180 and
again at a970fbc, released on 15 October 2026).
"""
import hashlib
import json

from second_order import research_analysis as ra, research_quality
from second_order.research_reading import classify
from test_qa_research_quality import message

RELEASED_1_SHA256 = "42d273c72fd458d4a75447fd3b80c3d546fd30f9b0f9ea6b84fd021dcbb245e7"
# What each rubric version did with released set 1, measured by QA: the four counts and the SHA-256 of every case's flags
# (canonical JSON).
RELEASED_1_BASELINE = {
    "research-quality-0.2": {"rubric_version": "research-quality-0.2", "cases": 13, "correct": 5, "faulty": 8,
                             "refused_by_reading": 0, "correct_with_any_flag": 3, "faulty_flagged_at_fault": 3,
                             "faulty_without_flag_at_fault": 5,
                             "flags_sha256": "544f01cfa7cbbfe9969e22131dc4825b28a771e673ea92b39b68c474b1d2f756"},
    "research-quality-0.3": {"rubric_version": "research-quality-0.3", "cases": 13, "correct": 5, "faulty": 8,
                             "refused_by_reading": 0, "correct_with_any_flag": 2, "faulty_flagged_at_fault": 5,
                             "faulty_without_flag_at_fault": 3,
                             "flags_sha256": "71b49ca5b280560c085409838665050e2663c14e9c79fa5ce59c9aaa88e197b1"}}


def counts(result: dict) -> dict:
    return {key: len(value) if isinstance(value, list) else value for key, value in result.items() if key != "flags"} | {
        "flags_sha256": hashlib.sha256(json.dumps(result["flags"], sort_keys=True).encode("utf-8")).hexdigest()}


def measure(cases: dict, sources: dict) -> dict:
    rows = {}
    for name, case in cases.items():
        source = sources[case["source"]]
        read = classify(message(case["output"]), ra.MODEL, source["text"])
        if read["outcome"] not in ("analysis", "no additional finding"):
            rows[name] = {"refused": read["outcome"], "flags": []}
            continue
        found = research_quality.assess(source["headline"], source["text"], read["analysis"])
        assert found["rejected"] == [] and all(item["level"] == "flagged" for item in found["findings"])
        rows[name] = {"refused": None, "flags": sorted([item["check"], item["where"]] for item in found["findings"])}
    faulty = {name for name, case in cases.items() if case["fault"]}
    refused = sorted(name for name, row in rows.items() if row["refused"])
    at_fault = sorted(name for name in faulty - set(refused)
                      if any(where == cases[name]["fault"] for _, where in rows[name]["flags"]))
    return {
        "rubric_version": research_quality.RUBRIC_VERSION,
        "cases": len(cases), "correct": len(cases) - len(faulty), "faulty": len(faulty),
        "refused_by_reading": refused,
        "correct_with_any_flag": sorted(name for name in set(cases) - faulty - set(refused) if rows[name]["flags"]),
        "faulty_flagged_at_fault": at_fault,
        "faulty_without_flag_at_fault": sorted(faulty - set(refused) - set(at_fault)),
        "flags": rows,
    }
