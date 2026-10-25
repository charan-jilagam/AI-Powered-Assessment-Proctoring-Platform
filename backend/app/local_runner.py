"""
Docker-free code runner: executes candidate code as a subprocess on the machine
that runs the backend. Enable with  CODE_RUNNER=local  (see README).

!! THIS IS NOT A FULL SANDBOX !!
What it does to limit the blast radius: an empty environment (secrets in env vars are not inherited), a throw-away
working directory that other runs cannot list, wall-clock timeout, output cap, CPU / memory / file-size limits and -
when RUNNER_UID is set and the process may switch users (the Docker image arranges this) - candidate code and compilers
run as a different, unprivileged OS user so they cannot read the backend's /proc/<pid>/environ, files or memory.
What it cannot do: block the network or cap a process's total memory/disk precisely. Use it for demos, trials and
low-stakes practice. For high-stakes exams use Judge0 (JUDGE0_URL) or run the backend inside a locked-down VM.

It returns the same raw result dicts as judge0.execute(), so the grading code in
judge0.py / coding.py is shared and unchanged.
"""
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from typing import Dict, List, Optional

log = logging.getLogger("orvexa.runner")

IS_WINDOWS = os.name == "nt"
MAX_OUTPUT_BYTES = 1_000_000     # stdout/stderr kept per run
COMPILE_TIMEOUT_SECONDS = 60
STARTUP_ALLOWANCE = {62: 1.5, 91: 1.5, 78: 2.5, 81: 2.5, 88: 2.0, 86: 2.0, 60: 0.5}  # JVM / big-runtime start-up; others get 0.5
DEFAULT_STARTUP = 0.5

# Judge0 status ids reused so verdict mapping stays identical
ACCEPTED, TLE, COMPILE_ERROR, RUNTIME_ERROR, INTERNAL_ERROR = 3, 5, 6, 11, 13
_STATUS_TEXT = {3: "Accepted", 5: "Time Limit Exceeded", 6: "Compilation Error",
                11: "Runtime Error (NZEC)", 13: "Internal Error"}

# Run candidate code as this unprivileged user when the process is allowed to switch (set by the Docker entrypoint).
RUNNER_UID = int(os.getenv("RUNNER_UID", "0") or 0)
RUNNER_GID = int(os.getenv("RUNNER_GID", str(RUNNER_UID)) or RUNNER_UID)
_RUN_ROOT = os.path.join(tempfile.gettempdir(), "orvexa-run")


def _tool(*names: str) -> Optional[str]:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def _node_can_strip_types(node: str) -> bool:
    try:
        out = subprocess.run([node, "--version"], capture_output=True, timeout=10).stdout.decode().strip().lstrip("v")
        major, minor = (int(x) for x in out.split(".")[:2])
        return (major, minor) >= (22, 6)
    except Exception:  # noqa: BLE001
        return False


