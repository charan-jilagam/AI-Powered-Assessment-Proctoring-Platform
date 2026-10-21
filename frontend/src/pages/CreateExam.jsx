import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { apiCall, getToken } from "../utils/api";
import CodingProblemForm from "../components/CodingProblemForm";
import { emptyProblem, cleanProblem, validateProblem, parseImportedProblems } from "../utils/codingProblems";

const API_URL = "http://localhost:8000";

function CreateExam() {
    const navigate = useNavigate();
    const [mode, setMode] = useState("manual"); // "manual" or "csv"

    // Shared exam fields
    const [title, setTitle] = useState("");
    const [description, setDescription] = useState("");
    const [duration, setDuration] = useState(10);

    // Manual questions
    const [questions, setQuestions] = useState([
        { question_text: "", option_a: "", option_b: "", option_c: "", option_d: "", correct_answer: "A" },
    ]);

    // Coding problems (judged by Judge0) - optional
    const [codingProblems, setCodingProblems] = useState([]);

    // CSV
    const [csvFile, setCsvFile] = useState(null);

    const [error, setError] = useState("");
    const [success, setSuccess] = useState("");
    const [loading, setLoading] = useState(false);

    function updateQuestion(index, field, value) {
        setQuestions((prev) => {
            const copy = [...prev];
            copy[index] = { ...copy[index], [field]: value };
            return copy;
        });
    }

    function addQuestion() {
        setQuestions((prev) => [...prev, { question_text: "", option_a: "", option_b: "", option_c: "", option_d: "", correct_answer: "A" }]);
    }

    function removeQuestion(index) {
        setQuestions((prev) => prev.filter((_, i) => i !== index));
    }

    function updateCodingProblem(index, problem) {
        setCodingProblems((prev) => prev.map((p, i) => (i === index ? problem : p)));
    }

    async function importCodingJson(file) {
        if (!file) return;
        setError("");
        try {
            const imported = parseImportedProblems(await file.text());
            setCodingProblems((prev) => [...prev, ...imported]);
        } catch (err) {
            setError(err.message);
        }
    }

    async function submitManual() {
        setError(""); setSuccess(""); setLoading(true);

        // Validate before sending
        if (!title.trim()) {
            setError("Please enter an exam title.");
            setLoading(false);
            return;
        }
        // A completely empty multiple-choice block is ignored (so coding-only exams are possible)
        const isBlank = (q) => !q.question_text.trim() && !q.option_a.trim() && !q.option_b.trim() && !q.option_c.trim() && !q.option_d.trim();
        const filledQuestions = [];
        for (let i = 0; i < questions.length; i++) {
            const q = questions[i];
            if (isBlank(q)) continue;
            if (!q.question_text.trim() || !q.option_a.trim() || !q.option_b.trim() || !q.option_c.trim() || !q.option_d.trim()) {
                setError(`Question ${i + 1} is incomplete. Please fill in the question and all four options.`);
                setLoading(false);
                return;
            }
            filledQuestions.push(q);
        }
        for (let i = 0; i < codingProblems.length; i++) {
            const problemError = validateProblem(codingProblems[i], `Coding problem ${i + 1}`);
            if (problemError) {
                setError(problemError);
                setLoading(false);
                return;
            }
        }
        if (filledQuestions.length === 0 && codingProblems.length === 0) {
            setError("Add at least one multiple-choice question or coding problem.");
            setLoading(false);
            return;
        }

        try {
            const res = await apiCall("/exams/create", "POST", {
                title,
                description,
                duration_minutes: parseInt(duration),
                questions: filledQuestions,
                coding_problems: codingProblems.map(cleanProblem),
            });
            const codingNote = res.coding_problem_count ? ` and ${res.coding_problem_count} coding problem${res.coding_problem_count !== 1 ? "s" : ""}` : "";
            setSuccess(`Exam "${res.title}" created with ${res.question_count} questions${codingNote}!`);
            setTimeout(() => navigate("/dashboard"), 2000);
        } catch (err) {
            // Handle both string errors and structured validation errors
            const msg = typeof err.message === "string" ? err.message : "Failed to create exam. Please check all fields.";
            setError(msg);
        } finally {
            setLoading(false);
        }
    }

    async function submitCsv() {
        setError(""); setSuccess(""); setLoading(true);
        if (!csvFile) {
            setError("Please select a CSV file.");
            setLoading(false);
            return;
        }
        try {
            const formData = new FormData();
            formData.append("title", title);
            formData.append("description", description);
            formData.append("duration_minutes", parseInt(duration));
            formData.append("file", csvFile);

            const response = await fetch(`${API_URL}/exams/upload-csv`, {
                method: "POST",
                headers: { "Authorization": `Bearer ${getToken()}` },
                body: formData, // no Content-Type — browser sets it for multipart
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || "Upload failed");

            setSuccess(`Exam "${data.title}" created with ${data.question_count} questions!`);
            setTimeout(() => navigate("/dashboard"), 2000);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    return (
        <div style={styles.page}>
            <nav style={styles.navbar}>
                <div style={styles.navBrand}>
                    <span style={styles.navLogo}>🎓</span>
                    <span style={styles.navName}>ProctorAI</span>
                </div>
                <Link to="/dashboard" style={styles.backBtn}>← Back to Dashboard</Link>
            </nav>

            <div style={styles.main}>
                <h1 style={styles.title}>Create New Exam</h1>
                <p style={styles.subtitle}>Add questions manually or upload a CSV file</p>

                {error && <div style={styles.errorBox}>{error}</div>}
                {success && <div style={styles.successBox}>✅ {success}</div>}

                {/* Mode toggle */}
                <div style={styles.modeToggle}>
                    <button
                        onClick={() => setMode("manual")}
                        style={{ ...styles.modeBtn, ...(mode === "manual" ? styles.modeBtnActive : {}) }}
                    >
                        ✍️ Manual Entry
                    </button>
                    <button
                        onClick={() => setMode("csv")}
                        style={{ ...styles.modeBtn, ...(mode === "csv" ? styles.modeBtnActive : {}) }}
                    >
                        📄 CSV Upload
                    </button>
                </div>

                {/* Shared exam details */}
                <div style={styles.card}>
                    <h3 style={styles.cardTitle}>Exam Details</h3>
                    <div style={styles.field}>
                        <label style={styles.label}>Title</label>
                        <input value={title} onChange={(e) => setTitle(e.target.value)} style={styles.input} placeholder="e.g. Java Fundamentals" />
                    </div>
                    <div style={styles.field}>
                        <label style={styles.label}>Description</label>
                        <input value={description} onChange={(e) => setDescription(e.target.value)} style={styles.input} placeholder="Short description" />
                    </div>
                    <div style={styles.field}>
                        <label style={styles.label}>Duration (minutes)</label>
                        <input type="number" value={duration} onChange={(e) => setDuration(e.target.value)} style={styles.input} min="1" />
                    </div>
                </div>

                {/* Manual mode */}
                {mode === "manual" && (
                    <div style={styles.card}>
                        <h3 style={styles.cardTitle}>Questions ({questions.length})</h3>
                        {questions.map((q, i) => (
                            <div key={i} style={styles.questionBlock}>
                                <div style={styles.questionHeader}>
                                    <span style={styles.questionNum}>Question {i + 1}</span>
                                    {questions.length > 1 && (
                                        <button onClick={() => removeQuestion(i)} style={styles.removeBtn}>Remove</button>
                                    )}
                                </div>
                                <input value={q.question_text} onChange={(e) => updateQuestion(i, "question_text", e.target.value)} style={styles.input} placeholder="Question text" />
                                <div style={styles.optionsGrid}>
                                    {["a", "b", "c", "d"].map((opt) => (
                                        <input key={opt} value={q[`option_${opt}`]} onChange={(e) => updateQuestion(i, `option_${opt}`, e.target.value)} style={styles.input} placeholder={`Option ${opt.toUpperCase()}`} />
                                    ))}
                                </div>
                                <div style={styles.field}>
                                    <label style={styles.label}>Correct Answer</label>
                                    <select value={q.correct_answer} onChange={(e) => updateQuestion(i, "correct_answer", e.target.value)} style={styles.input}>
                                        <option value="A">A</option>
                                        <option value="B">B</option>
                                        <option value="C">C</option>
                                        <option value="D">D</option>
                                    </select>
                                </div>
                            </div>
                        ))}
                        <button onClick={addQuestion} style={styles.addBtn}>+ Add Question</button>
                    </div>
                )}

                {/* Coding problems (manual mode) */}
                {mode === "manual" && (
                    <div style={styles.card}>
                        <h3 style={styles.cardTitle}>Coding Problems ({codingProblems.length})</h3>
                        <p style={styles.csvHint}>
                            Optional. Candidates write code that is run and scored against your test cases.
                            You can also add or import problems later from the exam's <strong>Coding</strong> button on the dashboard.
                        </p>
                        {codingProblems.map((p, i) => (
                            <CodingProblemForm
                                key={i}
                                index={i}
                                problem={p}
                                onChange={(updated) => updateCodingProblem(i, updated)}
                                onRemove={() => setCodingProblems((prev) => prev.filter((_, j) => j !== i))}
                            />
                        ))}
                        <button onClick={() => setCodingProblems((prev) => [...prev, emptyProblem()])} style={styles.addBtn}>
                            + Add Coding Problem
                        </button>
                        <label style={styles.importBtn}>
                            Import coding problems from JSON
                            <input
                                type="file"
                                accept=".json,application/json"
                                style={{ display: "none" }}
                                onChange={(e) => { importCodingJson(e.target.files[0]); e.target.value = ""; }}
                            />
                        </label>
                        <button onClick={submitManual} disabled={loading} style={styles.submitBtn}>
                            {loading ? "Creating..." : "Create Exam"}
                        </button>
                    </div>
                )}

                {/* CSV mode */}
                {mode === "csv" && (
                    <div style={styles.card}>
                        <h3 style={styles.cardTitle}>Upload CSV</h3>
                        <p style={styles.csvHint}>
                            CSV must have columns: <strong>Question, Option A, Option B, Option C, Option D, Answer</strong>
                            (Answer is a letter: A, B, C, or D)
                        </p>
                        <input type="file" accept=".csv" onChange={(e) => setCsvFile(e.target.files[0])} style={styles.fileInput} />
                        <button onClick={submitCsv} disabled={loading} style={styles.submitBtn}>
                            {loading ? "Uploading..." : "Upload & Create Exam"}
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}

const styles = {
    page: { minHeight: "100vh", background: "#0A0E1A", fontFamily: "Inter, sans-serif" },
    navbar: { background: "#0C1120", borderBottom: "1px solid #1C2438", padding: "0 40px", height: "64px", display: "flex", alignItems: "center", justifyContent: "space-between", position: "sticky", top: 0, zIndex: 100 },
    navBrand: { display: "flex", alignItems: "center", gap: "10px" },
    navLogo: { fontSize: "24px" },
    navName: { fontSize: "18px", fontWeight: "600", color: "#F8FAFC", fontFamily: "'Space Grotesk', sans-serif" },
    backBtn: { color: "#22D3EE", textDecoration: "none", fontSize: "14px", fontWeight: "500" },
    main: { maxWidth: "720px", margin: "0 auto", padding: "40px 20px" },
    title: { fontSize: "28px", fontWeight: "600", color: "#F8FAFC", marginBottom: "4px", fontFamily: "'Space Grotesk', sans-serif" },
    subtitle: { fontSize: "14px", color: "#64748B", marginBottom: "24px" },
    errorBox: { background: "#2A1215", color: "#FCA5A5", padding: "12px", borderRadius: "10px", marginBottom: "16px", fontSize: "14px", border: "1px solid #5B2121" },
    successBox: { background: "#0C2E22", color: "#6EE7B7", padding: "12px", borderRadius: "10px", marginBottom: "16px", fontSize: "14px", border: "1px solid #1A5943" },
    modeToggle: { display: "flex", gap: "10px", marginBottom: "24px" },
    modeBtn: { flex: 1, padding: "12px", border: "1px solid #1C2438", borderRadius: "10px", background: "#0F1524", fontSize: "14px", fontWeight: "600", color: "#64748B", cursor: "pointer" },
    modeBtnActive: { border: "1px solid #22D3EE", background: "#0D2540", color: "#22D3EE" },
    card: { background: "#0F1524", border: "1px solid #1C2438", borderRadius: "16px", padding: "24px", marginBottom: "20px" },
    cardTitle: { fontSize: "16px", fontWeight: "700", color: "#F8FAFC", marginBottom: "16px" },
    field: { marginBottom: "16px" },
    label: { display: "block", fontSize: "13px", fontWeight: "600", color: "#94A3B8", marginBottom: "6px" },
    input: { width: "100%", padding: "10px 12px", borderRadius: "8px", border: "1px solid #1E293B", background: "#0A0E1A", color: "#E2E8F0", fontSize: "14px", boxSizing: "border-box", fontFamily: "Inter, sans-serif", outline: "none" },
    questionBlock: { padding: "16px", background: "#0A0E1A", borderRadius: "10px", marginBottom: "16px", border: "1px solid #1C2438" },
    questionHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" },
    questionNum: { fontSize: "13px", fontWeight: "700", color: "#22D3EE" },
    removeBtn: { background: "transparent", border: "none", color: "#EF4444", fontSize: "12px", fontWeight: "600", cursor: "pointer" },
    optionsGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", margin: "10px 0" },
    addBtn: { width: "100%", padding: "12px", background: "#0D2540", color: "#22D3EE", border: "1px dashed #1E4E7A", borderRadius: "8px", fontSize: "14px", fontWeight: "600", cursor: "pointer", marginBottom: "16px" },
    importBtn: { display: "block", textAlign: "center", boxSizing: "border-box", width: "100%", padding: "12px", background: "transparent", color: "#94A3B8", border: "1px solid #1E293B", borderRadius: "8px", fontSize: "14px", fontWeight: "500", cursor: "pointer", marginBottom: "16px" },
    submitBtn: { width: "100%", padding: "14px", background: "#22D3EE", color: "#04141C", border: "none", borderRadius: "10px", fontSize: "15px", fontWeight: "600", cursor: "pointer", boxShadow: "0 0 20px rgba(34,211,238,0.3)" },
    csvHint: { fontSize: "13px", color: "#64748B", marginBottom: "16px", lineHeight: "1.6" },
    fileInput: { width: "100%", padding: "20px", border: "2px dashed #1E293B", borderRadius: "10px", marginBottom: "16px", fontSize: "14px", background: "#0A0E1A", color: "#94A3B8" },
};

export default CreateExam;