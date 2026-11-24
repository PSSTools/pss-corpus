"""Structure enumeration (activity design §9.3): every legal structure of a
tiny model, found by solving each order the activity allows with free values.
A tool's runs are then judged against the set (soundness) and must reach
each member (reachability)."""

from pss_corpus import PASS
from pss_corpus.check import enumerate_structures

from test_infer import DO_C, DO_N, _run, _test


def _inferred(found):
    return sorted(k[1] for k in found)


def test_select_lists_each_branch():
    found, cut = enumerate_structures(_test({"select": [{"body": DO_C}, {"body": DO_N}]}))
    assert not cut
    assert sorted(found.values()) == [("N",), ("P", "C")]


def test_unfed_branch_is_not_legal_without_inference():
    found, _ = enumerate_structures(_test({"select": [{"body": DO_C}, {"body": DO_N}]}, allowed=False))
    assert list(found.values()) == [("N",)]


def test_inference_adds_the_producer_and_chains_within_the_limit():
    found, _ = enumerate_structures(_test({"par": [{"do": "P"}, {"do": "C"}]}))
    # A buffer is never fed from a parallel branch: C needs an inferred
    # producer, directly or through Q -> Y.
    assert _inferred(found) == [("P",), ("Q", "Y")]
    found, _ = enumerate_structures(_test({"par": [{"do": "P"}, {"do": "C"}]}), max_inferred=1)
    assert _inferred(found) == [("P",)]


def test_cut_off_runs_are_reported():
    # With inference allowed, a run at the limit could always have one more
    # inferred action, so the cut is conservative; here none is allowed.
    rep = {"repeat": {"count": 3}, "body": DO_N}
    found, cut = enumerate_structures(_test(rep, allowed=False), max_occ=2)
    assert cut and not found
    found, cut = enumerate_structures(_test(rep, allowed=False), max_occ=3)
    assert not cut and list(found.values()) == [("N", "N", "N")]


def test_a_judged_run_names_a_listed_structure(tmp_path):
    t = _test({"select": [{"body": DO_C}, {"body": DO_N}]})
    found, _ = enumerate_structures(t)
    v = _run(tmp_path, t, ["P o.v=5", "C k=0 i.v=5"])
    assert v.verdict == PASS, v.reason
    assert found[v.structure] == ("P", "C")