@lru_cache(maxsize=1)
def _toolchains() -> Dict[int, dict]:
    """language_id -> how to build/run it, only for toolchains installed on this machine (Judge0's ids are reused)."""
    chains: Dict[int, dict] = {}

    def add(lid: int, name: str, file: str, run: List[str], build: Optional[List[List[str]]] = None, env: Optional[dict] = None):
        chains[lid] = {"name": name, "file": file, "run": run, **({"build": build} if build else {}), **({"env": env} if env else {})}

    add(71, f"Python ({sys.version.split()[0]})", "main.py", [sys.executable, "-u", "main.py"])
    if (node := _tool("node", "nodejs")):
        add(63, "JavaScript (Node.js)", "main.js", [node, "main.js"])
        if _node_can_strip_types(node):
            add(74, "TypeScript (Node.js type stripping, no type check)", "main.ts", [node, "--experimental-strip-types", "--no-warnings", "main.ts"])
    if (gcc := _tool("gcc")):
        add(50, "C (GCC)", "main.c", ["./main"], [[gcc, "main.c", "-O2", "-o", "main", "-lm"]])
    if (gpp := _tool("g++")):
        add(54, "C++ (GCC, C++17)", "main.cpp", ["./main"], [[gpp, "main.cpp", "-O2", "-std=c++17", "-o", "main"]])
    javac, java = _tool("javac"), _tool("java")
    if javac and java:
        add(62, "Java (class must be Main)", "Main.java", [java, "-Xshare:auto", "Main"], [[javac, "Main.java"]])
        if (kotlinc := _tool("kotlinc")):
            add(78, "Kotlin", "main.kt", [java, "-jar", "main.jar"], [[kotlinc, "main.kt", "-include-runtime", "-d", "main.jar"]])
    if (go := _tool("go")):
        add(60, "Go", "main.go", ["./main"], [[go, "build", "-o", "main", "main.go"]],
            env={"GOFLAGS": "-buildvcs=false", "GOCACHE": "{work}/.gocache", "GOPATH": "{work}/.gopath", "GO111MODULE": "off", "CGO_ENABLED": "0"})
    if (rustc := _tool("rustc")):
        add(73, "Rust", "main.rs", ["./main"], [[rustc, "-O", "main.rs", "-o", "main"]])
    if (mcs := _tool("mcs")) and (mono := _tool("mono")):
        add(51, "C# (Mono)", "main.cs", [mono, "main.exe"], [[mcs, "main.cs", "-out:main.exe"]])
    if (ruby := _tool("ruby")):
        add(72, "Ruby", "main.rb", [ruby, "main.rb"])
    if (php := _tool("php", "php-cli")):
        add(68, "PHP", "main.php", [php, "main.php"])
    if (perl := _tool("perl")):
        add(85, "Perl", "main.pl", [perl, "main.pl"])
    if (lua := _tool("lua5.4", "lua5.3", "lua")):
        add(64, "Lua", "main.lua", [lua, "main.lua"])
    if (bash := _tool("bash")):
        add(46, "Bash", "main.sh", [bash, "main.sh"])
    if (rscript := _tool("Rscript")):
        add(80, "R", "main.R", [rscript, "main.R"])
    if (octave := _tool("octave-cli", "octave")):
        add(66, "Octave", "main.m", [octave, "--no-gui", "--quiet", "main.m"])
    if (ghc := _tool("ghc")):
        add(61, "Haskell (GHC)", "main.hs", ["./main"], [[ghc, "-O0", "main.hs", "-o", "main"]])
    if (ocamlopt := _tool("ocamlfind", "ocamlopt")):
        build = [ocamlopt, "ocamlopt", "main.ml", "-o", "main"] if os.path.basename(ocamlopt) == "ocamlfind" else [ocamlopt, "main.ml", "-o", "main"]
        add(65, "OCaml", "main.ml", ["./main"], [build])
    if (sbcl := _tool("sbcl")):
        add(55, "Common Lisp (SBCL)", "main.lisp", [sbcl, "--script", "main.lisp"])
    if (gfortran := _tool("gfortran")):
        add(59, "Fortran (GFortran)", "main.f90", ["./main"], [[gfortran, "main.f90", "-O2", "-o", "main"]])
    if (fpc := _tool("fpc")):
        add(67, "Pascal (Free Pascal)", "main.pas", ["./main"], [[fpc, "-O2", "-omain", "main.pas"]])
    if (cobc := _tool("cobc")):
        add(77, "COBOL (GnuCOBOL, free format)", "main.cob", ["./main"], [[cobc, "-x", "-free", "-o", "main", "main.cob"]])
    if (nasm := _tool("nasm")) and (ld := _tool("ld")):
        add(45, "Assembly (NASM x86-64, Linux)", "main.asm", ["./main"], [[nasm, "-f", "elf64", "main.asm", "-o", "main.o"], [ld, "main.o", "-o", "main"]])
    if (dc := _tool("ldc2", "dmd", "gdc")):
        build = [dc, "main.d", "-of=main"] if os.path.basename(dc) in ("ldc2", "dmd") else [dc, "main.d", "-o", "main"]
        add(56, "D", "main.d", ["./main"], [build])
    if (elixir := _tool("elixir")):
        add(57, "Elixir", "main.exs", [elixir, "main.exs"])
    if (escript := _tool("escript")):
        add(58, "Erlang (escript)", "main.erl", [escript, "main.erl"])
    if (sqlite := _tool("sqlite3")):
        add(82, "SQL (SQLite)", "main.sql", [sqlite, ":memory:", ".read main.sql"])
    if (swipl := _tool("swipl")):
        add(69, "Prolog (SWI-Prolog; define main/0)", "main.pl", [swipl, "-q", "-g", "main", "-t", "halt", "main.pl"])
    if (groovy := _tool("groovy")):
        add(88, "Groovy", "main.groovy", [groovy, "main.groovy"])
    if (dart := _tool("dart")):
        add(90, "Dart", "main.dart", [dart, "main.dart"])
    if (scala := _tool("scala")):
        add(81, "Scala", "main.scala", [scala, "main.scala"])
    if (swiftc := _tool("swiftc")):
        add(83, "Swift", "main.swift", ["./main"], [[swiftc, "-O", "main.swift", "-o", "main"]])
    if IS_WINDOWS:  # MinGW gcc/g++ append .exe to the output name
        for lid in (50, 54):
            if lid in chains:
                chains[lid]["run"] = [os.path.join(".", "main.exe")]
    return chains


def available_languages() -> Dict[int, str]:
    return {lid: spec["name"] for lid, spec in _toolchains().items()}


def _clean_env(extra: Optional[Dict[str, str]] = None, work: str = "") -> Dict[str, str]:
    """Do NOT hand the backend's environment (SECRET_KEY, MONGODB_URI, ...) to candidate code."""
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", "HOME": work or tempfile.gettempdir()}
    for key in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "LANG", "LC_ALL", "JAVA_HOME"):
        if key in os.environ:
            env[key] = os.environ[key]
    for key, value in (extra or {}).items():
        env[key] = value.replace("{work}", work)
    return env


