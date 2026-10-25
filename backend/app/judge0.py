"""
Thin client for the Judge0 CE REST API (https://ce.judge0.com/).

The backend is the ONLY thing that talks to Judge0. Judge0 is not published to
the host or the internet in docker-compose.yml, so candidates cannot reach it
directly, and they never see hidden test cases or expected outputs.

Design notes
- Each test case is sent as its own Judge0 submission (batched, 20 per request),
  with the test input as stdin.
- We do NOT send `expected_output` to Judge0. We compare stdout ourselves so the
  comparison rules live in one place and expected output never leaves our DB.
- Source code / stdin / stdout travel base64-encoded (`base64_encoded=true`) so
  non-UTF8 output cannot break the JSON response.
"""
import base64
import json
import os
import time
from typing import Dict, List, Optional

import httpx

# Which engine runs candidate code:
#   "judge0" - a Judge0 server (JUDGE0_URL): sandboxed, the right choice for real exams
#   "local"  - subprocesses on this machine (see local_runner.py): no extra service, NOT a full sandbox
#   "auto"   - (default) judge0 when JUDGE0_URL is set, otherwise local
CODE_RUNNER = os.getenv("CODE_RUNNER", "auto").strip().lower()
JUDGE0_URL = os.getenv("JUDGE0_URL", "").strip().rstrip("/")
if CODE_RUNNER == "auto":
    CODE_RUNNER = "judge0" if JUDGE0_URL else "local"
JUDGE0_URL = JUDGE0_URL or "http://judge0-server:2358"
# Optional: only needed if you enable AUTHN_HEADER / AUTHN_TOKEN in judge0.conf
JUDGE0_AUTH_HEADER = os.getenv("JUDGE0_AUTH_HEADER", "X-Auth-Token")
JUDGE0_AUTH_TOKEN = os.getenv("JUDGE0_AUTH_TOKEN", "")
# Extra request headers as JSON, e.g. a hosted Judge0 on RapidAPI:
#   {"X-RapidAPI-Key": "...", "X-RapidAPI-Host": "judge0-ce.p.rapidapi.com"}
JUDGE0_EXTRA_HEADERS_RAW = os.getenv("JUDGE0_EXTRA_HEADERS", "")
# Ask the Judge0 server which languages it has (so the editor offers exactly those). Falls back to the table below.
JUDGE0_FETCH_LANGUAGES = os.getenv("JUDGE0_FETCH_LANGUAGES", "true").strip().lower() in {"1", "true", "yes", "on"}

BATCH_SIZE = 20            # Judge0's default MAX_SUBMISSION_BATCH_SIZE
POLL_INTERVAL_SECONDS = 0.5
POLL_TIMEOUT_SECONDS = 60  # give up waiting for a batch after this long
HTTP_TIMEOUT_SECONDS = 15
MAX_OUTPUT_CHARS = 2000    # what we hand back to the browser
KB_PER_MB = 1000           # Judge0 takes KB and documents 256000 KB as its max, so 256 MB -> 256000

# Every runnable language of Judge0 CE (1.13.x). IDs are Judge0's; the live /languages list of your server wins when
# it can be fetched (see get_languages). Not offered: 43 Plain Text, 44 Executable, 89 Multi-file program.
SUPPORTED_LANGUAGES: Dict[int, str] = {
    100: "Python (3.12.5)", 92: "Python (3.11.2)", 71: "Python (3.8.1)", 70: "Python (2.7.17)",
    54: "C++ (GCC 9.2.0)", 53: "C++ (GCC 8.3.0)", 52: "C++ (GCC 7.4.0)", 76: "C++ (Clang 7.0.1)",
    50: "C (GCC 9.2.0)", 49: "C (GCC 8.3.0)", 48: "C (GCC 7.4.0)", 75: "C (Clang 7.0.1)",
    91: "Java (JDK 17.0.6)", 62: "Java (OpenJDK 13.0.1)", 96: "JavaFX (JDK 17.0.6)",
    102: "JavaScript (Node.js 22.08.0)", 97: "JavaScript (Node.js 20.17.0)", 93: "JavaScript (Node.js 18.15.0)", 63: "JavaScript (Node.js 12.14.0)",
    101: "TypeScript (5.6.2)", 94: "TypeScript (5.0.3)", 74: "TypeScript (3.7.4)",
    51: "C# (Mono 6.6.0.161)", 87: "F# (.NET Core SDK 3.1.202)", 84: "Visual Basic.Net (vbnc 0.0.0.5943)",
    95: "Go (1.18.5)", 60: "Go (1.13.5)",
    73: "Rust (1.40.0)", 78: "Kotlin (1.3.70)", 81: "Scala (2.13.2)", 83: "Swift (5.2.3)", 90: "Dart (2.19.2)",
    72: "Ruby (2.7.0)", 98: "PHP (8.3.11)", 68: "PHP (7.4.1)", 85: "Perl (5.28.1)", 64: "Lua (5.3.5)", 46: "Bash (5.0.0)",
    99: "R (4.4.1)", 80: "R (4.0.0)", 66: "Octave (5.1.0)",
    61: "Haskell (GHC 8.8.1)", 65: "OCaml (4.09.0)", 55: "Common Lisp (SBCL 2.0.0)", 86: "Clojure (1.10.1)", 88: "Groovy (3.0.3)",
    57: "Elixir (1.9.4)", 58: "Erlang (OTP 22.2)",
    59: "Fortran (GFortran 9.2.0)", 67: "Pascal (FPC 3.0.4)", 77: "COBOL (GnuCOBOL 2.2)", 56: "D (DMD 2.089.1)",
    45: "Assembly (NASM 2.14.02)", 47: "Basic (FBC 1.07.1)", 69: "Prolog (GNU Prolog 1.4.5)", 79: "Objective-C (Clang 7.0.1)",
    82: "SQL (SQLite 3.27.2)",
}
NOT_OFFERED_IDS = {43, 44, 89}

