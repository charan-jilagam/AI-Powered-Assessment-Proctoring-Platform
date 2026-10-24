"""Code similarity screening and the built-in question library."""
import pytest

from app import similarity
from tests.test_coding import PY, cenv, coding_test, start, submit  # noqa: F401  (cenv fixture)

BASE = """
import sys
def solve(values):
    total = 0
    for value in values:
        if value % 2 == 0:
            total += value * 2
        else:
            total -= value
    return total

def main():
    data = sys.stdin.read().split()
    values = [int(x) for x in data]
    print(solve(values))

main()
"""
# same program, different names, comments and spacing
RENAMED = """
import sys
# totally different comment
def compute(items):
    acc = 0
    for item in items:
        if item % 2 == 0:
            acc += item * 2
        else:
            acc -= item
    return acc


def run():
    raw = sys.stdin.read().split()
    nums = [int(t) for t in raw]
    print(compute(nums))


run()
"""
DIFFERENT = """
import sys
from collections import Counter

def run():
    words = sys.stdin.read().split()
    freq = Counter(words)
    best = max(freq.values()) if freq else 0
    winners = sorted(w for w, c in freq.items() if c == best)
    print(len(freq), best)
    for w in winners:
        print(w)

run()
"""


def test_renaming_variables_does_not_hide_a_copy():
    a = similarity.shingles(similarity.normalize(BASE))
    b = similarity.shingles(similarity.normalize(RENAMED))
    assert similarity.score(a, b) >= similarity.HIGH


def test_different_programs_score_low():
    a = similarity.shingles(similarity.normalize(BASE))
    c = similarity.shingles(similarity.normalize(DIFFERENT))
    assert similarity.score(a, c) < similarity.MEDIUM


def test_tiny_solutions_are_never_scored():
    tiny = similarity.shingles(similarity.normalize("print(sum(map(int, input().split())))"))
    assert tiny == frozenset() and similarity.score(tiny, tiny) is None


def test_endpoint_flags_copies_and_is_tenant_scoped(cenv):
    org = cenv.make_org()
    test = coding_test(cenv, org)
    a, b, c = (start(cenv, org, test, email=f"cand{i}@x.example.com") for i in range(3))
    submit(cenv, a, BASE)
    submit(cenv, b, RENAMED)
    submit(cenv, c, DIFFERENT)
    r = cenv.client.get(f"/tests/{test['id']}/similarity", headers=org["headers"])
    assert r.status_code == 200
    pairs = r.json()["pairs"]
    assert len(pairs) == 1 and pairs[0]["level"] == "high"
    ids = {pairs[0]["a"]["attempt_id"], pairs[0]["b"]["attempt_id"]}
    rep = cenv.client.get(f"/attempts/{sorted(ids)[0]}", headers=org["headers"]).json()
    assert rep["similarity"] and rep["similarity"][0]["level"] == "high"
    # another organisation can neither see this test's pairs nor probe its existence
    other = cenv.make_org()
    assert cenv.client.get(f"/tests/{test['id']}/similarity", headers=other["headers"]).status_code == 404


def test_same_candidate_resubmitting_is_not_a_match(cenv):
    org = cenv.make_org()
    test = coding_test(cenv, org)
    a = start(cenv, org, test)
    submit(cenv, a, BASE)
    submit(cenv, a, RENAMED)
    assert cenv.client.get(f"/tests/{test['id']}/similarity", headers=org["headers"]).json()["pairs"] == []


# ---------------------------------------------------------------- library
def test_library_import_is_idempotent_and_valid(env):
    org = env.make_org()
    overview = env.client.get("/bank/library", headers=org["headers"]).json()["sections"]
    assert sum(s["questions"] for s in overview) >= 30 and all(s["imported"] == 0 for s in overview)
    first = env.client.post("/bank/library/import", headers=org["headers"], json={}).json()
    assert first["added"] >= 30 and first["skipped"] == 0
    again = env.client.post("/bank/library/import", headers=org["headers"], json={}).json()
    assert again["added"] == 0 and again["skipped"] == first["added"]
    bank = env.client.get("/bank/questions?page_size=100", headers=org["headers"]).json()
    assert bank["total"] == first["added"]


def test_library_import_respects_sections_and_tenancy(env):
    org, other = env.make_org(), env.make_org()
    r = env.client.post("/bank/library/import", headers=org["headers"], json={"sections": ["SQL"]}).json()
    assert 0 < r["added"] < 10
    assert env.client.get("/bank/questions", headers=other["headers"]).json()["total"] == 0


def test_library_is_admin_only(env):
    org = env.make_org()
    rev = env.add_member(org, "reviewer")["headers"]
    assert env.client.post("/bank/library/import", headers=rev, json={}).status_code == 403
