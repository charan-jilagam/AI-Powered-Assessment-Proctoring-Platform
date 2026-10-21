import { useEffect, useState } from "react";
import { apiCall } from "../utils/api";

// Starter code per Judge0 language id. Programs read stdin and print to stdout.
const TEMPLATES = {
  71: "import sys\n\n\ndef main():\n    data = sys.stdin.read().split()\n    # your code here\n\n\nmain()\n",
  54: "#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    ios::sync_with_stdio(false);\n    cin.tie(nullptr);\n    // your code here\n    return 0;\n}\n",
  50: "#include <stdio.h>\n\nint main(void) {\n    // your code here\n    return 0;\n}\n",
  62: "import java.util.*;\n\npublic class Main {\n    public static void main(String[] args) {\n        Scanner sc = new Scanner(System.in);\n        // your code here\n    }\n}\n",
  63: 'const lines = require("fs").readFileSync("/dev/stdin", "utf8").split("\\n");\n// your code here\n',
};

// Used only if GET /coding/languages fails
const FALLBACK_LANGUAGES = [
  { id: 71, name: "Python (3.8.1)" },
  { id: 54, name: "C++ (GCC 9.2.0)" },
  { id: 50, name: "C (GCC 9.2.0)" },
  { id: 62, name: "Java (OpenJDK 13.0.1)" },
  { id: 63, name: "JavaScript (Node.js 12.14.0)" },
];

const DEFAULT_LANGUAGE = 71;

function draftKey(examId, problemId) {
  return `proctorai-code-${examId}-${problemId}`;
}