if CODE_RUNNER == "local":  # only offer languages that are actually installed on this machine
    from app import local_runner as _local_runner
    SUPPORTED_LANGUAGES = _local_runner.available_languages()

# Language "families" let the editor pick starter code and syntax hints without knowing every Judge0 id.
_FAMILIES = [
    ("typescript", "typescript"), ("javascript", "javascript"), ("node", "javascript"), ("c++", "cpp"), ("objective-c", "objc"),
    ("c#", "csharp"), ("f#", "fsharp"), ("visual basic", "vb"), ("javafx", "java"), ("java", "java"), ("python", "python"),
    ("kotlin", "kotlin"), ("scala", "scala"), ("swift", "swift"), ("dart", "dart"), ("golang", "go"), ("go ", "go"), ("rust", "rust"),
    ("ruby", "ruby"), ("php", "php"), ("perl", "perl"), ("lua", "lua"), ("bash", "bash"), ("octave", "octave"), ("haskell", "haskell"),
    ("ocaml", "ocaml"), ("lisp", "lisp"), ("clojure", "clojure"), ("groovy", "groovy"), ("elixir", "elixir"), ("erlang", "erlang"),
    ("fortran", "fortran"), ("pascal", "pascal"), ("cobol", "cobol"), ("assembly", "asm"), ("basic", "basic"), ("prolog", "prolog"),
    ("sql", "sql"), ("c (", "c"), ("r (", "r"), ("d (", "d"),
]


def family_of(name: str) -> str:
    low = (name or "").lower()
    if low.startswith("go"):
        return "go"
    for needle, fam in _FAMILIES:
        if needle in low:
            return fam
    return "text"


_lang_cache: Dict[str, object] = {"at": 0.0, "value": None}
LANG_CACHE_SECONDS = 600


def get_languages() -> Dict[int, str]:
    """id -> display name of every language candidates may use right now."""
    if CODE_RUNNER == "local" or not JUDGE0_FETCH_LANGUAGES:
        return dict(SUPPORTED_LANGUAGES)
    now = time.monotonic()
    cached = _lang_cache["value"]
    if cached is not None and now - float(_lang_cache["at"]) < LANG_CACHE_SECONDS:
        return dict(cached)  # type: ignore[arg-type]
    try:
        response = httpx.get(f"{JUDGE0_URL}/languages", headers=_headers(), timeout=5)
        response.raise_for_status()
        live = {int(item["id"]): str(item["name"]) for item in response.json() if int(item["id"]) not in NOT_OFFERED_IDS}
        if not live:
            raise ValueError("empty language list")
        value = dict(sorted(live.items(), key=lambda kv: kv[1].lower()))
        # keep our friendlier ordering for well-known ids, then append anything new the server has
        ordered = {lid: value[lid] for lid in SUPPORTED_LANGUAGES if lid in value}
        ordered.update({lid: name for lid, name in value.items() if lid not in ordered})
        value = ordered
    except Exception:  # noqa: BLE001 - Judge0 down or not reachable: offer the static list, retry in a minute
        value = dict(SUPPORTED_LANGUAGES)
        _lang_cache.update(at=now - LANG_CACHE_SECONDS + 60, value=value)
        return dict(value)
    _lang_cache.update(at=now, value=value)
    return dict(value)


def language_name(language_id: int) -> str:
    return get_languages().get(language_id) or SUPPORTED_LANGUAGES.get(language_id) or str(language_id)

