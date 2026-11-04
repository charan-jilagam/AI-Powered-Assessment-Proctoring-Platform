"""Fixed question sets (A/B/C), the OMR answer sheet (live data, PDF downloads) and the sample aptitude test."""
import io
import zipfile
from types import SimpleNamespace

from pypdf import PdfReader

from app import omr_pdf, sample_tests, scoring


def pdf_text(data: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


def pages(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def Q(i, section="S", options=("a", "b", "c", "d"), qtype="single", correct=(0,)):
    return SimpleNamespace(id=i, position=i, question_type=qtype, question_text=f"Q{i}", options=list(options), correct=list(correct),
                           marks=1, negative_marks=0, section=section, difficulty="easy", explanation=None)


def sectioned(n=12):
    return [Q(i, section="Maths" if i <= n // 2 else "Verbal") for i in range(1, n + 1)]


# ------------------------------------------------------------------ pure set logic
def test_set_a_is_the_authored_order_and_other_sets_are_different_papers():
    qs = sectioned()
    orders = []
    for index in range(4):
        data, _ = scoring.build_set_paper(qs, exam_id=7, index=index, per_attempt=None, shuffle_options=True)
        orders.append([q["id"] for q in data])
    assert orders[0] == [q.id for q in qs]
    assert len({tuple(o) for o in orders}) == 4                                   # every set is a different paper


def test_a_set_is_identical_every_time_and_keeps_sections_together():
    qs = sectioned()
    first, _ = scoring.build_set_paper(qs, exam_id=7, index=2, per_attempt=None, shuffle_options=True)
    again, _ = scoring.build_set_paper(qs, exam_id=7, index=2, per_attempt=None, shuffle_options=True)
    assert first == again                                                         # question order AND option order
    sections = [q["section"] for q in first]
    assert sections == sorted(sections, key=lambda s: ["Maths", "Verbal"].index(s))   # Maths block, then Verbal block


def test_options_are_only_shuffled_in_later_sets_and_scoring_still_uses_text():
    qs = [Q(i) for i in range(1, 9)]
    a, key = scoring.build_set_paper(qs, exam_id=3, index=0, per_attempt=None, shuffle_options=True)
    b, _ = scoring.build_set_paper(qs, exam_id=3, index=1, per_attempt=None, shuffle_options=True)
    assert all(q["options"] == ["a", "b", "c", "d"] for q in a)
    assert any(q["options"] != ["a", "b", "c", "d"] for q in b)
    assert all(sorted(q["options"]) == ["a", "b", "c", "d"] for q in b)
    assert key["1"]["correct"] == ["a"]
    off, _ = scoring.build_set_paper(qs, exam_id=3, index=1, per_attempt=None, shuffle_options=False)
    assert all(q["options"] == ["a", "b", "c", "d"] for q in off)


def test_question_subset_is_the_same_in_every_set():
    qs = [Q(i) for i in range(1, 21)]
    ids = [{q["id"] for q in scoring.build_set_paper(qs, exam_id=9, index=i, per_attempt=8, shuffle_options=False)[0]} for i in range(3)]
    assert len(ids[0]) == 8 and ids[0] == ids[1] == ids[2]


def test_pick_set_keeps_sets_evenly_filled():
    used, picked = {}, []
    for _ in range(9):
        i = scoring.pick_set(used, 3)
        picked.append(scoring.set_letter(i))
        used[scoring.set_letter(i)] = used.get(scoring.set_letter(i), 0) + 1
    assert picked == list("ABCABCABC")
    assert scoring.pick_set({"A": 3, "B": 1, "C": 2}, 3) == 1
    assert scoring.set_index("c") == 2
    try:
        scoring.set_index("Z")
        assert False
    except ValueError:
        pass


# ------------------------------------------------------------------ API: sets
def sets_test(env, org, n_sets=3, omr=True, **kw):
    qs = [env.mcq(f"Q{i}?", ("w", "x", "y", "z"), i % 4, section="Maths" if i < 6 else "Verbal") for i in range(10)]
    return env.make_test(org, questions=qs, question_sets=n_sets, omr_enabled=omr, shuffle_questions=False, **kw)


def test_settings_round_trip(env):
    org = env.make_org()
    t = sets_test(env, org, omr_institute="Sconex Institute", omr_note="Hall 3")
    assert t["question_sets"] == 3 and t["omr_enabled"] is True and t["omr_institute"] == "Sconex Institute" and t["omr_note"] == "Hall 3"
    r = env.client.patch(f"/tests/{t['id']}", headers=org["headers"], json={"question_sets": 2, "omr_enabled": False, "omr_note": ""})
    assert r.status_code == 200 and r.json()["question_sets"] == 2 and r.json()["omr_enabled"] is False and r.json()["omr_note"] is None
    assert env.client.patch(f"/tests/{t['id']}", headers=org["headers"], json={"question_sets": 9}).status_code == 422
    dup = env.client.post(f"/tests/{t['id']}/duplicate", headers=org["headers"]).json()
    copy = env.client.get(f"/tests/{dup['id']}", headers=org["headers"]).json()
    assert copy["question_sets"] == 2 and copy["omr_institute"] == "Sconex Institute"
    default = env.make_test(org)
    assert default["question_sets"] == 1 and default["omr_enabled"] is False


def test_candidates_are_dealt_sets_evenly_and_a_set_is_one_identical_paper(env):
    org = env.make_org()
    t = sets_test(env, org)
    cands = [env.candidate(t["code"]) for _ in range(6)]
    letters = [c["state"]["paper_set"] for c in cands]
    assert letters == list("ABCABC")
    by_set = {}
    for c in cands:
        by_set.setdefault(c["state"]["paper_set"], []).append([(q["id"], q["options"]) for q in c["state"]["questions"]])
    for letter, papers in by_set.items():
        assert papers[0] == papers[1], letter                                      # same set, same paper, same option order
    assert by_set["A"][0] != by_set["B"][0] != by_set["C"][0]
    assert [q["id"] for q in cands[0]["state"]["questions"]] == sorted(q["id"] for q in cands[0]["state"]["questions"])   # set A = authored order
    # reopening the exam does not re-deal
    again = env.client.get("/attempt", headers=cands[1]["headers"]).json()
    assert again["paper_set"] == "B" and again["questions"] == cands[1]["state"]["questions"]
    # the staff list shows the set
    row = env.client.get(f"/tests/{t['id']}/attempts", headers=org["headers"]).json()["items"][0]
    assert row["paper_set"] in ("A", "B", "C")


def test_every_set_scores_correctly_whatever_the_order(env):
    org = env.make_org()
    t = sets_test(env, org)
    for _ in range(3):
        c = env.candidate(t["code"])
        answers = env.answer_all_correctly(org, t, c)
        done = env.client.post("/attempt/submit", headers=c["headers"], json={"answers": answers}).json()
        assert done["percentage"] == 100, c["state"]["paper_set"]


def test_without_sets_nothing_changes(env):
    org = env.make_org()
    t = env.make_test(org, questions=[env.mcq(f"Q{i}?") for i in range(5)])
    c = env.candidate(t["code"])
    assert c["state"]["paper_set"] is None and "omr" not in c["state"]


def test_changing_the_number_of_sets_is_blocked_while_candidates_are_live(env):
    org = env.make_org()
    t = sets_test(env, org)
    env.candidate(t["code"])
    r = env.client.patch(f"/tests/{t['id']}", headers=org["headers"], json={"question_sets": 2})
    assert r.status_code == 409
    assert env.client.patch(f"/tests/{t['id']}", headers=org["headers"], json={"omr_note": "ok"}).status_code == 200


# ------------------------------------------------------------------ API: OMR
def finish_with(env, t, answer_idx=None, **kw):
    """Start a candidate, mark option ``answer_idx`` (or nothing) on every question, submit."""
    c = env.candidate(t["code"], **kw)
    answers = {}
    if answer_idx is not None:
        for q in c["state"]["questions"]:
            answers[str(q["id"])] = q["options"][answer_idx]
    env.client.post("/attempt/submit", headers=c["headers"], json={"answers": answers})
    return c


def test_state_carries_the_live_omr_header_when_enabled(env):
    org = env.make_org(name="Sconex Org")
    t = sets_test(env, org, omr_institute="Sconex Institute", candidate_fields=[{"key": "roll", "label": "Roll number", "required": True}])
    c = env.candidate(t["code"], name="Asha Rao", fields={"roll": "R-42"}, phone="9999999999")
    omr = c["state"]["omr"]
    assert omr["enabled"] and omr["institute"] == "Sconex Institute" and omr["paper_set"] == "A" and omr["sets"] == "ABC"
    assert omr["candidate"]["name"] == "Asha Rao" and omr["candidate"]["fields"] == [{"label": "Roll number", "value": "R-42"}]
    assert omr["test_title"] == t["title"] and omr["started_at"]
    assert "correct" not in str(c["state"])                                       # still no answer key anywhere


def test_staff_download_a_candidate_omr(env):
    org = env.make_org()
    t = sets_test(env, org, omr_institute="Sconex Institute")
    c = finish_with(env, t, 1, name="Asha Rao")
    r = env.client.get(f"/attempts/{c['attempt_id']}/omr.pdf", headers=org["headers"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert "attachment" in r.headers["content-disposition"] and "Asha-Rao" in r.headers["content-disposition"]
    text = pdf_text(r.content)
    assert "Sconex Institute" in text and "Asha Rao" in text and "OMR ANSWER SHEET" in text and "EVALUATED" not in text
    assert pages(r.content) == 1


def test_evaluated_copy_is_admin_only_and_shows_the_score(env):
    org = env.make_org()
    t = sets_test(env, org)
    c = finish_with(env, t, 0)
    reviewer = env.add_member(org, "reviewer")
    url = f"/attempts/{c['attempt_id']}/omr.pdf?evaluated=true"
    assert env.client.get(url, headers=reviewer["headers"]).status_code == 403
    assert env.client.get(url.replace("?evaluated=true", ""), headers=reviewer["headers"]).status_code == 200      # blank-key copy is fine
    r = env.client.get(url, headers=org["headers"])
    assert r.status_code == 200
    text = pdf_text(r.content)
    assert "EVALUATED COPY" in text and ("PASS" in text or "FAIL" in text)
    assert "CORRECT" in text.upper() and "WRONG" in text.upper()


def test_one_pdf_with_every_candidate_zip_and_filters(env):
    org = env.make_org()
    t = sets_test(env, org)
    for name in ("Zed Zane", "Amy Ames", "Bob Bell", "Cy Cole"):
        finish_with(env, t, 1, name=name)
    finish_with(env, t, 1, name="Voided Vic")
    live = env.candidate(t["code"], name="Still Typing")
    voided = env.client.get(f"/tests/{t['id']}/attempts", headers=org["headers"]).json()["items"]
    vic = next(a for a in voided if a["candidate"]["name"] == "Voided Vic")
    assert env.client.post(f"/attempts/{vic['id']}/void", headers=org["headers"]).status_code == 200

    pdf = env.client.get(f"/tests/{t['id']}/omr.pdf", headers=org["headers"])
    assert pdf.status_code == 200 and pages(pdf.content) == 4                      # voided + still-running are left out
    text = pdf_text(pdf.content)
    assert "Voided Vic" not in text and "Still Typing" not in text and "Amy Ames" in text
    with_live = env.client.get(f"/tests/{t['id']}/omr.pdf?include_live=true", headers=org["headers"])
    assert pages(with_live.content) == 5

    set_a = env.client.get(f"/tests/{t['id']}/omr.pdf?set=A", headers=org["headers"])
    assert set_a.status_code == 200 and 0 < pages(set_a.content) < 4
    assert env.client.get(f"/tests/{t['id']}/omr.pdf?set=Q", headers=org["headers"]).status_code == 400

    z = env.client.get(f"/tests/{t['id']}/omr.zip", headers=org["headers"])
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert len(names) == 4 and all(n.endswith(".pdf") and "-Set-" in n for n in names)
    assert any("Amy-Ames" in n for n in names)
    assert env.client.get(f"/tests/{t['id']}/omr.zip?evaluated=true", headers=env.add_member(org, "reviewer")["headers"]).status_code == 403


def test_nothing_to_export_and_not_started_are_clear_errors(env):
    org = env.make_org()
    t = sets_test(env, org)
    assert env.client.get(f"/tests/{t['id']}/omr.pdf", headers=org["headers"]).status_code == 409
    lobby = env.candidate(t["code"], start=False)
    assert env.client.get(f"/attempts/{lobby['attempt_id']}/omr.pdf", headers=org["headers"]).status_code == 409


def test_blank_template_per_set(env):
    org = env.make_org()
    t = sets_test(env, org, omr_institute="Sconex Institute")
    every = env.client.get(f"/tests/{t['id']}/omr/blank.pdf", headers=org["headers"])
    assert every.status_code == 200 and pages(every.content) == 3                 # one sheet per set
    assert "BLANK TEMPLATE" in pdf_text(every.content)
    one = env.client.get(f"/tests/{t['id']}/omr/blank.pdf?set=B", headers=org["headers"])
    assert pages(one.content) == 1
    assert env.client.get(f"/tests/{t['id']}/omr/blank.pdf?set=F", headers=org["headers"]).status_code == 400   # test only has A-C
    plain = env.make_test(org, questions=[env.mcq()])
    assert pages(env.client.get(f"/tests/{plain['id']}/omr/blank.pdf", headers=org["headers"]).content) == 1


def test_omr_routes_are_tenant_scoped_and_staff_only(env):
    a, b = env.make_org(), env.make_org()
    t = sets_test(env, a)
    c = finish_with(env, t, 1)
    assert env.client.get(f"/attempts/{c['attempt_id']}/omr.pdf", headers=b["headers"]).status_code == 404
    assert env.client.get(f"/tests/{t['id']}/omr.pdf", headers=b["headers"]).status_code == 404
    assert env.client.get(f"/tests/{t['id']}/omr.pdf", headers=c["headers"]).status_code in (401, 403)   # a candidate is not staff
    assert env.client.get(f"/tests/{t['id']}/omr.pdf").status_code == 401


def test_candidate_can_download_only_their_own_sheet_and_only_when_enabled(env):
    org = env.make_org()
    on = sets_test(env, org, omr_institute="Sconex Institute")
    c = env.candidate(on["code"], name="Asha Rao")
    q = c["state"]["questions"][0]
    env.client.put("/attempt/answers", headers=c["headers"], json={"answers": {str(q["id"]): q["options"][2]}})
    r = env.client.get("/attempt/omr.pdf", headers=c["headers"])
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and "Asha Rao" in pdf_text(r.content)
    off = sets_test(env, org, omr=False)
    c2 = env.candidate(off["code"])
    assert "omr" not in c2["state"]
    r2 = env.client.get("/attempt/omr.pdf", headers=c2["headers"])
    assert r2.status_code == 403 and r2.json()["code"] == "omr_disabled"
    assert env.client.get("/attempt/omr.pdf").status_code == 401


def test_csv_export_has_the_set_column(env):
    org = env.make_org()
    t = sets_test(env, org)
    finish_with(env, t, 1)
    header = env.client.get(f"/tests/{t['id']}/export.csv", headers=org["headers"]).text.lstrip("﻿").splitlines()[0]
    assert "Question set" in header


# ------------------------------------------------------------------ the sheet renderer itself
def sheet(n=40, **kw):
    qs = [omr_pdf.OmrQuestion(i, "single", list("ABCD"), [i % 4]) for i in range(1, n + 1)]
    return omr_pdf.OmrSheet(institute="Inst", test_title="Test", questions=qs, candidate_name="Asha Rao", **kw)


def test_renderer_paginates_and_handles_odd_content():
    assert pages(omr_pdf.render([sheet(40)])) == 1
    assert pages(omr_pdf.render([sheet(400)])) >= 3
    assert pages(omr_pdf.render([sheet(40), sheet(40), sheet(40)])) == 3
    six = omr_pdf.OmrSheet(institute="I", test_title="T", questions=[omr_pdf.OmrQuestion(i, "single", list("ABCDEF"), [5]) for i in range(1, 61)])
    assert pages(omr_pdf.render([six])) == 1
    mixed = sheet(10).questions + [omr_pdf.OmrQuestion(11, "short_text", text="150 minutes"), omr_pdf.OmrQuestion(12, "true_false", ["T", "F"], [0])]
    out = omr_pdf.render([omr_pdf.OmrSheet(institute="I", test_title="T", questions=mixed)])
    assert "WRITTEN ANSWERS" in pdf_text(out) and "150 minutes" in pdf_text(out)
    weird = omr_pdf.OmrSheet(institute="X" * 300, test_title="Y" * 300, questions=sheet(3).questions, candidate_name="Ünïcode नाम ✓", note="n" * 500)
    assert pages(omr_pdf.render([weird])) == 1                                     # long text is shrunk, non-Latin text cannot crash it
    try:
        omr_pdf.render([])
        assert False
    except ValueError:
        pass


# ------------------------------------------------------------------ the sample aptitude test
def test_sample_aptitude_test_is_installed_with_sets_and_omr(env):
    org = env.make_org()
    r = env.client.post("/tests/samples", headers=org["headers"])
    assert r.status_code == 201 and len(r.json()["created"]) == 3
    rows = env.client.get("/tests", headers=org["headers"]).json()["items"]
    apt = next(t for t in rows if "OMR" in t["title"])
    assert apt["question_sets"] == 3 and apt["omr_enabled"] and apt["status"] == "published" and apt["question_count"] == 40
    detail = env.client.get(f"/tests/{apt['id']}", headers=org["headers"]).json()
    assert {q["section"] for q in detail["questions"]} == {"Quantitative Aptitude", "Logical Reasoning", "Verbal Ability", "Data Interpretation"}
    assert {q["question_type"] for q in detail["questions"]} == {"single", "multiple"}
    assert detail["total_marks"] == 43


def test_every_set_of_the_sample_scores_full_marks_with_the_answer_key(env):
    org = env.make_org()
    env.client.post("/tests/samples", headers=org["headers"])
    apt = next(t for t in env.client.get("/tests", headers=org["headers"]).json()["items"] if "OMR" in t["title"])
    seen = {}
    for _ in range(3):
        c = env.candidate(apt["code"])
        letter = c["state"]["paper_set"]
        seen[letter] = [q["id"] for q in c["state"]["questions"]]
        answers = env.answer_all_correctly(org, apt, c)
        done = env.client.post("/attempt/submit", headers=c["headers"], json={"answers": answers}).json()
        assert done["percentage"] == 100 and done["score"] == 43, letter
        sheet_pdf = env.client.get(f"/attempts/{c['attempt_id']}/omr.pdf?evaluated=true", headers=org["headers"])
        assert sheet_pdf.status_code == 200 and "43 / 43" in pdf_text(sheet_pdf.content).replace("43.0", "43")
    assert sorted(seen) == ["A", "B", "C"] and len({tuple(v) for v in seen.values()}) == 3
    # sections stay in their original order in every set
    detail = env.client.get(f"/tests/{apt['id']}", headers=org["headers"]).json()
    section_of = {q["id"]: q["section"] for q in detail["questions"]}
    order = ["Quantitative Aptitude", "Logical Reasoning", "Verbal Ability", "Data Interpretation"]
    for ids in seen.values():
        idx = [order.index(section_of[i]) for i in ids]
        assert idx == sorted(idx)


def test_sample_answers_are_internally_consistent():
    for q in sample_tests.APTITUDE_OMR_QUESTIONS:
        assert q["marks"] in (1, 2) and (q["question_type"] == "multiple") == (q["marks"] == 2)
        assert len(set(o.lower() for o in q["options"])) == len(q["options"]) and q["explanation"]
        assert all(0 <= i < len(q["options"]) for i in q["correct"])