// sessionStorage can throw (private mode, blocked storage) - it's only a convenience
function loadDraft(examId, problemId) {
  try {
    const raw = sessionStorage.getItem(draftKey(examId, problemId));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveDraft(examId, problemId, draft) {
  try {
    sessionStorage.setItem(draftKey(examId, problemId), JSON.stringify(draft));
  } catch {
    /* ignore */
  }
}

function CodingProblems({ examId, problems }) {
  const [languages, setLanguages] = useState(FALLBACK_LANGUAGES);
  const [activeId, setActiveId] = useState(problems[0]?.id);
  const [drafts, setDrafts] = useState({}); // problemId -> { languageId, code }
  const [results, setResults] = useState({}); // problemId -> result object from the API
  const [best, setBest] = useState({}); // problemId -> { passed, total, verdict }
  const [customInput, setCustomInput] = useState({});
  const [showCustom, setShowCustom] = useState({});
  const [busy, setBusy] = useState(""); // "" | "run" | "submit"
  const [error, setError] = useState("");

  // Languages + restore last submitted code / best result after a page refresh
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const langs = await apiCall("/coding/languages", "GET");
        if (!cancelled && langs.length) setLanguages(langs);
      } catch {
        /* fall back to the built-in list */
      }
      try {
        const progress = await apiCall(`/exams/${examId}/coding-progress`, "GET");
        if (cancelled) return;
        const restoredDrafts = {};
        const restoredBest = {};
        progress.forEach((p) => {
          restoredDrafts[p.problem_id] = { languageId: p.last_language_id, code: p.last_source_code };
          restoredBest[p.problem_id] = { passed: p.best_passed, total: p.best_total, verdict: p.best_verdict };
        });
        problems.forEach((p) => {
          const local = loadDraft(examId, p.id); // unsaved edits are newer than the last submit
          if (local) restoredDrafts[p.id] = local;
        });
        setDrafts((prev) => ({ ...restoredDrafts, ...prev }));
        setBest(restoredBest);
      } catch {
        /* nothing submitted yet */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [examId, problems]);

  const problem = problems.find((p) => p.id === activeId) || problems[0];
  if (!problem) return null;

  const draft = drafts[problem.id] || { languageId: DEFAULT_LANGUAGE, code: TEMPLATES[DEFAULT_LANGUAGE] };
  const result = results[problem.id];
  const bestForProblem = best[problem.id];

  function updateDraft(patch) {
    const next = { ...draft, ...patch };
    setDrafts((prev) => ({ ...prev, [problem.id]: next }));
    saveDraft(examId, problem.id, next);
  }

  function changeLanguage(newId) {
    const untouched = Object.values(TEMPLATES).includes(draft.code) || !draft.code.trim();
    updateDraft({ languageId: newId, code: untouched ? TEMPLATES[newId] || "" : draft.code });
  }

  function handleTab(e) {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const el = e.target;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    updateDraft({ code: draft.code.slice(0, start) + "    " + draft.code.slice(end) });
    requestAnimationFrame(() => {
      el.selectionStart = el.selectionEnd = start + 4;
    });
  }

  async function execute(kind) {
    setBusy(kind);
    setError("");
    try {
      const base = `/exams/${examId}/coding-problems/${problem.id}`;
      const body = { language_id: draft.languageId, source_code: draft.code };
      let data;
      if (kind === "submit") {
        data = await apiCall(`${base}/submit`, "POST", body);
        setBest((prev) => ({
          ...prev,
          [problem.id]: { passed: data.best_passed, total: data.best_total, verdict: data.verdict },
        }));
      } else {
        if (showCustom[problem.id]) body.custom_input = customInput[problem.id] || "";
        data = await apiCall(`${base}/run`, "POST", body);
      }
      setResults((prev) => ({ ...prev, [problem.id]: { kind, ...data } }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  return (
    <div style={styles.wrap}>
      <div style={styles.sectionTitle}>💻 Coding Problems</div>
      <p style={styles.hint}>
        Write a program that reads from standard input and prints to standard output. <strong>Run</strong> tries the
        sample tests; <strong>Submit solution</strong> grades against all tests (including hidden ones) and your best
        attempt counts. You still need to press <strong>Submit Exam</strong> at the bottom to finish. Copy/paste is
        disabled during the exam.
      </p>

      <div style={styles.tabs}>
        {problems.map((p, i) => {
          const b = best[p.id];
          const solved = b && b.total > 0 && b.passed === b.total;
          return (
            <button
              key={p.id}
              onClick={() => {
                setActiveId(p.id);
                setError("");
              }}
              style={{ ...styles.tab, ...(p.id === problem.id ? styles.tabActive : {}) }}
            >
              {solved ? "✅ " : ""}
              {i + 1}. {p.title}
            </button>
          );
        })}
      </div>

      <div style={styles.card}>
        <div style={styles.problemHeader}>
          <h3 style={styles.problemTitle}>{problem.title}</h3>
          <div style={styles.metaRow}>
            <span style={styles.metaTag}>{problem.points} pts</span>
            <span style={styles.metaTag}>⏱ {problem.time_limit_seconds}s</span>
            <span style={styles.metaTag}>🧠 {problem.memory_limit_mb} MB</span>
            {bestForProblem && (
              <span style={{ ...styles.metaTag, ...styles.metaBest }}>
                Best: {bestForProblem.passed}/{bestForProblem.total} tests
              </span>
            )}
          </div>
        </div>

        <pre style={styles.statement}>{problem.statement}</pre>
        {problem.input_format && <Section label="Input format" text={problem.input_format} />}
        {problem.output_format && <Section label="Output format" text={problem.output_format} />}
        {problem.constraints && <Section label="Constraints" text={problem.constraints} />}

        {problem.samples.map((s, i) => (
          <div key={i} style={styles.sampleBox}>
            <div style={styles.sampleCol}>
              <div style={styles.sampleLabel}>Sample input {i + 1}</div>
              <pre style={styles.pre}>{s.input}</pre>
            </div>
            <div style={styles.sampleCol}>
              <div style={styles.sampleLabel}>Sample output {i + 1}</div>
              <pre style={styles.pre}>{s.expected_output}</pre>
            </div>
          </div>
        ))}
        {problem.hidden_test_count > 0 && (
          <p style={styles.hint}>+ {problem.hidden_test_count} hidden test{problem.hidden_test_count !== 1 ? "s" : ""} used when you submit.</p>
        )}

        <div style={styles.editorBar}>
          <label style={styles.label}>Language</label>
          <select value={draft.languageId} onChange={(e) => changeLanguage(parseInt(e.target.value))} style={styles.select}>
            {languages.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </div>

        <textarea
          value={draft.code}
          onChange={(e) => updateDraft({ code: e.target.value })}
          onKeyDown={handleTab}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          style={styles.editor}
          rows={16}
        />

        <label style={styles.customToggle}>
          <input
            type="checkbox"
            checked={!!showCustom[problem.id]}
            onChange={(e) => setShowCustom((prev) => ({ ...prev, [problem.id]: e.target.checked }))}
            style={{ marginRight: "8px" }}
          />
          Run with my own input instead of the samples
        </label>
        {showCustom[problem.id] && (
          <textarea
            value={customInput[problem.id] || ""}
            onChange={(e) => setCustomInput((prev) => ({ ...prev, [problem.id]: e.target.value }))}
            placeholder="Custom standard input"
            style={styles.customInput}
            rows={4}
          />
        )}

        {error && <div style={styles.errorBox}>{error}</div>}

        <div style={styles.btnRow}>
          <button onClick={() => execute("run")} disabled={!!busy} style={styles.runBtn}>
            {busy === "run" ? "Running..." : "▶ Run"}
          </button>
          <button onClick={() => execute("submit")} disabled={!!busy} style={styles.submitCodeBtn}>
            {busy === "submit" ? "Judging..." : "Submit solution"}
          </button>
        </div>

        {result && <ResultPanel result={result} />}
      </div>
    </div>
  );
}

function Section({ label, text }) {
  return (
    <div style={{ marginBottom: "12px" }}>
      <div style={styles.sampleLabel}>{label}</div>
      <pre style={styles.plain}>{text}</pre>
    </div>
  );
}

function VerdictBadge({ verdict, small }) {
  const ok = verdict === "Accepted" || verdict === "Ran Successfully";
  const style = ok
    ? { color: "#6EE7B7", background: "#0C2E22", border: "1px solid #1A5943" }
    : { color: "#FCA5A5", background: "#2A1215", border: "1px solid #5B2121" };
  return (
    <span style={{ ...styles.badge, ...style, ...(small ? styles.badgeSmall : {}) }}>
      {verdict}
    </span>
  );
}

function ResultPanel({ result }) {
  const title = result.kind === "submit" ? "Submission result" : result.mode === "custom" ? "Custom run" : "Sample run";

  if (result.mode === "custom") {
    return (
      <div style={styles.resultBox}>
        <div style={styles.resultHeader}>
          <strong style={{ color: "#E2E8F0" }}>{title}</strong>
          <VerdictBadge verdict={result.verdict} />
        </div>
        {result.compile_output && <Block label="Compiler output" text={result.compile_output} />}
        <Block label="Output" text={result.stdout} />
        {result.stderr && <Block label="Errors" text={result.stderr} />}
      </div>
    );
  }

  return (
    <div style={styles.resultBox}>
      <div style={styles.resultHeader}>
        <strong style={{ color: "#E2E8F0" }}>{title}</strong>
        <span>
          <span style={styles.passCount}>
            {result.passed}/{result.total} tests passed
          </span>{" "}
          <VerdictBadge verdict={result.verdict} />
        </span>
      </div>
      {result.compile_output && <Block label="Compiler output" text={result.compile_output} />}
      {result.cases.map((c, i) => (
        <div key={i} style={styles.caseRow}>
          <div style={styles.caseTop}>
            <span style={styles.caseLabel}>{c.label}</span>
            <span>
              {c.time != null && <span style={styles.caseTime}>{c.time}s</span>}
              <VerdictBadge verdict={c.verdict} small />
            </span>
          </div>
          {c.is_sample && !c.passed && c.verdict !== "Compilation Error" && (
            <div style={styles.caseDetail}>
              <Block label="Input" text={c.input} />
              <Block label="Expected" text={c.expected_output} />
              <Block label="Your output" text={c.actual_output} />
              {c.stderr && <Block label="Errors" text={c.stderr} />}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function Block({ label, text }) {
  return (
    <div style={{ marginTop: "8px" }}>
      <div style={styles.sampleLabel}>{label}</div>
      <pre style={styles.pre}>{text === "" ? "(empty)" : text}</pre>
    </div>
  );
}

const mono = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

const styles = {
  wrap: { marginTop: "36px" },
  sectionTitle: { fontSize: "20px", fontWeight: "600", color: "#F8FAFC", marginBottom: "8px", fontFamily: "'Space Grotesk', sans-serif" },
  hint: { fontSize: "13px", color: "#64748B", lineHeight: "1.6", margin: "0 0 16px" },
  tabs: { display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: "16px" },
  tab: { padding: "9px 14px", borderRadius: "8px", border: "1px solid #1C2438", background: "#0F1524", color: "#94A3B8", fontSize: "13px", fontWeight: "600", cursor: "pointer" },
  tabActive: { border: "1px solid #22D3EE", background: "#0D2540", color: "#22D3EE" },
  card: { background: "#0F1524", border: "1px solid #1C2438", borderRadius: "12px", padding: "20px" },
  problemHeader: { marginBottom: "12px" },
  problemTitle: { fontSize: "18px", fontWeight: "600", color: "#F8FAFC", margin: "0 0 8px" },
  metaRow: { display: "flex", gap: "8px", flexWrap: "wrap" },
  metaTag: { background: "#0A0E1A", color: "#94A3B8", padding: "3px 10px", borderRadius: "20px", fontSize: "12px", border: "1px solid #1C2438" },
  metaBest: { color: "#6EE7B7", border: "1px solid #1A5943", background: "#0C2E22" },
  statement: { whiteSpace: "pre-wrap", fontFamily: "Inter, sans-serif", fontSize: "14px", color: "#CBD5E1", lineHeight: "1.7", margin: "0 0 16px" },
  plain: { whiteSpace: "pre-wrap", fontFamily: "Inter, sans-serif", fontSize: "13px", color: "#CBD5E1", margin: "4px 0 0", lineHeight: "1.6" },
  sampleBox: { display: "flex", gap: "12px", marginBottom: "12px", flexWrap: "wrap" },
  sampleCol: { flex: "1 1 240px", minWidth: 0 },
  sampleLabel: { fontSize: "11px", fontWeight: "700", color: "#64748B", letterSpacing: "0.5px", textTransform: "uppercase", marginBottom: "4px" },
  pre: { margin: 0, padding: "10px 12px", background: "#0A0E1A", border: "1px solid #1C2438", borderRadius: "8px", fontFamily: mono, fontSize: "13px", color: "#E2E8F0", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: "220px", overflow: "auto" },
  editorBar: { display: "flex", alignItems: "center", gap: "12px", margin: "16px 0 8px" },
  label: { fontSize: "13px", fontWeight: "600", color: "#94A3B8" },
  select: { padding: "8px 10px", borderRadius: "8px", border: "1px solid #1E293B", background: "#0A0E1A", color: "#E2E8F0", fontSize: "13px" },
  editor: { width: "100%", boxSizing: "border-box", padding: "12px", borderRadius: "8px", border: "1px solid #1E293B", background: "#070B14", color: "#E2E8F0", fontFamily: mono, fontSize: "13px", lineHeight: "1.55", resize: "vertical", tabSize: 4, outline: "none" },
  customToggle: { display: "flex", alignItems: "center", fontSize: "13px", color: "#94A3B8", margin: "12px 0 8px", cursor: "pointer" },
  customInput: { width: "100%", boxSizing: "border-box", padding: "10px 12px", borderRadius: "8px", border: "1px solid #1E293B", background: "#070B14", color: "#E2E8F0", fontFamily: mono, fontSize: "13px", marginBottom: "8px" },
  errorBox: { background: "#2A1215", color: "#FCA5A5", padding: "10px 12px", borderRadius: "8px", margin: "10px 0", fontSize: "13px", border: "1px solid #5B2121" },
  btnRow: { display: "flex", gap: "10px", marginTop: "12px" },
  runBtn: { padding: "11px 22px", background: "#0D2540", color: "#22D3EE", border: "1px solid #1E4E7A", borderRadius: "8px", fontSize: "14px", fontWeight: "600", cursor: "pointer" },
  submitCodeBtn: { padding: "11px 22px", background: "#22D3EE", color: "#04141C", border: "none", borderRadius: "8px", fontSize: "14px", fontWeight: "600", cursor: "pointer" },
  resultBox: { marginTop: "16px", background: "#0A0E1A", border: "1px solid #1C2438", borderRadius: "10px", padding: "14px" },
  resultHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px", marginBottom: "8px" },
  passCount: { fontSize: "13px", color: "#94A3B8", marginRight: "6px" },
  badge: { display: "inline-block", padding: "4px 12px", borderRadius: "20px", fontSize: "12px", fontWeight: "700" },
  badgeSmall: { padding: "2px 9px", fontSize: "11px" },
  caseRow: { padding: "8px 0", borderTop: "1px solid #1C2438" },
  caseTop: { display: "flex", justifyContent: "space-between", alignItems: "center" },
  caseLabel: { fontSize: "13px", fontWeight: "600", color: "#CBD5E1" },
  caseTime: { fontSize: "11px", color: "#64748B", marginRight: "8px" },
  caseDetail: { marginTop: "6px" },
};

export default CodingProblems;
