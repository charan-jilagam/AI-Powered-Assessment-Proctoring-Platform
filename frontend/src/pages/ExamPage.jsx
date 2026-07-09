import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { apiCall } from "../utils/api";

const MAX_LEVEL2_VIOLATIONS = 3;

function ExamPage() {
    const { examId } = useParams();
    const navigate = useNavigate();

    const [exam, setExam] = useState(null);
    const [answers, setAnswers] = useState({});
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState("");
    const [result, setResult] = useState(null);
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [alerts, setAlerts] = useState([]);
    const [level2Count, setLevel2Count] = useState(0);
    const [examTerminated, setExamTerminated] = useState(false);
    const [cameraActive, setCameraActive] = useState(false);
    const [cameraError, setCameraError] = useState("");
    const [audioActive, setAudioActive] = useState(false);
    const [level2Modal, setLevel2Modal] = useState(null);
    const [agreedToTerms, setAgreedToTerms] = useState(false);
    const [timeLeft, setTimeLeft] = useState(null); // seconds remaining

    function pushAlert(message, type) {
        const id = Date.now() + Math.random();
        setAlerts((prev) => [...prev, { id, message, type }]);
        // Auto-remove this alert after 5 seconds
        setTimeout(() => {
            setAlerts((prev) => prev.filter((a) => a.id !== id));
        }, 5000);
    }
    function formatTime(seconds) {
        if (seconds === null) return "--:--";
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}:${secs.toString().padStart(2, "0")}`;
    }

    useEffect(() => {
        loadExam();
    }, [examId]);

    useEffect(() => {
        function handleVisibilityChange() {
            if (document.hidden && isFullscreen && !result && !examTerminated) {
                logViolation("Tab switch detected", 2);
            }
        }
        document.addEventListener("visibilitychange", handleVisibilityChange);
        return () => document.removeEventListener("visibilitychange", handleVisibilityChange);
    }, [isFullscreen, level2Count, result, examTerminated]);

    useEffect(() => {
        function handleFullscreenChange() {
            const inFullscreen = !!document.fullscreenElement;
            setIsFullscreen(inFullscreen);
            if (!inFullscreen && exam && !result && !examTerminated && !submitting) {
                logViolation("Exited fullscreen mode", 2);
            }
        }
        document.addEventListener("fullscreenchange", handleFullscreenChange);
        return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
    }, [exam, level2Count, result, examTerminated, submitting]);

    useEffect(() => {
        function blockCopyPaste(e) {
            e.preventDefault();
            logViolation("Attempted copy/paste/cut", 1);
        }
        function blockRightClick(e) {
            e.preventDefault();
            logViolation("Attempted right-click", 1);
        }
        document.addEventListener("copy", blockCopyPaste);
        document.addEventListener("paste", blockCopyPaste);
        document.addEventListener("cut", blockCopyPaste);
        document.addEventListener("contextmenu", blockRightClick);
        return () => {
            document.removeEventListener("copy", blockCopyPaste);
            document.removeEventListener("paste", blockCopyPaste);
            document.removeEventListener("cut", blockCopyPaste);
            document.removeEventListener("contextmenu", blockRightClick);
        };
    }, []);

    useEffect(() => {
        function blockShortcuts(e) {
            if (
                e.altKey ||
                e.metaKey ||
                e.key === "F11" ||
                e.key === "F12" ||
                (e.ctrlKey && e.shiftKey && e.key === "I") ||
                (e.ctrlKey && e.shiftKey && e.key === "J") ||
                (e.ctrlKey && e.key === "u")
            ) {
                e.preventDefault();
                logViolation("Keyboard shortcut attempted", 1);
            }
        }
        document.addEventListener("keydown", blockShortcuts);
        return () => document.removeEventListener("keydown", blockShortcuts);
    }, []);

    // Webcam setup and AI frame analysis
    useEffect(() => {
        if (!isFullscreen || !exam || examTerminated) return;

        let stream = null;
        let intervalId = null;

        async function startCamera() {
            try {
                stream = await navigator.mediaDevices.getUserMedia({ video: true });
                const videoElement = document.getElementById("proctorVideo");
                if (videoElement) {
                    videoElement.srcObject = stream;
                    setCameraActive(true);
                }

                intervalId = setInterval(async () => {
                    const video = document.getElementById("proctorVideo");
                    if (!video || !video.videoWidth || !video.videoHeight) {
                        console.log("Video not ready yet...");
                        return;
                    }

                    const canvas = document.createElement("canvas");
                    canvas.width = video.videoWidth;
                    canvas.height = video.videoHeight;
                    const ctx = canvas.getContext("2d");
                    ctx.drawImage(video, 0, 0);
                    const imageData = canvas.toDataURL("image/jpeg", 0.6);

                    try {
                        const res = await apiCall("/proctor/analyze", "POST", {
                            exam_id: parseInt(examId),
                            image: imageData,
                        });
                        console.log("AI result:", res);
                        if (res.warnings && res.warnings.length > 0) {
                            pushAlert(res.warnings.join(", "), "ai");
                        }
                    } catch (err) {
                        console.error("AI analysis failed:", err);
                    }
                }, 1500);
            } catch (err) {
                setCameraError("Camera access denied. You must allow camera access to take the exam.");
                console.error("Camera error:", err);
            }
        }

        startCamera();

        return () => {
            if (intervalId) clearInterval(intervalId);
            if (stream) {
                stream.getTracks().forEach((track) => track.stop());
            }
        };
    }, [isFullscreen, exam, examTerminated, examId]);

    // Countdown timer - starts when exam begins
    useEffect(() => {
        if (!isFullscreen || !exam || examTerminated || result || !agreedToTerms) return;

        if (timeLeft === null) {
            setTimeLeft(exam.remaining_seconds ?? exam.duration_minutes * 60);
            return;
        }

        if (timeLeft <= 0) {
            handleSubmit();
            return;
        }

        const timerId = setTimeout(() => {
            setTimeLeft((prev) => prev - 1);
        }, 1000);

        return () => clearTimeout(timerId);
    }, [isFullscreen, exam, examTerminated, result, timeLeft, agreedToTerms]);

    // Microphone monitoring - detects sustained talking
    useEffect(() => {
        if (!isFullscreen || !exam || examTerminated) return;

        let audioStream = null;
        let audioContext = null;
        let intervalId = null;
        let loudFrameCount = 0;

        async function startAudioMonitoring() {
            try {
                audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
                const source = audioContext.createMediaStreamSource(audioStream);
                const analyser = audioContext.createAnalyser();
                analyser.fftSize = 512;
                source.connect(analyser);

                const dataArray = new Uint8Array(analyser.frequencyBinCount);
                const sampleRate = audioContext.sampleRate;
                const binCount = analyser.frequencyBinCount;
                // Each frequency bin covers this many Hz
                const hzPerBin = sampleRate / analyser.fftSize;

                // Human voice band: ~300 Hz to 3400 Hz
                const voiceLowBin = Math.floor(300 / hzPerBin);
                const voiceHighBin = Math.ceil(3400 / hzPerBin);

                setAudioActive(true);

                intervalId = setInterval(() => {
                    analyser.getByteFrequencyData(dataArray);

                    // Energy inside the human-voice frequency band
                    let voiceEnergy = 0;
                    for (let i = voiceLowBin; i <= voiceHighBin; i++) {
                        voiceEnergy += dataArray[i];
                    }
                    const voiceAvg = voiceEnergy / (voiceHighBin - voiceLowBin + 1);

                    // Energy OUTSIDE the voice band (low rumble + high hiss) = background noise
                    let noiseEnergy = 0;
                    let noiseCount = 0;
                    for (let i = 0; i < binCount; i++) {
                        if (i < voiceLowBin || i > voiceHighBin) {
                            noiseEnergy += dataArray[i];
                            noiseCount++;
                        }
                    }
                    const noiseAvg = noiseEnergy / (noiseCount || 1);

                    // Speech is present if voice-band energy is clearly above the
                    // background noise floor AND above a small absolute minimum
                    const isSpeech = voiceAvg > 20 && voiceAvg > noiseAvg * 2.0;

                    if (isSpeech) {
                        loudFrameCount++;
                    } else {
                        loudFrameCount = 0;
                    }

                    if (loudFrameCount >= 6) { // 6 frames * 0.5s = 3 seconds of sustained sound
                        handleAudioViolation();
                        loudFrameCount = 0;
                    }
                }, 500);
            } catch (err) {
                console.error("Microphone access error:", err);
            }
        }

        async function handleAudioViolation() {
            pushAlert("Voice/talking detected", "audio");

            try {
                await apiCall(`/exams/${examId}/violations`, "POST", {
                    violation_type: "AI: Voice/talking detected",
                    details: "Audio monitoring detected sustained sound",
                });
            } catch (err) {
                console.error("Failed to log audio violation:", err);
            }
        }

        startAudioMonitoring();

        return () => {
            if (intervalId) clearInterval(intervalId);
            if (audioContext) audioContext.close();
            if (audioStream) {
                audioStream.getTracks().forEach((track) => track.stop());
            }
        };
    }, [isFullscreen, exam, examTerminated, examId]);

    async function loadExam() {
        try {
            const data = await apiCall(`/exams/${examId}`, "GET");
            const now = new Date();
            const startTime = new Date(data.start_time);
            const endTime = new Date(data.end_time);

            if (now < startTime) {
                setError(`This exam hasn't started yet. It begins at ${startTime.toLocaleString()}`);
                setLoading(false);
                return;
            }
            if (now > endTime) {
                setError("This exam has ended. The access window has closed.");
                setLoading(false);
                return;
            }
            setExam(data);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    function selectAnswer(questionId, optionText) {
        setAnswers((prev) => ({ ...prev, [questionId]: optionText }));
    }

    function enterFullscreen() {
        document.documentElement.requestFullscreen().catch((err) => {
            console.log("Fullscreen request failed:", err);
        });
    }

    async function logViolation(message, level) {
        if (level === 1) {
            pushAlert(message, "level1");
        }

        try {
            await apiCall(`/exams/${examId}/violations`, "POST", {
                violation_type: message,
                details: `Level ${level} violation`,
            });
        } catch (err) {
            console.error("Failed to log violation:", err);
        }

        if (level === 2) {
            const newCount = level2Count + 1;
            setLevel2Count(newCount);
            if (newCount >= MAX_LEVEL2_VIOLATIONS) {
                terminateExam();
            } else {
                setLevel2Modal({ message, count: newCount });
            }
        }
    }

    async function terminateExam() {
        setExamTerminated(true);

        // Tell the server this session is terminated (blocks re-entry)
        try {
            await apiCall(`/exams/${examId}/terminate`, "POST");
        } catch (err) {
            console.error("Failed to mark session terminated:", err);
        }

        if (document.fullscreenElement) {
            await document.exitFullscreen();
        }
        setTimeout(() => {
            navigate("/dashboard");
        }, 5000);
    }
    async function handleSubmit() {
        setSubmitting(true);
        setError("");
        try {
            const data = await apiCall(`/exams/${examId}/submit`, "POST", { answers });
            setResult(data);
            if (document.fullscreenElement) {
                await document.exitFullscreen();
            }
        } catch (err) {
            setError(err.message);
        } finally {
            setSubmitting(false);
        }
    }

    if (loading) return <div style={{ padding: "40px" }}>Loading exam...</div>;

    if (error && !exam) return (
        <div style={{ padding: "40px", textAlign: "center" }}>
            <div style={styles.errorBox}>{error}</div>
            <button onClick={() => navigate("/dashboard")} style={styles.backBtn}>
                Back to Dashboard
            </button>
        </div>
    );

    if (examTerminated) return (
        <div style={styles.terminatedScreen}>
            <div style={styles.terminatedCard}>
                <div style={{ fontSize: "48px" }}>🚫</div>
                <h1 style={{ color: "#dc2626" }}>Exam Terminated</h1>
                <p>Due to high violations your exam has been ended.</p>
                <p>Try next time.</p>
                <p style={{ color: "#888", fontSize: "13px" }}>
                    Redirecting to dashboard in 5 seconds...
                </p>
            </div>
        </div>
    );

    if (result) return (
        <div style={styles.centeredScreen}>
            <div style={styles.resultCard}>
                <div style={{ fontSize: "48px" }}>🎉</div>
                <h1>Exam Submitted!</h1>
                <p style={styles.scoreText}>
                    Your Score: {result.score} / {result.total_questions}
                </p>
                <button onClick={() => navigate("/dashboard")} style={styles.backBtn}>
                    Back to Dashboard
                </button>
            </div>
        </div>
    );
    // Terms & Conditions gate — must agree before anything else
    if (exam && !agreedToTerms) return (
        <div style={styles.termsScreen}>
            <div style={styles.termsCard}>
                <div style={styles.termsHeader}>
                    <div style={{ fontSize: "40px" }}>📋</div>
                    <h1 style={styles.termsTitle}>Exam Terms & Conditions</h1>
                    <p style={styles.termsSubtitle}>{exam.title}</p>
                </div>

                <div style={styles.termsBody}>
                    <div style={styles.termItem}>
                        <span style={styles.termIcon}>⏱️</span>
                        <div>
                            <p style={styles.termHeading}>Time Limit</p>
                            <p style={styles.termText}>
                                You have {exam.duration_minutes} minutes to complete this exam,
                                which contains {exam.questions.length} question{exam.questions.length !== 1 ? "s" : ""}.
                                The exam must be completed in one sitting.
                            </p>
                        </div>
                    </div>

                    <div style={styles.termItem}>
                        <span style={styles.termIcon}>🖥️</span>
                        <div>
                            <p style={styles.termHeading}>Fullscreen Required</p>
                            <p style={styles.termText}>
                                The exam must be taken in fullscreen mode. Exiting fullscreen at any
                                time will be recorded as a violation.
                            </p>
                        </div>
                    </div>

                    <div style={styles.termItem}>
                        <span style={styles.termIcon}>📷</span>
                        <div>
                            <p style={styles.termHeading}>Webcam & Microphone Monitoring</p>
                            <p style={styles.termText}>
                                Your webcam and microphone will be active throughout the exam. AI
                                proctoring monitors your face, gaze, and surroundings, and detects talking.
                                Ensure you are alone in a quiet, well-lit room.
                            </p>
                        </div>
                    </div>

                    <div style={styles.termItem}>
                        <span style={styles.termIcon}>🚫</span>
                        <div>
                            <p style={styles.termHeading}>Prohibited Actions</p>
                            <p style={styles.termText}>
                                Switching tabs, copying/pasting, right-clicking, using keyboard shortcuts,
                                and using phones, books, or other devices are strictly prohibited and will
                                be logged as violations.
                            </p>
                        </div>
                    </div>

                    <div style={styles.termItem}>
                        <span style={styles.termIcon}>👥</span>
                        <div>
                            <p style={styles.termHeading}>No Other Persons</p>
                            <p style={styles.termText}>
                                Only you may appear on camera. The presence of additional faces will be
                                detected and recorded as a violation.
                            </p>
                        </div>
                    </div>

                    <div style={styles.termItem}>
                        <span style={styles.termIcon}>⚠️</span>
                        <div>
                            <p style={styles.termHeading}>3-Strike Termination Policy</p>
                            <p style={styles.termText}>
                                Serious violations (tab switching, exiting fullscreen) are tracked. After
                                {" "}{MAX_LEVEL2_VIOLATIONS} serious violations, your exam will be automatically
                                terminated and you will not be able to retake it.
                            </p>
                        </div>
                    </div>

                    <div style={styles.termItem}>
                        <span style={styles.termIcon}>✅</span>
                        <div>
                            <p style={styles.termHeading}>Single Submission</p>
                            <p style={styles.termText}>
                                Your answers are scored automatically. Once submitted, the exam cannot be
                                retaken. Make sure to review your answers before submitting.
                            </p>
                        </div>
                    </div>
                </div>

                <div style={styles.termsFooter}>
                    <p style={styles.termsAgreeText}>
                        By clicking "I Agree & Continue", you confirm that you have read and understood
                        all the terms above and agree to be monitored during this exam.
                    </p>
                    <button
                        onClick={() => setAgreedToTerms(true)}
                        style={styles.agreeBtn}
                    >
                        I Agree & Continue
                    </button>
                    <button
                        onClick={() => navigate("/dashboard")}
                        style={styles.declineBtn}
                    >
                        Cancel & Return to Dashboard
                    </button>
                </div>
            </div>
        </div>
    );

    if (!isFullscreen) return (
        <div style={styles.centeredScreen}>
            <div style={styles.fullscreenGate}>
                <div style={{ fontSize: "48px" }}>🖥️</div>
                <h2>Fullscreen Required</h2>
                <p style={{ color: "#666", marginBottom: "24px" }}>
                    You must enter fullscreen mode before you can take this exam.
                    Exiting fullscreen during the exam will count as a violation.
                </p>
                <p style={styles.violationCounter}>
                    Level 2 Violations: {level2Count} / {MAX_LEVEL2_VIOLATIONS}
                </p>
                <button onClick={enterFullscreen} style={styles.fullscreenBtn}>
                    Enter Fullscreen & Start Exam
                </button>
                <button
                    onClick={() => navigate("/dashboard")}
                    style={{ ...styles.backBtn, marginTop: "12px" }}
                >
                    Back to Dashboard
                </button>
            </div>
        </div>
    );

    return (
        <div style={styles.examContainer}>
            {/* Level 2 blocking modal */}
            {level2Modal && (
                <div style={styles.modalOverlay}>
                    <div style={styles.modalBox}>
                        <div style={{ fontSize: "48px" }}>🚨</div>
                        <h2 style={styles.modalTitle}>Level 2 Violation</h2>
                        <p style={styles.modalMessage}>{level2Modal.message}</p>
                        <div style={styles.modalCount}>
                            Strike {level2Modal.count} of {MAX_LEVEL2_VIOLATIONS}
                        </div>
                        <p style={styles.modalWarning}>
                            Warning: {MAX_LEVEL2_VIOLATIONS - level2Modal.count} more Level 2 violation
                            {MAX_LEVEL2_VIOLATIONS - level2Modal.count !== 1 ? "s" : ""} will end your exam.
                        </p>
                        <button onClick={() => setLevel2Modal(null)} style={styles.modalBtn}>
                            I Understand, Continue
                        </button>
                    </div>
                </div>
            )}
            {/* Unified alert stack - top center */}
            <div style={styles.alertStack}>
                {alerts.map((alert) => (
                    <div
                        key={alert.id}
                        style={{
                            ...styles.alertItem,
                            ...(alert.type === "level1" ? styles.alertLevel1 : {}),
                            ...(alert.type === "ai" ? styles.alertAi : {}),
                            ...(alert.type === "audio" ? styles.alertAudio : {}),
                        }}
                    >
                        {alert.type === "level1" && "⚠️ "}
                        {alert.type === "ai" && "👁️ "}
                        {alert.type === "audio" && "🎤 "}
                        {alert.message}
                    </div>
                ))}
            </div>
            {/* Countdown timer - top left */}
            <div style={{
                ...styles.timerBox,
                ...(timeLeft !== null && timeLeft <= 60 ? styles.timerUrgent : {}),
            }}>
                <span style={styles.timerLabel}>⏱️ Time Left</span>
                <span style={styles.timerValue}>{formatTime(timeLeft)}</span>
            </div>
            <div style={styles.webcamContainer}>
                <video
                    id="proctorVideo"
                    autoPlay
                    playsInline
                    muted
                    style={styles.webcamVideo}
                />
                <div style={styles.webcamLabel}>
                    {cameraActive ? "🔴 Proctoring Active" : "📷 Camera starting..."}
                    {audioActive && " · 🎤 Mic On"}
                </div>
            </div>


            <div style={styles.examBox}>
                <div style={styles.examHeader}>
                    <h1 style={styles.examTitle}>{exam.title}</h1>
                    <p style={styles.examDesc}>{exam.description}</p>
                    <div style={styles.violationBadge}>
                        🚨 Level 2 Violations: {level2Count}/{MAX_LEVEL2_VIOLATIONS}
                    </div>
                </div>

                {error && <div style={styles.errorBox}>{error}</div>}

                {exam.questions.map((q, index) => (
                    <div key={q.id} style={styles.questionBlock}>
                        <p style={styles.questionText}>
                            {index + 1}. {q.question_text}
                        </p>
                        {["A", "B", "C", "D"].map((letter) => {
                            const optionText = q[`option_${letter.toLowerCase()}`];
                            return (
                                <label key={letter} style={{
                                    ...styles.optionLabel,
                                    background: answers[q.id] === optionText ? "#0D2540" : "#0A0E1A",
                                    border: answers[q.id] === optionText ? "1px solid #22D3EE" : "1px solid #1C2438",
                                }}>
                                    <input
                                        type="radio"
                                        name={`question-${q.id}`}
                                        checked={answers[q.id] === optionText}
                                        onChange={() => selectAnswer(q.id, optionText)}
                                        style={{ marginRight: "10px" }}
                                    />
                                    {letter}. {optionText}
                                </label>
                            );
                        })}
                    </div>
                ))}

                <button onClick={handleSubmit} disabled={submitting} style={styles.submitBtn}>
                    {submitting ? "Submitting..." : "Submit Exam"}
                </button>
            </div>
        </div>
    );
}

