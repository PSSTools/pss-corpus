"""The extractor is strict: formatting differences are findings, not noise."""

import pytest

from pss_corpus.trace import ProtocolError, extract, parse_value, value_matches


def test_decoration_before_the_sentinel_is_ignored():
    recs = extract("[ZSP] 12ns UVM_INFO @@PSS-TRACE act pss_top::A n=3\n")
    assert len(recs) == 1
    assert (recs[0].kind, recs[0].tag, recs[0].fields) == ("act", "pss_top::A", {"n": "3"})


def test_lines_without_the_sentinel_are_ignored():
    assert extract("hello\n\nworld\n") == []


@pytest.mark.parametrize("line", [
    "@@PSS-TRACE chk t a=   3",         # SV-style padding
    "@@PSS-TRACE chk t a=3 ",           # trailing space
    "@@PSS-TRACE chk t a",              # not key=value
    "@@PSS-TRACE chk t a=",             # empty value
    "@@PSS-TRACE chk t a=1 a=2",        # duplicate key
    "@@PSS-TRACE bogus t",              # unknown kind
    "@@PSS-TRACE chk",                  # no tag
])
def test_malformed_records_are_protocol_errors(line):
    with pytest.raises(ProtocolError):
        extract(line)


def test_a_carriage_return_is_not_forgiven():
    # Exactly one newline (§4.6): "\r\n" leaves a "\r" on the last value.
    rec = extract("@@PSS-TRACE chk t a=3\r\n")[0]
    assert not value_matches(rec.fields["a"], 3)


@pytest.mark.parametrize("tok,val", [
    ("0", 0), ("-1", -1), ("18446744073709551615", 18446744073709551615),
    ("0xdeadbeef", 0xdeadbeef), ("0x0", 0), ("true", True), ("false", False),
    ("GREEN", "GREEN"),
])
def test_values(tok, val):
    assert parse_value(tok) == val and type(parse_value(tok)) is type(val)


@pytest.mark.parametrize("tok", ["007", "+3", "0xDEAD", "0x00ff", "0x", "-0x1"])
def test_non_strict_numbers_are_not_values(tok):
    assert parse_value(tok) is None


def test_bool_is_not_an_integer():
    assert not value_matches("1", True)
    assert not value_matches("true", 1)


def test_string_expectation_compares_the_token():
    assert value_matches("100%", "100%")
