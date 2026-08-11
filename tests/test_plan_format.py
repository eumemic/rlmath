import pytest

from rlmath.core.plan_format import PlanFormatError, parse_plan

GOOD = """Sure! Here's my decomposition plan:
#lemma h1 : 2 ∣ 4
#lemma h2 : 2 ∣ 6
#assembly
exact Dvd.dvd.add h1 h2
#end
Hope that helps!"""


def test_parse_good_plan_tolerates_chatter():
    plan = parse_plan(GOOD)
    assert [l.name for l in plan.lemmas] == ["h1", "h2"]
    assert plan.lemmas[0].prop == "2 ∣ 4"
    assert plan.assembly == "exact Dvd.dvd.add h1 h2"


def test_direct_plan():
    plan = parse_plan("#assembly\nnorm_num\n#end")
    assert plan.is_direct
    assert plan.assembly == "norm_num"


def test_multiline_assembly_preserved_verbatim():
    plan = parse_plan("#assembly\nintro n\n  simp [foo]\n#end")
    assert plan.assembly == "intro n\n  simp [foo]"


def test_blank_lines_between_lemmas_ok():
    plan = parse_plan("#lemma a : P\n\n#lemma b : Q\n#assembly\nexact t\n#end")
    assert len(plan.lemmas) == 2


def test_prop_may_contain_colons():
    plan = parse_plan("#lemma h : ∀ n : ℕ, n + 0 = n\n#assembly\nexact h 3\n#end")
    assert plan.lemmas[0].prop == "∀ n : ℕ, n + 0 = n"


@pytest.mark.parametrize(
    "bad",
    [
        "no markers at all",
        "#lemma h1 : P",                                        # no assembly
        "#assembly\nfoo",                                       # no end
        "#assembly\n\n#end",                                    # empty assembly
        "#lemma h1 h2 : P\n#assembly\nx\n#end",                 # malformed lemma line
        "#lemma h1 : P\n#lemma h1 : Q\n#assembly\nx\n#end",     # duplicate name
        "#lemma _plan : P\n#assembly\nx\n#end",                 # reserved name
        "#lemma goal : P\n#assembly\nx\n#end",                  # reserved name
        "#lemma 1h : P\n#assembly\nx\n#end",                    # invalid identifier
        "#assembly\nx\n#lemma h : P\n#end",                     # lemma after assembly
    ],
)
def test_parse_errors(bad):
    with pytest.raises(PlanFormatError):
        parse_plan(bad)
