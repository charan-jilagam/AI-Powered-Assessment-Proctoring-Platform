"""Unit tests for the Judge0 client. No real Judge0 needed: httpx.MockTransport plays its part."""
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import pytest

from app import judge0


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def result(status_id=3, description="Accepted", stdout="", stderr=None, compile_output=None):
    return {
        # like real Judge0 (default field set): the id lives inside `status`, there is no top-level status_id
        "status": {"id": status_id, "description": description},
        "stdout": b64(stdout) if stdout else None,
        "stderr": b64(stderr) if stderr else None,
        "compile_output": b64(compile_output) if compile_output else None,
        "message": None,
        "time": "0.012",
        "memory": 2048,
    }


class FakeJudge0:
    """Tiny in-memory Judge0: POST /submissions/batch -> tokens; GET polls 'processing' once, then results."""

    def __init__(self, outputs, processing_polls=1):
        self.outputs = outputs            # one result dict per submission, in creation order
        self.processing_polls = processing_polls
        self.posted = []                  # every submission payload received
        self.post_calls = 0
        self.polls = 0
        self.last_headers = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.last_headers = request.headers
        if request.method == "POST" and request.url.path == "/submissions/batch":
            assert request.url.params["base64_encoded"] == "true"
            body = json.loads(request.content)
            start = len(self.posted)
            self.posted.extend(body["submissions"])
            self.post_calls += 1
            return httpx.Response(201, json=[{"token": f"t{start + i}"} for i in range(len(body["submissions"]))])

        if request.method == "GET" and request.url.path == "/submissions/batch":
            self.polls += 1
            tokens = request.url.params["tokens"].split(",")
            items = []
            for token in tokens:
                item = dict(self.outputs[int(token[1:])])
                if self.polls <= self.processing_polls:
                    item = result(status_id=2, description="Processing")
                item["token"] = token
                items.append(item)
            return httpx.Response(200, json={"submissions": items})

        return httpx.Response(404)


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch):
    monkeypatch.setattr(judge0, "POLL_INTERVAL_SECONDS", 0)


def client_for(fake) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(fake))


# ---- transport -------------------------------------------------------------

def test_execute_sends_base64_stdin_limits_and_no_expected_output():
    fake = FakeJudge0([result(stdout="3\n")])
    out = judge0.execute("print(1+2)", 71, ["1 2\n"], 2.0, 256, client=client_for(fake))

    sent = fake.posted[0]
    assert base64.b64decode(sent["source_code"]).decode() == "print(1+2)"
    assert base64.b64decode(sent["stdin"]).decode() == "1 2\n"
    assert sent["language_id"] == 71
    assert sent["cpu_time_limit"] == 2.0
    assert sent["memory_limit"] == 256000              # Judge0 wants KB; 256000 is its documented max
    assert sent["wall_time_limit"] >= 1                # Judge0 >= 1.13 requirement
    assert "expected_output" not in sent               # expected output never leaves our DB
    assert out[0]["stdout"] == "3\n"
    assert out[0]["time"] == 0.012


def test_execute_polls_until_finished():
    fake = FakeJudge0([result(stdout="a"), result(stdout="b")], processing_polls=3)
    out = judge0.execute("x", 71, ["", ""], client=client_for(fake))
    assert fake.polls == 4
    assert [r["stdout"] for r in out] == ["a", "b"]


def test_execute_splits_large_batches_and_keeps_order():
    outputs = [result(stdout=str(i)) for i in range(45)]
    fake = FakeJudge0(outputs, processing_polls=0)
    out = judge0.execute("x", 71, [str(i) for i in range(45)], client=client_for(fake))
    assert fake.post_calls == 3                        # 20 + 20 + 5
    assert [r["stdout"] for r in out] == [str(i) for i in range(45)]


def test_http_error_becomes_judge0error():
    def broken(request):
        return httpx.Response(500, text="boom")
    with pytest.raises(judge0.Judge0Error):
        judge0.execute("x", 71, ["1"], client=client_for(broken))


