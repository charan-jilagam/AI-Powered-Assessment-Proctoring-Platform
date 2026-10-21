import { useState, useEffect, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { apiCall } from "../utils/api";
import CodingProblemForm from "../components/CodingProblemForm";
import { emptyProblem, cleanProblem, validateProblem, parseImportedProblems } from "../utils/codingProblems";

function AdminCoding() {
    const { examId } = useParams();
    const [tab, setTab] = useState("problems"); // "problems" | "submissions"
    const [problems, setProblems] = useState([]);
    const [submissions, setSubmissions] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [success, setSuccess] = useState("");
    const [adding, setAdding] = useState(null); // a problem being authored, or null
    const [saving, setSaving] = useState(false);
    const [openProblem, setOpenProblem] = useState(null);
    const [openSubmission, setOpenSubmission] = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const [p, s] = await Promise.all([
                apiCall(`/exams/${examId}/coding-problems`, "GET"),
                apiCall(`/exams/${examId}/coding-submissions`, "GET"),
            ]);
            setProblems(p);
            setSubmissions(s);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [examId]);

    useEffect(() => {
        load();
    }, [load]);

    async function saveProblem() {
        setError(""); setSuccess("");
        const problemError = validateProblem(adding);
        if (problemError) {
            setError(problemError);
            return;
        }
        setSaving(true);
        try {
            await apiCall(`/exams/${examId}/coding-problems`, "POST", cleanProblem(adding));
            setSuccess("Problem added.");
            setAdding(null);
            await load();
        } catch (err) {
            setError(err.message);
        } finally {
            setSaving(false);
        }
    }

    async function importJson(file) {
        if (!file) return;
        setError(""); setSuccess("");
        try {
            const parsed = parseImportedProblems(await file.text());
            const res = await apiCall(`/exams/${examId}/coding-problems/bulk`, "POST", {
                problems: parsed.map(cleanProblem),
            });
            setSuccess(`Imported ${res.count} problem${res.count !== 1 ? "s" : ""}.`);
            await load();
        } catch (err) {
            setError(err.message);
        }
    }

    async function deleteProblem(problem) {
        const confirmed = window.confirm(
            `Delete "${problem.title}"?\n\nThis also deletes all candidate code submissions for it, which changes their scores. This cannot be undone.`
        );
        if (!confirmed) return;
        try {
            await apiCall(`/coding-problems/${problem.id}`, "DELETE");
            await load();
        } catch (err) {
            setError(err.message);
        }
    }

    return (
        <div style={styles.page}>
            <nav style={styles.navbar}>
                <div style={styles.navBrand}>
                    <span style={styles.navLogo}>🛡️</span>
                    <span style={styles.navName}>ProctorAI</span>
                </div>
                <Link to="/dashboard" style={styles.backBtn}>← Back to Dashboard</Link>
            </nav>

            <div style={styles.main}>
                <div style={styles.eyebrow}>ADMIN CONSOLE · EXAM #{examId}</div>
                <h1 style={styles.title}>Coding Problems</h1>
                <p style={styles.subtitle}>
                    Candidates write code in the exam; it runs in a Judge0 sandbox and is scored against your test cases.
                </p>

                {error && <div style={styles.errorBox}>{error}</div>}
                {success && <div style={styles.successBox}>✅ {success}</div>}

                <div style={styles.tabs}>
                    <button onClick={() => setTab("problems")} style={{ ...styles.tab, ...(tab === "problems" ? styles.tabActive : {}) }}>
                        Problems ({problems.length})
                    </button>
                    <button onClick={() => setTab("submissions")} style={{ ...styles.tab, ...(tab === "submissions" ? styles.tabActive : {}) }}>
                        Code submissions ({submissions.length})
                    </button>
                </div>

                {loading && <div style={styles.muted}>Loading...</div>}

                {!loading && tab === "problems" && (
                    <>
                        {!adding && (
                            <div style={styles.actionRow}>
                                <button onClick={() => { setAdding(emptyProblem()); setError(""); setSuccess(""); }} style={styles.primaryBtn}>
                                    + Add problem
                                </button>
                                <label style={styles.secondaryBtn}>
                                    Import from JSON
                                    <input
                                        type="file"
                                        accept=".json,application/json"
                                        style={{ display: "none" }}
                                        onChange={(e) => { importJson(e.target.files[0]); e.target.value = ""; }}
                                    />
                                </label>
                            </div>
                        )}

                        {adding && (
                            <div style={styles.card}>
                                <CodingProblemForm problem={adding} onChange={setAdding} index={problems.length} />
                                <div style={styles.actionRow}>
                                    <button onClick={saveProblem} disabled={saving} style={styles.primaryBtn}>
                                        {saving ? "Saving..." : "Save problem"}
                                    </button>
                                    <button onClick={() => setAdding(null)} style={styles.secondaryBtn}>Cancel</button>
                                </div>
                            </div>
                        )}

                        {problems.length === 0 && !adding && (
                            <div style={styles.emptyBox}>No coding problems yet. Add one or import a JSON file.</div>
                        )}

                        {problems.map((p) => (
                            <div key={p.id} style={styles.card}>
                                <div style={styles.rowBetween}>
                                    <div>
                                        <div style={styles.problemTitle}>{p.title}</div>
                                        <div style={styles.metaRow}>
                                            <span style={styles.metaTag}>{p.points} pts</span>
                                            <span style={styles.metaTag}>⏱ {p.time_limit_seconds}s</span>
                                            <span style={styles.metaTag}>🧠 {p.memory_limit_mb} MB</span>
                                            <span style={styles.metaTag}>
                                                {p.test_cases.filter((t) => t.is_sample).length} sample · {p.test_cases.filter((t) => !t.is_sample).length} hidden
                                            </span>
                                        </div>
                                    </div>
                                    <div style={styles.actionRow}>
                                        <button onClick={() => setOpenProblem(openProblem === p.id ? null : p.id)} style={styles.secondaryBtn}>
                                            {openProblem === p.id ? "Hide details" : "View details"}
                                        </button>
                                        <button onClick={() => deleteProblem(p)} style={styles.deleteBtn}>Delete</button>
                                    </div>
                                </div>
                                {openProblem === p.id && (
                                    <div style={{ marginTop: "14px" }}>
                                        <pre style={styles.statement}>{p.statement}</pre>
                                        {p.test_cases.map((t, i) => (
                                            <div key={t.id} style={styles.testBox}>
                                                <div style={styles.testLabel}>
                                                    Test {i + 1} · {t.is_sample ? "sample" : "hidden"}
                                                </div>
                                                <div style={styles.testGrid}>
                                                    <pre style={styles.pre}>{t.input_data || "(no input)"}</pre>
                                                    <pre style={styles.pre}>{t.expected_output}</pre>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        ))}
                    </>
                )}

                {!loading && tab === "submissions" && (
                    <>
                        {submissions.length === 0 && <div style={styles.emptyBox}>No code submitted yet.</div>}
                        {submissions.length > 0 && (
                            <div style={styles.card}>
                                <table style={styles.table}>
                                    <thead>
                                        <tr>
                                            {["Candidate", "Problem", "Language", "Verdict", "Tests", "When", ""].map((h) => (
                                                <th key={h} style={styles.th}>{h}</th>
                                            ))}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {submissions.map((s) => (
                                            <SubmissionRow
                                                key={s.id}
                                                s={s}
                                                open={openSubmission === s.id}
                                                onToggle={() => setOpenSubmission(openSubmission === s.id ? null : s.id)}
                                            />
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}

function SubmissionRow({ s, open, onToggle }) {
    const ok = s.verdict === "Accepted";
    return (
        <>
            <tr>
                <td style={styles.td}>
                    <div style={{ color: "#E2E8F0", fontWeight: 600 }}>{s.student_name}</div>
                    <div style={{ color: "#64748B", fontSize: "12px" }}>{s.student_email}</div>
                </td>
                <td style={styles.td}>{s.problem_title}</td>
                <td style={styles.td}>{s.language}</td>
                <td style={styles.td}>
                    <span style={{ ...styles.badge, ...(ok ? styles.badgeOk : styles.badgeBad) }}>{s.verdict}</span>
                </td>
                <td style={styles.td}>{s.passed}/{s.total}</td>
                <td style={styles.td}>{new Date(s.created_at).toLocaleString()}</td>
                <td style={styles.td}>
                    <button onClick={onToggle} style={styles.linkBtn}>{open ? "Hide code" : "View code"}</button>
                </td>
            </tr>
            {open && (
                <tr>
                    <td colSpan={7} style={{ padding: "0 0 12px" }}>
                        <pre style={styles.code}>{s.source_code}</pre>
                    </td>
                </tr>
            )}
        </>
    );
}

const mono = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

const styles = {
    page: { minHeight: "100vh", background: "#0A0E1A", fontFamily: "Inter, sans-serif" },
    navbar: { background: "#0C1120", borderBottom: "1px solid #1C2438", padding: "0 40px", height: "64px", display: "flex", alignItems: "center", justifyContent: "space-between", position: "sticky", top: 0, zIndex: 100 },
    navBrand: { display: "flex", alignItems: "center", gap: "10px" },
    navLogo: { fontSize: "22px" },
    navName: { fontSize: "18px", fontWeight: "600", color: "#F8FAFC", fontFamily: "'Space Grotesk', sans-serif" },
    backBtn: { color: "#22D3EE", textDecoration: "none", fontSize: "14px", fontWeight: "500" },
    main: { maxWidth: "980px", margin: "0 auto", padding: "40px 20px" },
    eyebrow: { fontFamily: "'Space Grotesk', sans-serif", color: "#334155", fontSize: "11px", letterSpacing: "2px", marginBottom: "10px" },
    title: { fontSize: "28px", fontWeight: "600", color: "#F8FAFC", margin: "0 0 4px", fontFamily: "'Space Grotesk', sans-serif" },
    subtitle: { fontSize: "14px", color: "#64748B", marginBottom: "24px" },
    errorBox: { background: "#2A1215", color: "#FCA5A5", padding: "12px", borderRadius: "10px", marginBottom: "16px", fontSize: "14px", border: "1px solid #5B2121" },
    successBox: { background: "#0C2E22", color: "#6EE7B7", padding: "12px", borderRadius: "10px", marginBottom: "16px", fontSize: "14px", border: "1px solid #1A5943" },
    tabs: { display: "flex", gap: "10px", marginBottom: "20px" },
    tab: { padding: "10px 18px", border: "1px solid #1C2438", borderRadius: "10px", background: "#0F1524", fontSize: "14px", fontWeight: "600", color: "#64748B", cursor: "pointer" },
    tabActive: { border: "1px solid #22D3EE", background: "#0D2540", color: "#22D3EE" },
    muted: { color: "#64748B", padding: "30px", textAlign: "center" },
    actionRow: { display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap", margin: "0 0 16px" },
    primaryBtn: { padding: "10px 18px", background: "#22D3EE", color: "#04141C", border: "none", borderRadius: "8px", fontSize: "14px", fontWeight: "600", cursor: "pointer" },
    secondaryBtn: { padding: "10px 18px", background: "#0F1524", color: "#94A3B8", border: "1px solid #1C2438", borderRadius: "8px", fontSize: "14px", fontWeight: "500", cursor: "pointer", display: "inline-block" },
    deleteBtn: { padding: "10px 16px", background: "transparent", color: "#EF4444", border: "1px solid #5B2121", borderRadius: "8px", fontSize: "14px", fontWeight: "600", cursor: "pointer" },
    card: { background: "#0F1524", border: "1px solid #1C2438", borderRadius: "14px", padding: "20px", marginBottom: "16px" },
    emptyBox: { textAlign: "center", padding: "50px 20px", background: "#0F1524", borderRadius: "14px", border: "1px solid #1C2438", color: "#64748B", fontSize: "14px" },
    rowBetween: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "16px", flexWrap: "wrap" },
    problemTitle: { fontSize: "16px", fontWeight: "600", color: "#F8FAFC", marginBottom: "8px" },
    metaRow: { display: "flex", gap: "8px", flexWrap: "wrap" },
    metaTag: { background: "#0A0E1A", color: "#94A3B8", padding: "3px 10px", borderRadius: "20px", fontSize: "12px", border: "1px solid #1C2438" },
    statement: { whiteSpace: "pre-wrap", fontFamily: "Inter, sans-serif", fontSize: "13px", color: "#CBD5E1", lineHeight: "1.7", margin: "0 0 12px" },
    testBox: { marginBottom: "10px" },
    testLabel: { fontSize: "11px", fontWeight: "700", color: "#64748B", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "4px" },
    testGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" },
    pre: { margin: 0, padding: "10px 12px", background: "#0A0E1A", border: "1px solid #1C2438", borderRadius: "8px", fontFamily: mono, fontSize: "12px", color: "#E2E8F0", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: "180px", overflow: "auto" },
    table: { width: "100%", borderCollapse: "collapse" },
    th: { textAlign: "left", fontSize: "11px", color: "#64748B", textTransform: "uppercase", letterSpacing: "0.5px", padding: "8px 10px", borderBottom: "1px solid #1C2438" },
    td: { padding: "10px", fontSize: "13px", color: "#CBD5E1", borderBottom: "1px solid #1C2438", verticalAlign: "top" },
    badge: { display: "inline-block", padding: "3px 10px", borderRadius: "20px", fontSize: "11px", fontWeight: "700" },
    badgeOk: { color: "#6EE7B7", background: "#0C2E22", border: "1px solid #1A5943" },
    badgeBad: { color: "#FCA5A5", background: "#2A1215", border: "1px solid #5B2121" },
    linkBtn: { background: "transparent", border: "none", color: "#22D3EE", fontSize: "13px", fontWeight: "600", cursor: "pointer" },
    code: { margin: 0, padding: "12px", background: "#070B14", border: "1px solid #1C2438", borderRadius: "8px", fontFamily: mono, fontSize: "12px", color: "#E2E8F0", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: "360px", overflow: "auto" },
};

export default AdminCoding;
