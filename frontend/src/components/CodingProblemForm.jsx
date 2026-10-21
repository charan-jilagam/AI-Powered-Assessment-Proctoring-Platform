// Form for authoring one coding problem (used by CreateExam and AdminCoding).

function CodingProblemForm({ problem, onChange, onRemove, index }) {
  function set(field, value) {
    onChange({ ...problem, [field]: value });
  }

  function setTest(i, field, value) {
    const tests = problem.test_cases.map((t, j) => (j === i ? { ...t, [field]: value } : t));
    onChange({ ...problem, test_cases: tests });
  }

  function addTest(isSample) {
    onChange({
      ...problem,
      test_cases: [...problem.test_cases, { input_data: "", expected_output: "", is_sample: isSample }],
    });
  }

  function removeTest(i) {
    onChange({ ...problem, test_cases: problem.test_cases.filter((_, j) => j !== i) });
  }

  return (
    <div style={styles.block}>
      <div style={styles.header}>
        <span style={styles.num}>Coding problem {index + 1}</span>
        {onRemove && (
          <button type="button" onClick={onRemove} style={styles.removeBtn}>
            Remove
          </button>
        )}
      </div>

      <label style={styles.label}>Title</label>
      <input value={problem.title} onChange={(e) => set("title", e.target.value)} style={styles.input} placeholder="e.g. Sum of two numbers" />

      <label style={styles.label}>Statement</label>
      <textarea value={problem.statement} onChange={(e) => set("statement", e.target.value)} style={styles.textarea} rows={5} placeholder="Describe the task. Candidates read stdin and print to stdout." />

      <div style={styles.grid2}>
        <div>
          <label style={styles.label}>Input format (optional)</label>
          <textarea value={problem.input_format} onChange={(e) => set("input_format", e.target.value)} style={styles.textarea} rows={2} />
        </div>
        <div>
          <label style={styles.label}>Output format (optional)</label>
          <textarea value={problem.output_format} onChange={(e) => set("output_format", e.target.value)} style={styles.textarea} rows={2} />
        </div>
      </div>

      <label style={styles.label}>Constraints (optional)</label>
      <input value={problem.constraints} onChange={(e) => set("constraints", e.target.value)} style={styles.input} placeholder="e.g. 1 <= N <= 100000" />

      <div style={styles.grid3}>
        <div>
          <label style={styles.label}>Points</label>
          <input type="number" min="1" value={problem.points} onChange={(e) => set("points", e.target.value)} style={styles.input} />
        </div>
        <div>
          <label style={styles.label}>Time limit (s)</label>
          <input type="number" min="0.5" max="15" step="0.5" value={problem.time_limit_seconds} onChange={(e) => set("time_limit_seconds", e.target.value)} style={styles.input} />
        </div>
        <div>
          <label style={styles.label}>Memory (MB)</label>
          <input type="number" min="16" max="256" value={problem.memory_limit_mb} onChange={(e) => set("memory_limit_mb", e.target.value)} style={styles.input} />
        </div>
      </div>

      <div style={styles.testsHeader}>Test cases ({problem.test_cases.length})</div>
      <p style={styles.hint}>Sample tests are shown to candidates. Hidden tests are never shown, only pass/fail.</p>
      {problem.test_cases.map((t, i) => (
        <div key={i} style={styles.testRow}>
          <div style={styles.testTop}>
            <label style={styles.sampleCheck}>
              <input type="checkbox" checked={t.is_sample} onChange={(e) => setTest(i, "is_sample", e.target.checked)} style={{ marginRight: "6px" }} />
              Sample (visible to candidates)
            </label>
            {problem.test_cases.length > 1 && (
              <button type="button" onClick={() => removeTest(i)} style={styles.removeBtn}>
                Remove
              </button>
            )}
          </div>
          <div style={styles.grid2}>
            <textarea value={t.input_data} onChange={(e) => setTest(i, "input_data", e.target.value)} style={styles.mono} rows={3} placeholder="Input (stdin)" />
            <textarea value={t.expected_output} onChange={(e) => setTest(i, "expected_output", e.target.value)} style={styles.mono} rows={3} placeholder="Expected output (stdout)" />
          </div>
        </div>
      ))}
      <div style={styles.addRow}>
        <button type="button" onClick={() => addTest(true)} style={styles.addBtn}>+ Sample test</button>
        <button type="button" onClick={() => addTest(false)} style={styles.addBtn}>+ Hidden test</button>
      </div>
    </div>
  );
}

const mono = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
const field = { width: "100%", padding: "10px 12px", borderRadius: "8px", border: "1px solid #1E293B", background: "#0A0E1A", color: "#E2E8F0", fontSize: "14px", boxSizing: "border-box", fontFamily: "Inter, sans-serif", outline: "none" };

const styles = {
  block: { padding: "16px", background: "#0A0E1A", borderRadius: "10px", marginBottom: "16px", border: "1px solid #1C2438" },
  header: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" },
  num: { fontSize: "13px", fontWeight: "700", color: "#22D3EE" },
  removeBtn: { background: "transparent", border: "none", color: "#EF4444", fontSize: "12px", fontWeight: "600", cursor: "pointer" },
  label: { display: "block", fontSize: "12px", fontWeight: "600", color: "#94A3B8", margin: "12px 0 6px" },
  input: field,
  textarea: { ...field, resize: "vertical" },
  mono: { ...field, fontFamily: mono, fontSize: "13px", resize: "vertical" },
  grid2: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" },
  grid3: { display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "10px" },
  testsHeader: { fontSize: "14px", fontWeight: "700", color: "#F8FAFC", margin: "20px 0 4px" },
  hint: { fontSize: "12px", color: "#64748B", margin: "0 0 10px" },
  testRow: { padding: "10px", background: "#0F1524", border: "1px solid #1C2438", borderRadius: "8px", marginBottom: "10px" },
  testTop: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" },
  sampleCheck: { display: "flex", alignItems: "center", fontSize: "12px", color: "#94A3B8", cursor: "pointer" },
  addRow: { display: "flex", gap: "10px" },
  addBtn: { flex: 1, padding: "10px", background: "#0D2540", color: "#22D3EE", border: "1px dashed #1E4E7A", borderRadius: "8px", fontSize: "13px", fontWeight: "600", cursor: "pointer" },
};

export default CodingProblemForm;