const styles = {
    centeredScreen: { minHeight: "100vh", display: "flex", justifyContent: "center", alignItems: "center", background: "#0A0E1A", fontFamily: "Inter, sans-serif", padding: "20px" },
    terminatedScreen: { minHeight: "100vh", display: "flex", justifyContent: "center", alignItems: "center", background: "#0A0E1A", fontFamily: "Inter, sans-serif" },
    terminatedCard: { background: "#0F1524", padding: "48px", borderRadius: "16px", textAlign: "center", maxWidth: "480px", border: "1px solid #5B2121", boxShadow: "0 0 40px rgba(239,68,68,0.15)" },
    fullscreenGate: { background: "#0F1524", padding: "48px", borderRadius: "16px", textAlign: "center", maxWidth: "480px", border: "1px solid #1C2438" },
    resultCard: { background: "#0F1524", padding: "48px", borderRadius: "16px", textAlign: "center", maxWidth: "400px", border: "1px solid #1C2438" },
    examContainer: { minHeight: "100vh", background: "#0A0E1A", fontFamily: "Inter, sans-serif" },
    examBox: { maxWidth: "760px", margin: "0 auto", padding: "40px 20px" },
    examHeader: { marginBottom: "32px", paddingBottom: "20px", borderBottom: "1px solid #1C2438" },
    examTitle: { fontSize: "28px", margin: "0 0 8px", color: "#F8FAFC", fontFamily: "'Space Grotesk', sans-serif" },
    examDesc: { color: "#64748B", margin: "0 0 12px" },
    violationBadge: { display: "inline-block", background: "#2A1215", color: "#FCA5A5", padding: "6px 14px", borderRadius: "20px", fontSize: "13px", fontWeight: "500", border: "1px solid #5B2121" },
    violationCounter: { background: "#2A1215", color: "#FCA5A5", padding: "8px 16px", borderRadius: "8px", fontSize: "14px", marginBottom: "16px", border: "1px solid #5B2121" },
    questionBlock: { marginBottom: "28px", padding: "20px", background: "#0F1524", borderRadius: "12px", border: "1px solid #1C2438" },
    questionText: { fontWeight: "600", fontSize: "15px", marginBottom: "14px", color: "#E2E8F0" },
    optionLabel: { display: "flex", alignItems: "center", padding: "12px 14px", borderRadius: "8px", cursor: "pointer", fontSize: "14px", marginBottom: "8px", transition: "all 0.15s", color: "#CBD5E1" },
    submitBtn: { width: "100%", padding: "14px", background: "#10B981", color: "#04140D", border: "none", borderRadius: "10px", fontSize: "16px", fontWeight: "600", cursor: "pointer", marginTop: "20px", boxShadow: "0 0 20px rgba(16,185,129,0.25)" },
    backBtn: { padding: "12px 24px", background: "#22D3EE", color: "#04141C", border: "none", borderRadius: "10px", cursor: "pointer", fontSize: "15px", fontWeight: "600", display: "block", width: "100%", textAlign: "center" },
    fullscreenBtn: { width: "100%", padding: "14px", background: "#22D3EE", color: "#04141C", border: "none", borderRadius: "10px", fontSize: "15px", fontWeight: "600", cursor: "pointer", marginBottom: "8px", boxShadow: "0 0 20px rgba(34,211,238,0.3)" },
    scoreText: { fontSize: "28px", fontWeight: "700", color: "#10B981", margin: "16px 0 24px", fontFamily: "'Space Grotesk', sans-serif" },
    errorBox: { background: "#2A1215", color: "#FCA5A5", padding: "12px", borderRadius: "8px", marginBottom: "16px", fontSize: "14px", border: "1px solid #5B2121" },
    webcamContainer: { position: "fixed", top: "20px", right: "20px", width: "200px", zIndex: 999, borderRadius: "12px", overflow: "hidden", boxShadow: "0 0 24px rgba(34,211,238,0.2)", border: "2px solid #22D3EE" },
    webcamVideo: { width: "100%", height: "150px", objectFit: "cover", display: "block", background: "#000", transform: "scaleX(-1)" },
    webcamLabel: { background: "#0C1120", color: "#E2E8F0", fontSize: "11px", fontWeight: "600", padding: "6px 10px", textAlign: "center" },
    modalOverlay: { position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(5,8,15,0.88)", display: "flex", justifyContent: "center", alignItems: "center", zIndex: 2000 },
    modalBox: { background: "#0F1524", padding: "40px", borderRadius: "16px", textAlign: "center", maxWidth: "440px", width: "90%", boxShadow: "0 0 50px rgba(239,68,68,0.2)", border: "2px solid #5B2121" },
    modalTitle: { fontSize: "24px", fontWeight: "700", color: "#EF4444", margin: "12px 0 8px", fontFamily: "'Space Grotesk', sans-serif" },
    modalMessage: { fontSize: "16px", color: "#E2E8F0", marginBottom: "16px" },
    modalCount: { display: "inline-block", background: "#2A1215", color: "#FCA5A5", padding: "8px 20px", borderRadius: "24px", fontSize: "16px", fontWeight: "700", marginBottom: "16px", border: "1px solid #5B2121" },
    modalWarning: { fontSize: "13px", color: "#64748B", marginBottom: "24px" },
    modalBtn: { width: "100%", padding: "14px", background: "#EF4444", color: "white", border: "none", borderRadius: "10px", fontSize: "15px", fontWeight: "600", cursor: "pointer" },
    alertStack: { position: "fixed", top: "16px", left: "50%", transform: "translateX(-50%)", display: "flex", flexDirection: "column", gap: "8px", zIndex: 1500, width: "340px", maxWidth: "90%" },
    alertItem: { padding: "11px 16px", borderRadius: "10px", fontSize: "13px", fontWeight: "600", textAlign: "center", boxShadow: "0 4px 20px rgba(0,0,0,0.4)", border: "1px solid transparent" },
    alertLevel1: { background: "#0C2E22", color: "#6EE7B7", border: "1px solid #1A5943" },
    alertAi: { background: "#2E2410", color: "#FCD34D", border: "1px solid #5B4718" },
    alertAudio: { background: "#1E1B3A", color: "#C4B5FD", border: "1px solid #4C3F91" },
    timerBox: { position: "fixed", top: "20px", left: "20px", background: "#0F1524", color: "#F8FAFC", padding: "10px 18px", borderRadius: "12px", zIndex: 999, display: "flex", flexDirection: "column", alignItems: "center", border: "1px solid #1C2438", minWidth: "90px" },
    timerUrgent: { background: "#2A1215", border: "1px solid #5B2121" },
    timerLabel: { fontSize: "11px", fontWeight: "600", color: "#64748B", marginBottom: "2px" },
    timerValue: { fontSize: "22px", fontWeight: "700", fontVariantNumeric: "tabular-nums", fontFamily: "'Space Grotesk', sans-serif" },
    termsScreen: { minHeight: "100vh", background: "#0A0E1A", fontFamily: "Inter, sans-serif", padding: "40px 20px", display: "flex", justifyContent: "center", alignItems: "flex-start" },
    termsCard: { background: "#0F1524", borderRadius: "16px", maxWidth: "640px", width: "100%", border: "1px solid #1C2438", overflow: "hidden" },
    termsHeader: { textAlign: "center", padding: "36px 40px 24px", borderBottom: "1px solid #1C2438" },
    termsTitle: { fontSize: "24px", fontWeight: "600", color: "#F8FAFC", margin: "12px 0 6px", fontFamily: "'Space Grotesk', sans-serif" },
    termsSubtitle: { fontSize: "15px", color: "#22D3EE", fontWeight: "600", margin: 0 },
    termsBody: { padding: "28px 40px", display: "flex", flexDirection: "column", gap: "20px" },
    termItem: { display: "flex", gap: "14px", alignItems: "flex-start" },
    termIcon: { fontSize: "22px", flexShrink: 0, marginTop: "2px" },
    termHeading: { fontSize: "15px", fontWeight: "700", color: "#E2E8F0", margin: "0 0 4px" },
    termText: { fontSize: "13px", color: "#64748B", lineHeight: "1.6", margin: 0 },
    termsFooter: { padding: "24px 40px 32px", borderTop: "1px solid #1C2438", background: "#0C1120" },
    termsAgreeText: { fontSize: "13px", color: "#94A3B8", lineHeight: "1.6", marginBottom: "20px", textAlign: "center" },
    agreeBtn: { width: "100%", padding: "14px", background: "#22D3EE", color: "#04141C", border: "none", borderRadius: "10px", fontSize: "16px", fontWeight: "600", cursor: "pointer", marginBottom: "12px", boxShadow: "0 0 20px rgba(34,211,238,0.3)" },
    declineBtn: { width: "100%", padding: "12px", background: "transparent", color: "#64748B", border: "1px solid #1E293B", borderRadius: "10px", fontSize: "14px", fontWeight: "500", cursor: "pointer" },
};

export default ExamPage;

//uvicorn app.main:app --reload
//npm run dev
//cd backend
//cd frontend
//docker compose up -d
//docker compose down