def test_rejected_submission_in_batch_becomes_judge0error():
    def reject(request):
        return httpx.Response(201, json=[{"language_id": ["language with id 999 doesn't exist"]}])
    with pytest.raises(judge0.Judge0Error, match="rejected"):
        judge0.execute("x", 999, ["1"], client=client_for(reject))


def test_connection_error_becomes_judge0error():
    def refuse(request):
        raise httpx.ConnectError("refused")
    with pytest.raises(judge0.Judge0Error):
        judge0.execute("x", 71, ["1"], client=client_for(refuse))


def test_poll_timeout_becomes_judge0error(monkeypatch):
    monkeypatch.setattr(judge0, "POLL_TIMEOUT_SECONDS", 0)
    fake = FakeJudge0([result()], processing_polls=10_000)
    with pytest.raises(judge0.Judge0Error):
        judge0.execute("x", 71, ["1"], client=client_for(fake))


def test_auth_header_sent_when_configured(monkeypatch):
    monkeypatch.setattr(judge0, "JUDGE0_AUTH_TOKEN", "secret-token")
    monkeypatch.setattr(judge0, "JUDGE0_AUTH_HEADER", "X-Auth-Token")
    fake = FakeJudge0([result()], processing_polls=0)
    judge0.execute("x", 71, ["1"], client=client_for(fake))
    assert fake.last_headers["x-auth-token"] == "secret-token"


# ---- comparison + verdicts -------------------------------------------------

@pytest.mark.parametrize("actual,expected,ok", [
    ("3\n", "3", True),
    ("3", "3\n\n", True),
    ("a b  \r\nc\r\n", "a b\nc", True),          # CRLF + trailing spaces ignored
    ("1 2", "1  2", False),                       # inner whitespace still matters
    ("3", "4", False),
    ("", "x", False),
])
def test_outputs_match(actual, expected, ok):
    assert judge0.outputs_match(actual, expected) is ok


@pytest.mark.parametrize("status_id,desc,expected,verdict", [
    (3, "Accepted", "3", "Accepted"),
    (3, "Accepted", "4", "Wrong Answer"),
    (5, "Time Limit Exceeded", "3", "Time Limit Exceeded"),
    (6, "Compilation Error", "3", "Compilation Error"),
    (11, "Runtime Error (NZEC)", "3", "Runtime Error"),
    (7, "Runtime Error (SIGSEGV)", "3", "Runtime Error"),
    (13, "Internal Error", "3", "Internal Error"),
])
def test_verdict_mapping(status_id, desc, expected, verdict):
    raw = judge0._clean({**result(status_id, desc, stdout="3\n"), "token": "t"})
    assert raw["status_id"] == status_id
    assert judge0.verdict_for(raw, expected) == verdict


def test_judge_hides_hidden_case_details():
    cases = [
        {"input": "1 2\n", "expected": "3\n", "is_sample": True},
        {"input": "SECRET-INPUT\n", "expected": "SECRET-OUTPUT\n", "is_sample": False},
    ]
    fake = FakeJudge0([result(stdout="3\n"), result(stdout="SECRET-OUTPUT\n")], processing_polls=0)
    out = judge0.judge("x", 71, cases, 2.0, 256, client=client_for(fake))

    assert out["verdict"] == "Accepted" and out["passed"] == 2 and out["total"] == 2
    sample, hidden = out["cases"]
    assert sample["label"] == "Sample 1" and sample["input"] == "1 2\n"
    assert hidden["label"] == "Hidden 1" and hidden["passed"] is True
    assert not {"input", "expected_output", "actual_output", "stderr"} & hidden.keys()
    assert "SECRET" not in json.dumps(out)


def test_judge_compile_error_is_reported_once():
    cases = [{"input": "", "expected": "x", "is_sample": False}] * 3
    fake = FakeJudge0([result(6, "Compilation Error", compile_output="main.cpp:1: error")] * 3, processing_polls=0)
    out = judge0.judge("x", 54, cases, 2.0, 256, client=client_for(fake))
    assert out["verdict"] == "Compilation Error"
    assert out["passed"] == 0
    assert "error" in out["compile_output"]