# Judge0 status ids -> our verdict names (ids 1 and 2 mean "still running")
STATUS_ACCEPTED = 3
STATUS_WRONG_ANSWER = 4   # we never send expected_output, so Judge0 shouldn't emit this; treated as "ran fine"
STATUS_TLE = 5
STATUS_COMPILE_ERROR = 6
_RUNTIME_ERROR_IDS = {7, 8, 9, 10, 11, 12}
_STILL_RUNNING_IDS = {1, 2}


class Judge0Error(Exception):
    """Judge0 is unreachable, timed out, or returned something unusable."""


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def _b64e(text: str) -> str:
    return base64.b64encode((text or "").encode("utf-8")).decode("ascii")


def _b64d(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return base64.b64decode(value).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if JUDGE0_AUTH_TOKEN:
        headers[JUDGE0_AUTH_HEADER] = JUDGE0_AUTH_TOKEN
    if JUDGE0_EXTRA_HEADERS_RAW:
        try:
            extra = json.loads(JUDGE0_EXTRA_HEADERS_RAW)
            headers.update({str(k): str(v) for k, v in extra.items()})
        except (ValueError, AttributeError):
            pass  # a malformed JUDGE0_EXTRA_HEADERS must not break code execution; the Judge0 server will say 401/403 if it matters
    return headers


def normalize_output(text: str) -> str:
    """Ignore \\r\\n vs \\n, trailing spaces on a line, and trailing blank lines."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.rstrip() for line in lines]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def outputs_match(actual: str, expected: str) -> bool:
    return normalize_output(actual) == normalize_output(expected)


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "\n... [output truncated]"


# ----------------------------------------------------------------------------
# raw execution
# ----------------------------------------------------------------------------
def _submission_payload(source_code: str, language_id: int, stdin: str,
                        time_limit_seconds: float, memory_limit_mb: int) -> dict:
    cpu = max(0.5, float(time_limit_seconds))
    return {
        "source_code": _b64e(source_code),
        "language_id": language_id,
        "stdin": _b64e(stdin),
        "cpu_time_limit": cpu,
        # wall time must be >= 1s (Judge0 >= 1.13); allow headroom for JVM start-up
        "wall_time_limit": min(20.0, max(1.0, cpu * 2 + 1)),
        "memory_limit": int(memory_limit_mb) * KB_PER_MB,
    }


def execute(source_code: str, language_id: int, stdins: List[str],
            time_limit_seconds: float = 2.0, memory_limit_mb: int = 256,
            client: Optional[httpx.Client] = None) -> List[dict]:
    """
    Run `source_code` once per entry in `stdins` and return one raw result dict
    per stdin, in order: {status_id, status, stdout, stderr, compile_output,
    message, time, memory}. Raises Judge0Error if the service is unavailable.
    """
    if not stdins:
        return []

    if CODE_RUNNER == "local":  # Docker-free mode, see local_runner.py (NOT a sandbox)
        from app import local_runner
        return local_runner.execute(source_code, language_id, stdins, time_limit_seconds, memory_limit_mb)

    own_client = client is None
    http = client or httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
    results: List[dict] = []
    try:
        for start in range(0, len(stdins), BATCH_SIZE):
            chunk = stdins[start:start + BATCH_SIZE]
            payload = {"submissions": [
                _submission_payload(source_code, language_id, s, time_limit_seconds, memory_limit_mb)
                for s in chunk
            ]}
            created = http.post(
                f"{JUDGE0_URL}/submissions/batch",
                params={"base64_encoded": "true"},
                json=payload,
                headers=_headers(),
            )
            created.raise_for_status()
            items = created.json()
            if not isinstance(items, list) or len(items) != len(chunk):
                raise Judge0Error("Judge0 returned an unexpected response to the batch request")
            rejected = [item for item in items if not isinstance(item, dict) or "token" not in item]
            if rejected:
                raise Judge0Error(f"Judge0 rejected the submission: {rejected[0]}")
            tokens = [item["token"] for item in items]
            results.extend(_poll(http, tokens))
    except Judge0Error:
        raise
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise Judge0Error(f"Code execution service error: {exc}") from exc
    finally:
        if own_client:
            http.close()
    return results


def _poll(http: httpx.Client, tokens: List[str]) -> List[dict]:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while True:
        response = http.get(
            f"{JUDGE0_URL}/submissions/batch",
            # no `fields`: Judge0's default set already is stdout,time,memory,stderr,token,compile_output,message,status
            params={"tokens": ",".join(tokens), "base64_encoded": "true"},
            headers=_headers(),
        )
        response.raise_for_status()
        by_token = {item["token"]: item for item in response.json()["submissions"]}
        items = [by_token.get(t) for t in tokens]
        if all(item is not None and _status_id(item) not in _STILL_RUNNING_IDS for item in items):
            return [_clean(item) for item in items]
        if time.monotonic() > deadline:
            raise Judge0Error("Timed out waiting for the code execution service")
        time.sleep(POLL_INTERVAL_SECONDS)


def _status_id(item: dict) -> Optional[int]:
    status = item.get("status")
    return status.get("id") if isinstance(status, dict) else None


def _clean(item: dict) -> dict:
    status = item.get("status") or {}
    try:
        seconds = float(item["time"]) if item.get("time") is not None else None
    except (TypeError, ValueError):
        seconds = None
    return {
        "status_id": _status_id(item),
        "status": status.get("description") if isinstance(status, dict) else str(status),
        "stdout": _b64d(item.get("stdout")),
        "stderr": _b64d(item.get("stderr")),
        "compile_output": _b64d(item.get("compile_output")),
        "message": _b64d(item.get("message")),
        "time": seconds,
        "memory": item.get("memory"),
    }


# ----------------------------------------------------------------------------
# judging
# ----------------------------------------------------------------------------
def verdict_for(raw: dict, expected_output: Optional[str]) -> str:
    """Turn one raw Judge0 result into a human-readable verdict."""
    status_id = raw["status_id"]
    if status_id == STATUS_COMPILE_ERROR:
        return "Compilation Error"
    if status_id == STATUS_TLE:
        return "Time Limit Exceeded"
    if status_id in _RUNTIME_ERROR_IDS:
        return "Runtime Error"
    if status_id in (STATUS_ACCEPTED, STATUS_WRONG_ANSWER):
        if expected_output is None:
            return "Ran Successfully"
        return "Accepted" if outputs_match(raw["stdout"], expected_output) else "Wrong Answer"
    # 13 = Internal Error, 14 = Exec Format Error, anything unexpected
    return raw.get("status") or "Internal Error"


def judge(source_code: str, language_id: int, cases: List[dict],
          time_limit_seconds: float, memory_limit_mb: int,
          client: Optional[httpx.Client] = None) -> dict:
    """
    Judge `source_code` against `cases` (each: {input, expected, is_sample}).

    Returns {verdict, passed, total, compile_output, cases: [...]}. For hidden
    cases the per-case entry contains NO input/expected/actual output.
    """
    raws = execute(source_code, language_id, [c["input"] for c in cases],
                   time_limit_seconds, memory_limit_mb, client=client)

    out_cases = []
    passed = 0
    compile_output = ""
    first_failure: Optional[str] = None
    sample_no = hidden_no = 0

    for case, raw in zip(cases, raws):
        verdict = verdict_for(raw, case["expected"])
        ok = verdict == "Accepted"
        passed += 1 if ok else 0
        if not ok and first_failure is None:
            first_failure = verdict
        if verdict == "Compilation Error" and not compile_output:
            compile_output = _clip(raw["compile_output"])

        if case["is_sample"]:
            sample_no += 1
            label = f"Sample {sample_no}"
        else:
            hidden_no += 1
            label = f"Hidden {hidden_no}"

        entry = {
            "label": label,
            "is_sample": bool(case["is_sample"]),
            "passed": ok,
            "verdict": verdict,
            "time": raw["time"],
            "memory_kb": raw["memory"],
        }
        if case["is_sample"]:  # samples are public, so show full detail
            entry.update({
                "input": _clip(case["input"]),
                "expected_output": _clip(case["expected"]),
                "actual_output": _clip(raw["stdout"]),
                "stderr": _clip(raw["stderr"] or raw["message"]),
            })
        out_cases.append(entry)

    total = len(cases)
    if any(c["verdict"] == "Compilation Error" for c in out_cases):
        overall = "Compilation Error"
    elif passed == total and total > 0:
        overall = "Accepted"
    else:
        overall = first_failure or "Wrong Answer"

    return {
        "verdict": overall,
        "passed": passed,
        "total": total,
        "compile_output": compile_output,
        "cases": out_cases,
    }


def run_custom(source_code: str, language_id: int, stdin: str,
               time_limit_seconds: float, memory_limit_mb: int,
               client: Optional[httpx.Client] = None) -> dict:
    """Run once against arbitrary stdin (the 'custom input' box). Not graded."""
    raw = execute(source_code, language_id, [stdin], time_limit_seconds, memory_limit_mb,
                  client=client)[0]
    return {
        "verdict": verdict_for(raw, None),
        "stdout": _clip(raw["stdout"]),
        "stderr": _clip(raw["stderr"] or raw["message"]),
        "compile_output": _clip(raw["compile_output"]),
        "time": raw["time"],
        "memory_kb": raw["memory"],
    }
