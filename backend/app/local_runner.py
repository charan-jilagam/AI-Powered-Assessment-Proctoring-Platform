"""
Docker-free code runner: executes candidate code as a subprocess on the machine
that runs the backend. Enable with  CODE_RUNNER=local  (see README).

!! THIS IS NOT A SANDBOX !!
Candidate code runs with the same OS user and file access as the backend. We
reduce the blast radius (empty environment so secrets in env vars are not
inherited, throw-away working directory, wall-clock timeout, output cap and, on
Linux/macOS, CPU / memory / file-size limits) but a determined candidate can still
read files, use the network or fork-bomb. Use it for development, demos and
trusted/low-stakes practice. For real exams use Judge0 (CODE_RUNNER=judge0) or
run the backend inside a locked-down container/VM.

It returns the same raw result dicts as judge0.execute(), so the grading code in
judge0.py / coding.py is shared and unchanged.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Dict, List, Optional

IS_WINDOWS = os.name == "nt"
MAX_OUTPUT_BYTES = 1_000_000     # stdout/stderr kept per run
COMPILE_TIMEOUT_SECONDS = 30
STARTUP_ALLOWANCE = {71: 0.5, 63: 0.5, 50: 0.5, 54: 0.5, 62: 1.5}  # interpreter / JVM start-up

# Judge0 status ids reused so verdict mapping stays identical
ACCEPTED, TLE, COMPILE_ERROR, RUNTIME_ERROR, INTERNAL_ERROR = 3, 5, 6, 11, 13
_STATUS_TEXT = {3: "Accepted", 5: "Time Limit Exceeded", 6: "Compilation Error",
                11: "Runtime Error (NZEC)", 13: "Internal Error"}


def _tool(*names: str) -> Optional[str]:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def _toolchains() -> Dict[int, dict]:
    """language_id -> how to build/run it, only for toolchains installed on this machine."""
    chains: Dict[int, dict] = {
        71: {"name": f"Python ({sys.version.split()[0]})", "file": "main.py",
             "run": [sys.executable, "-u", "main.py"]},
    }
    node = _tool("node", "nodejs")
    if node:
        chains[63] = {"name": "JavaScript (Node.js)", "file": "main.js", "run": [node, "main.js"]}
    gcc = _tool("gcc")
    if gcc:
        chains[50] = {"name": "C (GCC)", "file": "main.c", "build": [gcc, "main.c", "-O2", "-o", "main", "-lm"],
                      "run": [os.path.join(".", "main")]}
    gpp = _tool("g++")
    if gpp:
        chains[54] = {"name": "C++ (GCC)", "file": "main.cpp",
                      "build": [gpp, "main.cpp", "-O2", "-std=c++17", "-o", "main"],
                      "run": [os.path.join(".", "main")]}
    javac, java = _tool("javac"), _tool("java")
    if javac and java:
        chains[62] = {"name": "Java (class must be Main)", "file": "Main.java", "build": [javac, "Main.java"],
                      "run": [java, "-Xshare:auto", "Main"]}
    if IS_WINDOWS:  # MinGW gcc/g++ append .exe to the output name
        for lid in (50, 54):
            if lid in chains:
                chains[lid]["run"] = [os.path.join(".", "main.exe")]
    return chains


def available_languages() -> Dict[int, str]:
    return {lid: spec["name"] for lid, spec in _toolchains().items()}


def _clean_env() -> Dict[str, str]:
    """Do NOT hand the backend's environment (SECRET_KEY, DATABASE_URL, ...) to candidate code."""
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    for key in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "LANG", "LC_ALL", "JAVA_HOME"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _limits(cpu_seconds: float, memory_mb: int, language_id: int):
    """POSIX-only resource limits applied in the child before exec. None on Windows."""
    if IS_WINDOWS:
        return None
    import resource

    def apply():
        os.setsid()
        resource.setrlimit(resource.RLIMIT_CPU, (int(cpu_seconds) + 2, int(cpu_seconds) + 3))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if language_id in (71, 50, 54):  # JVM / V8 reserve huge virtual ranges, so address-space caps break them
            limit = int(memory_mb) * 1024 * 1024 + 64 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    return apply


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _read_capped(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return fh.read(MAX_OUTPUT_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _result(status_id: int, stdout="", stderr="", compile_output="", message="", seconds=None) -> dict:
    return {"status_id": status_id, "status": _STATUS_TEXT.get(status_id, "Internal Error"),
            "stdout": stdout, "stderr": stderr, "compile_output": compile_output,
            "message": message, "time": seconds, "memory": None}


def _run_once(spec: dict, workdir: str, stdin: str, language_id: int,
              time_limit: float, memory_mb: int) -> dict:
    out_path, err_path = os.path.join(workdir, ".stdout"), os.path.join(workdir, ".stderr")
    timeout = time_limit + STARTUP_ALLOWANCE.get(language_id, 0.5)
    started = time.perf_counter()
    with open(out_path, "wb") as out, open(err_path, "wb") as err:
        try:
            proc = subprocess.Popen(
                spec["run"], cwd=workdir, env=_clean_env(), stdin=subprocess.PIPE, stdout=out, stderr=err,
                preexec_fn=_limits(time_limit, memory_mb, language_id) if not IS_WINDOWS else None,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0,
            )
        except OSError as exc:
            return _result(INTERNAL_ERROR, message=f"Could not start the program: {exc}")
        try:
            proc.communicate(stdin.encode("utf-8"), timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.communicate()
            return _result(TLE, _read_capped(out_path), _read_capped(err_path), seconds=round(timeout, 3))
        except (BrokenPipeError, OSError):
            proc.wait()  # program exited without reading all of its input; that's fine
    seconds = round(time.perf_counter() - started, 3)
    stdout, stderr = _read_capped(out_path), _read_capped(err_path)
    if proc.returncode != 0:
        return _result(RUNTIME_ERROR, stdout, stderr, message=f"Exited with code {proc.returncode}", seconds=seconds)
    return _result(ACCEPTED, stdout, stderr, seconds=seconds)


def execute(source_code: str, language_id: int, stdins: List[str],
            time_limit_seconds: float = 2.0, memory_limit_mb: int = 256) -> List[dict]:
    """Same contract as judge0.execute(): one raw result per stdin, in order."""
    if not stdins:
        return []
    spec = _toolchains().get(language_id)
    if spec is None:
        return [_result(INTERNAL_ERROR, message="This language is not installed on the server")] * len(stdins)

    workdir = tempfile.mkdtemp(prefix="proctor-run-")
    try:
        with open(os.path.join(workdir, spec["file"]), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(source_code)

        if "build" in spec:
            try:
                build = subprocess.run(spec["build"], cwd=workdir, env=_clean_env(), capture_output=True,
                                       timeout=COMPILE_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                bad = _result(COMPILE_ERROR, compile_output="Compilation timed out")
                return [bad] * len(stdins)
            if build.returncode != 0:
                text = (build.stderr or build.stdout).decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
                return [_result(COMPILE_ERROR, compile_output=text)] * len(stdins)

        return [_run_once(spec, workdir, stdin, language_id, float(time_limit_seconds), int(memory_limit_mb))
                for stdin in stdins]
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
