"""Tests for the Docker-free local runner (CODE_RUNNER=local). Uses the real interpreters/compilers on this machine."""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app import judge0, local_runner

PY = 71
CASES = [
    {"input": "3 4\n", "expected": "7\n", "is_sample": True},
    {"input": "-5 -7\n", "expected": "-12\n", "is_sample": False},
]
SUM_PY = "a, b = map(int, input().split())\nprint(a + b)\n"


@pytest.fixture(autouse=True)
def local_mode(monkeypatch):
    monkeypatch.setattr(judge0, "CODE_RUNNER", "local")


def test_python_accepted_through_the_shared_judge():
    out = judge0.judge(SUM_PY, PY, CASES, 2.0, 256)
    assert out["verdict"] == "Accepted" and out["passed"] == 2 and out["total"] == 2
    hidden = out["cases"][1]
    assert "input" not in hidden and "expected_output" not in hidden  # hidden tests stay hidden


def test_wrong_answer():
    out = judge0.judge("print(0)", PY, CASES, 2.0, 256)
    assert out["verdict"] == "Wrong Answer" and out["passed"] == 0


def test_runtime_error_has_stderr_and_verdict():
    out = judge0.run_custom("raise ValueError('boom')", PY, "", 2.0, 256)
    assert out["verdict"] == "Runtime Error"
    assert "boom" in out["stderr"]


def test_infinite_loop_is_time_limited():
    out = judge0.run_custom("while True:\n    pass\n", PY, "", 1.0, 256)
    assert out["verdict"] == "Time Limit Exceeded"


def test_candidate_cannot_see_backend_secrets(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "super-secret-value")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db/x")
    code = "import os\nprint(os.environ.get('SECRET_KEY'), os.environ.get('DATABASE_URL'))\n"
    out = judge0.run_custom(code, PY, "", 2.0, 256)
    assert out["stdout"].strip() == "None None"


def test_program_that_ignores_stdin_is_fine():
    out = judge0.run_custom("print('hi')", PY, "x" * 500_000 + "\n", 2.0, 256)
    assert out["verdict"] == "Ran Successfully" and out["stdout"].strip() == "hi"


def test_huge_output_is_capped():
    out = local_runner.execute("print('a' * 5_000_000)", PY, [""], 2.0, 256)[0]
    assert len(out["stdout"]) <= local_runner.MAX_OUTPUT_BYTES


def test_working_directory_is_removed_afterwards(monkeypatch):
    seen = []
    real = local_runner.tempfile.mkdtemp
    monkeypatch.setattr(local_runner.tempfile, "mkdtemp", lambda **kw: seen.append(real(**kw)) or seen[-1])
    judge0.run_custom("print(1)", PY, "", 2.0, 256)
    assert seen and not os.path.exists(seen[0])


def test_only_installed_languages_are_offered():
    langs = local_runner.available_languages()
    assert PY in langs
    assert (54 in langs) == bool(shutil.which("g++"))


def test_unknown_language_reports_internal_error_not_crash():
    out = local_runner.execute("x", 999, ["", ""], 1.0, 64)
    assert [r["status_id"] for r in out] == [13, 13]


@pytest.mark.skipif(not shutil.which("g++"), reason="g++ not installed")
def test_cpp_compile_error_and_success():
    bad = judge0.judge("int main( {", 54, CASES, 10.0, 256)
    assert bad["verdict"] == "Compilation Error" and bad["compile_output"]
    good = judge0.judge("#include <iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a+b<<'\\n';}", 54, CASES, 10.0, 256)
    assert good["verdict"] == "Accepted"


@pytest.mark.skipif(not (shutil.which("javac") and shutil.which("java")), reason="JDK not installed")
def test_java_main_class():
    code = "import java.util.*;\npublic class Main { public static void main(String[] a){ Scanner s=new Scanner(System.in); System.out.println(s.nextInt()+s.nextInt()); } }"
    assert judge0.judge(code, 62, CASES, 10.0, 256)["verdict"] == "Accepted"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_node():
    code = "const [a,b]=require('fs').readFileSync(0,'utf8').trim().split(/\\s+/).map(Number);console.log(a+b)"
    assert judge0.judge(code, 63, CASES, 10.0, 256)["verdict"] == "Accepted"