@lru_cache(maxsize=1)
def isolation_active() -> bool:
    """True when candidate processes really run as a different unprivileged user (checked once, by trying it)."""
    if IS_WINDOWS or not RUNNER_UID:
        return False
    try:
        probe = subprocess.run(["id", "-u"], capture_output=True, timeout=10, preexec_fn=_drop_privileges)
        ok = probe.returncode == 0 and probe.stdout.decode().strip() == str(RUNNER_UID)
    except Exception as exc:  # noqa: BLE001 - not allowed to switch users here
        log.warning("code runner: cannot switch to uid %s (%s); running candidate code as the server's own user", RUNNER_UID, exc)
        return False
    if not ok:
        log.warning("code runner: user switch did not take effect; running candidate code as the server's own user")
    return ok


def _drop_privileges() -> None:
    os.setgroups([])
    os.setgid(RUNNER_GID)
    os.setuid(RUNNER_UID)


# Interpreters and C-family binaries cope with an address-space cap; JVM / Go / Haskell / V8 reserve huge virtual ranges and do not.
_AS_LIMITED = {71, 50, 54, 72, 68, 85, 64, 46, 59, 67, 77, 45, 80, 82}


def _limits(cpu_seconds: float, memory_mb: int, language_id: int, isolated: bool):
    """POSIX-only: switch user (when possible) and apply resource limits in the child before exec. None on Windows."""
    if IS_WINDOWS:
        return None
    import resource

    def apply():
        os.setsid()
        if isolated:
            _drop_privileges()
        resource.setrlimit(resource.RLIMIT_CPU, (int(cpu_seconds) + 2, int(cpu_seconds) + 3))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if isolated:  # a separate user, so this only counts the candidate's own processes: stops fork bombs
            resource.setrlimit(resource.RLIMIT_NPROC, (96, 96))
        if language_id in _AS_LIMITED:
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
              time_limit: float, memory_mb: int, isolated: bool) -> dict:
    out_path, err_path = os.path.join(workdir, ".stdout"), os.path.join(workdir, ".stderr")
    timeout = time_limit + STARTUP_ALLOWANCE.get(language_id, DEFAULT_STARTUP)
    started = time.perf_counter()
    with open(out_path, "wb") as out, open(err_path, "wb") as err:
        try:
            proc = subprocess.Popen(
                spec["run"], cwd=workdir, env=_clean_env(spec.get("env"), workdir), stdin=subprocess.PIPE, stdout=out, stderr=err,
                preexec_fn=_limits(time_limit, memory_mb, language_id, isolated) if not IS_WINDOWS else None,
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


def _new_workdir(isolated: bool) -> str:
    """A directory only this run can find: the parent is traverse-only (mode 711), so other runs cannot list its names."""
    os.makedirs(_RUN_ROOT, mode=0o711, exist_ok=True)
    try:
        os.chmod(_RUN_ROOT, 0o711)
    except OSError:
        pass
    workdir = tempfile.mkdtemp(prefix="run-", dir=_RUN_ROOT)
    if isolated:
        os.chmod(workdir, 0o777)  # the runner user must be able to write here (compiler output, scratch files)
    return workdir


def execute(source_code: str, language_id: int, stdins: List[str],
            time_limit_seconds: float = 2.0, memory_limit_mb: int = 256) -> List[dict]:
    """Same contract as judge0.execute(): one raw result per stdin, in order."""
    if not stdins:
        return []
    spec = _toolchains().get(language_id)
    if spec is None:
        return [_result(INTERNAL_ERROR, message="This language is not installed on the server")] * len(stdins)

    isolated = isolation_active()
    workdir = _new_workdir(isolated)
    try:
        path = os.path.join(workdir, spec["file"])
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(source_code)
        os.chmod(path, 0o644)

        for step in spec.get("build", []):
            try:
                build = subprocess.run(step, cwd=workdir, env=_clean_env(spec.get("env"), workdir), capture_output=True,
                                       timeout=COMPILE_TIMEOUT_SECONDS,
                                       preexec_fn=_limits(COMPILE_TIMEOUT_SECONDS, 1024, language_id=0, isolated=isolated) if not IS_WINDOWS else None)
            except subprocess.TimeoutExpired:
                return [_result(COMPILE_ERROR, compile_output="Compilation timed out")] * len(stdins)
            except OSError as exc:
                return [_result(INTERNAL_ERROR, message=f"Could not start the compiler: {exc}")] * len(stdins)
            if build.returncode != 0:
                text = (build.stderr or build.stdout).decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
                return [_result(COMPILE_ERROR, compile_output=text)] * len(stdins)

        return [_run_once(spec, workdir, stdin, language_id, float(time_limit_seconds), int(memory_limit_mb), isolated)
                for stdin in stdins]
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
