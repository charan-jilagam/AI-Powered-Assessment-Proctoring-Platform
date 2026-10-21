// Helpers for authoring coding problems (used by CreateExam and AdminCoding).

export function emptyProblem() {
  return {
    title: "",
    statement: "",
    input_format: "",
    output_format: "",
    constraints: "",
    points: 10,
    time_limit_seconds: 2,
    memory_limit_mb: 256,
    test_cases: [
      { input_data: "", expected_output: "", is_sample: true },
      { input_data: "", expected_output: "", is_sample: false },
    ],
  };
}

// Form state -> API payload
export function cleanProblem(p) {
  const optional = (v) => (v && v.trim() ? v : null);
  return {
    title: p.title.trim(),
    statement: p.statement,
    input_format: optional(p.input_format),
    output_format: optional(p.output_format),
    constraints: optional(p.constraints),
    points: parseInt(p.points),
    time_limit_seconds: parseFloat(p.time_limit_seconds),
    memory_limit_mb: parseInt(p.memory_limit_mb),
    test_cases: p.test_cases.map((t) => ({
      input_data: t.input_data,
      expected_output: t.expected_output,
      is_sample: !!t.is_sample,
    })),
  };
}

// Returns "" when fine, otherwise a message for the admin
export function validateProblem(p, label = "Coding problem") {
  if (!p.title.trim()) return `${label}: please enter a title.`;
  if (!p.statement.trim()) return `${label}: please enter the problem statement.`;
  if (!(parseInt(p.points) >= 1)) return `${label}: points must be at least 1.`;
  const seconds = parseFloat(p.time_limit_seconds);
  if (!(seconds >= 0.5 && seconds <= 15)) return `${label}: time limit must be between 0.5 and 15 seconds.`;
  const memory = parseInt(p.memory_limit_mb);
  if (!(memory >= 16 && memory <= 256)) return `${label}: memory limit must be between 16 and 256 MB.`;
  if (p.test_cases.length === 0) return `${label}: add at least one test case.`;
  for (let i = 0; i < p.test_cases.length; i++) {
    if (!p.test_cases[i].expected_output.trim()) return `${label}: test case ${i + 1} needs an expected output.`;
  }
  return "";
}

// Accepts an array of problems, or { problems: [...] }. Throws an Error with a readable message.
export function parseImportedProblems(text) {
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    throw new Error("That file is not valid JSON.");
  }
  const list = Array.isArray(json) ? json : json && Array.isArray(json.problems) ? json.problems : null;
  if (!list || list.length === 0) throw new Error('Expected a JSON array of problems (or {"problems": [...]}).');

  return list.map((raw, i) => {
    const label = `Problem ${i + 1}`;
    const tests = Array.isArray(raw.test_cases) ? raw.test_cases : [];
    const problem = {
      title: String(raw.title ?? ""),
      statement: String(raw.statement ?? ""),
      input_format: raw.input_format ?? "",
      output_format: raw.output_format ?? "",
      constraints: raw.constraints ?? "",
      points: raw.points ?? 10,
      time_limit_seconds: raw.time_limit_seconds ?? 2,
      memory_limit_mb: raw.memory_limit_mb ?? 256,
      test_cases: tests.map((t) => ({
        input_data: String(t.input_data ?? t.input ?? ""),
        expected_output: String(t.expected_output ?? t.output ?? ""),
        is_sample: !!t.is_sample,
      })),
    };
    const problemError = validateProblem(problem, label);
    if (problemError) throw new Error(problemError);
    return problem;
  });
}