# ---------------------------------------------------------------- more languages (each runs only where its toolchain is installed)
SUM_PROGRAMS = {
    63: "const [a,b]=require('fs').readFileSync(0,'utf8').trim().split(/\\s+/).map(Number);console.log(a+b)",
    74: "const [a, b]: number[] = require('fs').readFileSync(0, 'utf8').trim().split(/\\s+/).map(Number);\nconsole.log(a + b)",
    60: 'package main\nimport "fmt"\nfunc main(){var a,b int;fmt.Scan(&a,&b);fmt.Println(a+b)}',
    72: "a,b=gets.split.map(&:to_i);puts a+b",
    68: "<?php fscanf(STDIN,'%d %d',$a,$b);echo $a+$b,\"\\n\";",
    85: 'my ($a,$b)=split " ",<STDIN>;print $a+$b,"\\n";',
    46: "read a b; echo $((a+b))",
    50: '#include <stdio.h>\nint main(){int a,b;scanf("%d %d",&a,&b);printf("%d\\n",a+b);return 0;}',
    54: '#include <iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}',
    62: "import java.util.*;public class Main{public static void main(String[] x){Scanner s=new Scanner(System.in);System.out.println(s.nextInt()+s.nextInt());}}",
}


@pytest.mark.parametrize("lid", sorted(SUM_PROGRAMS))
def test_each_installed_language_runs_and_judges(lid):
    if lid not in local_runner.available_languages():
        pytest.skip("toolchain not installed on this machine")
    out = judge0.judge(SUM_PROGRAMS[lid], lid, CASES, 3.0, 256)
    assert out["verdict"] == "Accepted", out
    judged_wrong = judge0.judge(SUM_PROGRAMS[lid], lid, [{"input": "1 1\n", "expected": "3\n", "is_sample": True}], 3.0, 256)
    assert judged_wrong["verdict"] == "Wrong Answer"


def test_compile_error_is_reported_for_compiled_languages():
    if 50 not in local_runner.available_languages():
        pytest.skip("gcc not installed")
    out = judge0.run_custom("int main( { return 0 }", 50, "", 2.0, 256)
    assert out["verdict"] == "Compilation Error" and out["compile_output"]


def test_unknown_language_is_an_internal_error_not_a_crash():
    out = judge0.run_custom("x", 9999, "", 2.0, 256)
    assert out["verdict"] == "Internal Error"


def test_work_dirs_are_not_listable_and_are_cleaned_up():
    import stat
    judge0.run_custom("print(1)", PY, "", 2.0, 256)
    assert not os.listdir(local_runner._RUN_ROOT)                      # nothing left behind
    assert stat.S_IMODE(os.stat(local_runner._RUN_ROOT).st_mode) == 0o711   # traverse-only: names cannot be listed


@pytest.mark.skipif(os.name == "nt" or os.geteuid() != 0, reason="needs root to switch users")
def test_candidate_code_runs_as_an_unprivileged_user_when_isolation_is_on(monkeypatch):
    monkeypatch.setattr(local_runner, "RUNNER_UID", 10002)
    monkeypatch.setattr(local_runner, "RUNNER_GID", 10002)
    local_runner.isolation_active.cache_clear()
    try:
        assert local_runner.isolation_active() is True
        code = f"import os\nprint(os.getuid())\ntry:\n    open('/proc/{os.getpid()}/environ','rb').read()\n    print('READ')\nexcept PermissionError:\n    print('denied')\n"
        out = judge0.run_custom(code, PY, "", 2.0, 256)
        assert out["stdout"].split() == ["10002", "denied"]
        assert judge0.judge(SUM_PY, PY, CASES, 2.0, 256)["verdict"] == "Accepted"
    finally:
        local_runner.isolation_active.cache_clear()
