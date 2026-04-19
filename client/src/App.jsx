import React, { useState, useRef, useEffect, useCallback } from "react";
import axios from "axios";

// ─────────────────────────────────────────────────────────────────────────────
// Utility
// ─────────────────────────────────────────────────────────────────────────────

const api = axios.create({ baseURL: "/api", timeout: 150000 });

function cx(...classes) {
  return classes.filter(Boolean).join(" ");
}

// ─────────────────────────────────────────────────────────────────────────────
// Badge
// ─────────────────────────────────────────────────────────────────────────────

const STUDY_META = {
  human_rct:               { label: "RCT",              color: "bg-green-100 text-green-800 border-green-200" },
  human_systematic_review: { label: "Systematic Review", color: "bg-blue-100 text-blue-800 border-blue-200" },
  human_meta_analysis:     { label: "Meta-Analysis",     color: "bg-blue-100 text-blue-800 border-blue-200" },
  human_cohort:            { label: "Cohort Study",      color: "bg-teal-100 text-teal-800 border-teal-200" },
  human_observational:     { label: "Observational",     color: "bg-cyan-100 text-cyan-800 border-cyan-200" },
  human_case_control:      { label: "Case-Control",      color: "bg-indigo-100 text-indigo-800 border-indigo-200" },
  human_case_report:       { label: "Case Report",       color: "bg-yellow-100 text-yellow-800 border-yellow-200" },
  animal:                  { label: "Animal Study",      color: "bg-orange-100 text-orange-800 border-orange-200" },
  in_vitro:                { label: "In Vitro",          color: "bg-red-100 text-red-800 border-red-200" },
  unknown:                 { label: "Research",          color: "bg-gray-100 text-gray-700 border-gray-200" },
};

function StudyBadge({ type }) {
  const meta = STUDY_META[type] || STUDY_META.unknown;
  return (
    <span className={cx("text-xs font-medium px-2 py-0.5 rounded-full border", meta.color)}>
      {meta.label}
    </span>
  );
}

function StatusBadge({ status }) {
  const colors = {
    RECRUITING:              "bg-green-100 text-green-800 border-green-200",
    ACTIVE_NOT_RECRUITING:   "bg-blue-100 text-blue-800 border-blue-200",
    COMPLETED:               "bg-gray-100 text-gray-700 border-gray-200",
    NOT_YET_RECRUITING:      "bg-yellow-100 text-yellow-800 border-yellow-200",
    ENROLLING_BY_INVITATION: "bg-purple-100 text-purple-800 border-purple-200",
  };
  return (
    <span className={cx("text-xs font-medium px-2 py-0.5 rounded-full border", colors[status] || colors.COMPLETED)}>
      {status?.replace(/_/g, " ")}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Confidence bar
// ─────────────────────────────────────────────────────────────────────────────

function ConfidenceBar({ score }) {
  const pct   = Math.round((score || 0) * 100);
  const color = pct >= 70 ? "bg-emerald-500" : pct >= 45 ? "bg-amber-400" : "bg-rose-400";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-gray-100 rounded-full h-1.5 overflow-hidden">
        <div className={cx(color, "h-1.5 rounded-full transition-all duration-500")} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-400 tabular-nums w-8 text-right">{pct}%</span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Publication Card
// ─────────────────────────────────────────────────────────────────────────────

function PublicationCard({ insight, onBookmark, isBookmarked, userId }) {
  const [expanded, setExpanded] = useState(false);
  const [bookmarking, setBookmarking] = useState(false);

  const handleBookmark = async () => {
    if (!userId || isBookmarked) return;
    setBookmarking(true);
    try {
      await onBookmark({
        type:    "paper",
        item_id: insight.paper_id,
        title:   insight.title,
        url:     insight.url,
        source:  insight.source,
        year:    insight.year,
      });
    } finally {
      setBookmarking(false);
    }
  };

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm hover:shadow-md transition-all duration-200 flex flex-col gap-2">
      {/* Top row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap gap-1">
          <StudyBadge type={insight.study_subject} />
          {insight.is_open_access && (
            <span className="text-xs bg-emerald-50 text-emerald-700 border border-emerald-200 px-2 py-0.5 rounded-full">
              Open Access
            </span>
          )}
          {insight.cited_by_count > 100 && (
            <span className="text-xs bg-purple-50 text-purple-700 border border-purple-200 px-2 py-0.5 rounded-full">
              {insight.cited_by_count.toLocaleString()} citations
            </span>
          )}
          {insight.grounding_tag === "partially_supported" && (
            <span className="text-xs bg-yellow-50 text-yellow-700 border border-yellow-200 px-2 py-0.5 rounded-full">
              Partial support
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-xs text-gray-400">{insight.year}</span>
          {userId && (
            <button
              onClick={handleBookmark}
              disabled={isBookmarked || bookmarking}
              title={isBookmarked ? "Bookmarked" : "Bookmark this paper"}
              className={cx(
                "text-lg transition-all",
                isBookmarked ? "opacity-100" : "opacity-30 hover:opacity-80",
                bookmarking && "animate-pulse"
              )}>
              {isBookmarked ? "🔖" : "🔖"}
            </button>
          )}
        </div>
      </div>

      {/* Title */}
      <a href={insight.url} target="_blank" rel="noreferrer"
         className="text-sm font-semibold text-blue-700 hover:text-blue-900 hover:underline leading-snug">
        {insight.title}
      </a>

      {/* Authors */}
      {insight.authors?.length > 0 && (
        <p className="text-xs text-gray-400 leading-snug">
          {insight.authors.slice(0, 3).join(", ")}
          {insight.authors.length > 3 ? " et al." : ""}
          {insight.journal ? ` · ${insight.journal}` : ""}
        </p>
      )}

      {/* Confidence */}
      <ConfidenceBar score={insight.confidence_score} />

      {/* Key finding */}
      <p className="text-sm text-gray-800 leading-relaxed">{insight.key_finding}</p>

      {/* Supporting snippet */}
      {insight.supporting_snippet && (
        <blockquote className="border-l-4 border-blue-200 pl-3 text-xs text-gray-500 italic leading-relaxed">
          "{insight.supporting_snippet}"
        </blockquote>
      )}

      {/* Expanded detail */}
      {expanded && insight.relevance_explanation && (
        <p className="text-xs text-gray-600 leading-relaxed bg-gray-50 rounded-lg p-2.5">
          {insight.relevance_explanation}
        </p>
      )}

      <button onClick={() => setExpanded(e => !e)}
              className="text-xs text-blue-500 hover:text-blue-700 self-start mt-0.5">
        {expanded ? "Show less ↑" : "Why relevant ↓"}
      </button>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Trial Card
// ─────────────────────────────────────────────────────────────────────────────

function TrialCard({ trial, onBookmark, isBookmarked, userId }) {
  const [expanded, setExpanded] = useState(false);

  const locations = (trial.locations || []).slice(0, 4)
    .map(l => [l.city, l.country].filter(Boolean).join(", "))
    .filter(Boolean);

  const contact = (trial.contacts || [])[0];

  const handleBookmark = async () => {
    if (!userId || isBookmarked) return;
    await onBookmark({
      type:    "trial",
      item_id: trial.nct_id,
      title:   trial.title,
      url:     trial.url,
      source:  "clinicaltrials",
    });
  };

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm hover:shadow-md transition-all duration-200 flex flex-col gap-2">
      {/* Top row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap gap-1">
          <StatusBadge status={trial.status} />
          {trial.phase && (
            <span className="text-xs bg-indigo-50 text-indigo-700 border border-indigo-200 px-2 py-0.5 rounded-full">
              {trial.phase}
            </span>
          )}
          {trial.enrollment && (
            <span className="text-xs bg-gray-50 text-gray-600 border border-gray-200 px-2 py-0.5 rounded-full">
              n={trial.enrollment.toLocaleString()}
            </span>
          )}
        </div>
        {userId && (
          <button onClick={handleBookmark} disabled={isBookmarked}
                  className={cx("text-lg transition-all shrink-0", isBookmarked ? "opacity-100" : "opacity-30 hover:opacity-80")}>
            🔖
          </button>
        )}
      </div>

      {/* Title */}
      <a href={trial.url} target="_blank" rel="noreferrer"
         className="text-sm font-semibold text-blue-700 hover:underline leading-snug">
        {trial.title}
      </a>

      <p className="text-xs text-gray-400">NCT: {trial.nct_id}</p>

      {/* Relevance note */}
      {trial.relevance_note && (
        <p className="text-sm text-gray-700 leading-relaxed">{trial.relevance_note}</p>
      )}

      {/* Locations */}
      {locations.length > 0 && (
        <p className="text-xs text-gray-500">📍 {locations.join(" · ")}</p>
      )}

      {/* Eligibility summary */}
      {trial.eligibility?.min_age && (
        <p className="text-xs text-gray-500">
          Age: {trial.eligibility.min_age} – {trial.eligibility.max_age || "no limit"} · {trial.eligibility.gender || "All"}
        </p>
      )}

      {/* Inclusion criteria (expanded) */}
      {expanded && trial.eligibility?.inclusion?.length > 0 && (
        <div className="bg-green-50 rounded-lg p-2.5 space-y-1">
          <p className="text-xs font-medium text-green-800">Inclusion criteria:</p>
          {trial.eligibility.inclusion.slice(0, 5).map((c, i) => (
            <p key={i} className="text-xs text-green-700">· {c}</p>
          ))}
        </div>
      )}

      {expanded && trial.eligibility?.exclusion?.length > 0 && (
        <div className="bg-red-50 rounded-lg p-2.5 space-y-1">
          <p className="text-xs font-medium text-red-800">Exclusion criteria:</p>
          {trial.eligibility.exclusion.slice(0, 5).map((c, i) => (
            <p key={i} className="text-xs text-red-700">· {c}</p>
          ))}
        </div>
      )}

      {/* Contact */}
      {contact && (
        <div className="bg-gray-50 rounded-lg p-2.5">
          <p className="text-xs font-medium text-gray-700">{contact.name}</p>
          {contact.email && <p className="text-xs text-blue-600">{contact.email}</p>}
          {contact.phone && <p className="text-xs text-gray-500">{contact.phone}</p>}
        </div>
      )}

      <button onClick={() => setExpanded(e => !e)}
              className="text-xs text-blue-500 hover:text-blue-700 self-start">
        {expanded ? "Show less ↑" : "Eligibility criteria ↓"}
      </button>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Sources Panel
// ─────────────────────────────────────────────────────────────────────────────

function SourcesPanel({ sources }) {
  const [open, setOpen] = useState(false);
  if (!sources?.length) return null;
  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden">
      <button onClick={() => setOpen(o => !o)}
              className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-50 hover:bg-gray-100 text-sm text-gray-600 transition-colors">
        <span>📚 Source Attribution ({sources.length})</span>
        <span className="text-gray-400">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="divide-y divide-gray-100">
          {sources.map((s, i) => (
            <div key={i} className="px-4 py-3 bg-white">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <a href={s.url} target="_blank" rel="noreferrer"
                     className="text-sm font-medium text-blue-700 hover:underline block truncate">
                    {s.title}
                  </a>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {s.authors?.slice(0, 2).join(", ")}{s.authors?.length > 2 ? " et al." : ""} · {s.year} · {s.platform?.toUpperCase()}
                    {s.journal ? ` · ${s.journal}` : ""}
                  </p>
                  {s.snippet && (
                    <p className="text-xs text-gray-600 mt-1 italic">"{s.snippet}"</p>
                  )}
                </div>
                <div className="shrink-0 flex flex-col gap-0.5 items-end">
                  <StudyBadge type={s.study_subject} />
                  {s.is_open_access && (
                    <span className="text-xs text-emerald-600">Open</span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Pipeline Panel
// ─────────────────────────────────────────────────────────────────────────────

function PipelinePanel({ data }) {
  const [open, setOpen] = useState(false);
  const { pipeline, hyde_queries, retrieval_verdict, corrective_rag } = data;

  const verdictColor = {
    correct:   "bg-green-50 text-green-700 border-green-200",
    ambiguous: "bg-yellow-50 text-yellow-700 border-yellow-200",
    incorrect: "bg-red-50 text-red-700 border-red-200",
  }[retrieval_verdict] || "bg-gray-50 text-gray-600 border-gray-200";

  return (
    <div className="border border-dashed border-gray-200 rounded-xl overflow-hidden">
      <button onClick={() => setOpen(o => !o)}
              className="w-full flex items-center justify-between px-4 py-2 text-xs text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition-colors">
        <span>🔬 Pipeline transparency</span>
        <span>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="px-4 pb-4 pt-1 space-y-3">
          {/* HyDE queries */}
          {hyde_queries?.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-600 mb-1.5">HyDE query variants:</p>
              <div className="space-y-1">
                {hyde_queries.map((q, i) => (
                  <p key={i} className="text-xs text-gray-500 bg-gray-50 rounded px-2 py-1">
                    <span className="text-gray-400 mr-1">#{i + 1}</span>{q}
                  </p>
                ))}
              </div>
            </div>
          )}

          {/* Funnel metrics */}
          <div className="grid grid-cols-3 gap-2 text-center">
            {[
              { label: "Retrieved",    value: pipeline?.papers_retrieved },
              { label: "After filter", value: pipeline?.papers_after_prefilter },
              { label: "After embed",  value: pipeline?.papers_after_semantic },
              { label: "Final",        value: pipeline?.papers_after_rerank },
              { label: "Groq calls",   value: pipeline?.groq_calls_made },
              { label: "Total time",   value: pipeline?.total_ms ? `${pipeline.total_ms}ms` : "—" },
            ].map(({ label, value }) => (
              <div key={label} className="bg-gray-50 rounded-lg px-2 py-1.5">
                <p className="text-xs font-semibold text-gray-700">{value ?? "—"}</p>
                <p className="text-xs text-gray-400">{label}</p>
              </div>
            ))}
          </div>

          {/* Stage timings */}
          {pipeline && (
            <div className="space-y-1">
              {[
                ["HyDE expansion",   pipeline.hyde_expansion_ms],
                ["API retrieval",    pipeline.retrieval_ms],
                ["Embedding",        pipeline.embedding_ms],
                ["Rerank + RAG",     pipeline.rerank_ms],
                ["Corrective RAG",   pipeline.corrective_rag_ms],
                ["Synthesis",        pipeline.synthesis_ms],
              ].filter(([, v]) => v != null).map(([label, ms]) => (
                <div key={label} className="flex items-center justify-between text-xs text-gray-500">
                  <span>{label}</span>
                  <span className="font-mono text-gray-600">{ms}ms</span>
                </div>
              ))}
            </div>
          )}

          {/* Verdict */}
          <div className={cx("rounded-lg px-3 py-1.5 border text-xs font-medium", verdictColor)}>
            Retrieval verdict: <strong>{retrieval_verdict}</strong>
            {corrective_rag?.fired && (
              <span className="ml-2 text-blue-600">· Corrective RAG fired ✓ (+{corrective_rag.reretrieval_count} papers)</span>
            )}
          </div>

          {corrective_rag?.weak_aspects?.length > 0 && (
            <div>
              <p className="text-xs text-gray-500">Weak aspects detected:</p>
              {corrective_rag.weak_aspects.map((a, i) => (
                <p key={i} className="text-xs text-gray-400 ml-2">· {a}</p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Loading dots
// ─────────────────────────────────────────────────────────────────────────────

const LOADING_MESSAGES = [
  "Expanding query with HyDE...",
  "Searching PubMed, OpenAlex, ClinicalTrials...",
  "Running semantic ranking...",
  "Applying Self-RAG filtering...",
  "Synthesising research insights...",
];

function LoadingIndicator() {
  const [msgIdx, setMsgIdx] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setMsgIdx(i => (i + 1) % LOADING_MESSAGES.length), 2500);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="flex items-center gap-3 text-gray-500 text-sm py-2">
      <div className="flex gap-1">
        {[0, 1, 2].map(i => (
          <div key={i} className="w-2 h-2 bg-blue-400 rounded-full animate-bounce"
               style={{ animationDelay: `${i * 0.15}s` }} />
        ))}
      </div>
      <span className="transition-all">{LOADING_MESSAGES[msgIdx]}</span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Bookmarks sidebar
// ─────────────────────────────────────────────────────────────────────────────

function BookmarksSidebar({ bookmarks, onClose }) {
  return (
    <div className="fixed inset-y-0 right-0 w-80 bg-white border-l border-gray-200 shadow-xl z-50 flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <h2 className="font-semibold text-gray-800">Bookmarks ({bookmarks.length})</h2>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {bookmarks.length === 0 ? (
          <p className="text-sm text-gray-400 text-center mt-8">No bookmarks yet</p>
        ) : (
          bookmarks.map((b, i) => (
            <div key={i} className="border border-gray-100 rounded-lg p-3">
              <span className="text-xs text-gray-400 uppercase">{b.type}</span>
              <a href={b.url} target="_blank" rel="noreferrer"
                 className="text-sm font-medium text-blue-700 hover:underline block mt-0.5 leading-snug">
                {b.title}
              </a>
              {b.year && <p className="text-xs text-gray-400 mt-0.5">{b.year} · {b.source}</p>}
              {b.notes && <p className="text-xs text-gray-500 mt-1 italic">{b.notes}</p>}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main App
// ─────────────────────────────────────────────────────────────────────────────

export default function App() {
  const [sessionId,     setSessionId]     = useState(null);
  const [messages,      setMessages]      = useState([]);
  const [loading,       setLoading]       = useState(false);
  const [error,         setError]         = useState(null);
  const [bookmarks,     setBookmarks]     = useState([]);
  const [showBookmarks, setShowBookmarks] = useState(false);

  // Form
  const [query,       setQuery]       = useState("");
  const [disease,     setDisease]     = useState("");
  const [patientName, setPatientName] = useState("");
  const [location,    setLocation]    = useState("");
  const [userId,      setUserId]      = useState("");
  const [started,     setStarted]     = useState(false);

  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // Load bookmarks when userId is set
  useEffect(() => {
    if (!userId) return;
    api.get(`/users/${userId}/bookmarks`)
      .then(r => setBookmarks(r.data.bookmarks || []))
      .catch(() => {});
  }, [userId]);

  const handleBookmark = useCallback(async (item) => {
    if (!userId) return;
    try {
      await api.post(`/users/${userId}/bookmarks`, item);
      setBookmarks(prev => [{ ...item, created_at: new Date() }, ...prev]);
    } catch (e) {
      console.error("Bookmark failed:", e);
    }
  }, [userId]);

  const submit = async (overrideQuery) => {
    const q = (overrideQuery || query).trim();
    if (!q || !disease.trim()) return;

    setLoading(true);
    setError(null);
    setMessages(prev => [...prev, { role: "user", text: q }]);
    setQuery("");

    try {
      const { data } = await api.post("/query", {
        query:        q,
        disease:      disease.trim(),
        patient_name: patientName || undefined,
        location:     location    || undefined,
        session_id:   sessionId   || undefined,
        user_id:      userId      || undefined,
      });

      if (!sessionId) setSessionId(data.session_id);
      setMessages(prev => [...prev, { role: "assistant", data }]);
    } catch (err) {
      const msg = err.response?.data?.error
        || err.response?.data?.detail
        || "Something went wrong. Please try again.";
      setError(typeof msg === "string" ? msg : JSON.stringify(msg));
      setMessages(prev => prev.slice(0, -1));
    } finally {
      setLoading(false);
    }
  };

  const isBookmarked = (id) => bookmarks.some(b => b.item_id === id);

  // ── Onboarding screen ───────────────────────────────────────────────────
  if (!started) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 via-blue-50 to-indigo-50 p-4">
        <div className="bg-white rounded-2xl shadow-xl p-8 w-full max-w-lg border border-gray-100">
          <div className="text-center mb-8">
            <div className="w-14 h-14 bg-blue-600 rounded-2xl flex items-center justify-center mx-auto mb-4 text-white text-2xl font-bold shadow-lg">C</div>
            <h1 className="text-2xl font-bold text-gray-900">Curalink</h1>
            <p className="text-gray-500 mt-1 text-sm">AI Medical Research Assistant</p>
          </div>

          <div className="space-y-4">
            <Field label="Disease of Interest *" value={disease} onChange={setDisease}
                   placeholder="e.g. Parkinson's disease" />
            <Field label="Your Query *" value={query} onChange={setQuery}
                   placeholder="e.g. Deep Brain Stimulation outcomes" />
            <div className="grid grid-cols-2 gap-3">
              <Field label="Your Name" value={patientName} onChange={setPatientName}
                     placeholder="John Smith" />
              <Field label="Location" value={location} onChange={setLocation}
                     placeholder="Toronto, Canada" />
            </div>
            <Field label="User ID (optional — for personalization)"
                   value={userId} onChange={setUserId}
                   placeholder="user_john_001" />

            <button
              onClick={() => { if (query.trim() && disease.trim()) { setStarted(true); submit(query); }}}
              disabled={!query.trim() || !disease.trim()}
              className="w-full bg-blue-600 text-white rounded-xl py-3 font-semibold hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm">
              Start Research Session →
            </button>
          </div>

          <p className="text-xs text-gray-400 text-center mt-4">
            Searches PubMed · OpenAlex · ClinicalTrials.gov
          </p>
        </div>
      </div>
    );
  }

  // ── Chat screen ─────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-5 py-3 flex items-center justify-between sticky top-0 z-10 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center text-white text-sm font-bold">C</div>
          <div>
            <h1 className="text-sm font-bold text-gray-900">Curalink</h1>
            <p className="text-xs text-gray-400">
              {disease}
              {location ? ` · ${location}` : ""}
              {patientName ? ` · ${patientName}` : ""}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {userId && (
            <button onClick={() => setShowBookmarks(true)}
                    className="flex items-center gap-1.5 text-xs text-gray-600 hover:text-gray-900 border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-50 transition-colors">
              🔖 <span>Bookmarks {bookmarks.length > 0 ? `(${bookmarks.length})` : ""}</span>
            </button>
          )}
          <button
            onClick={() => { setStarted(false); setMessages([]); setSessionId(null); setQuery(""); setDisease(""); setUserId(""); setBookmarks([]); }}
            className="text-xs text-gray-500 hover:text-gray-700 border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-50 transition-colors">
            New Session
          </button>
        </div>
      </header>

      {/* Messages */}
      <main className="flex-1 overflow-y-auto px-4 py-6 max-w-4xl w-full mx-auto space-y-6">
        {messages.map((msg, idx) => (
          <div key={idx}>
            {msg.role === "user" ? (
              <div className="flex justify-end">
                <div className="bg-blue-600 text-white px-4 py-2.5 rounded-2xl rounded-tr-sm max-w-sm text-sm shadow-sm">
                  {msg.text}
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Condition overview */}
                {msg.data.condition_overview && (
                  <div className="bg-blue-50 border border-blue-100 rounded-xl px-5 py-4">
                    <p className="text-xs font-semibold text-blue-600 uppercase tracking-wider mb-1.5">Overview</p>
                    <p className="text-sm text-gray-800 leading-relaxed">{msg.data.condition_overview}</p>
                  </div>
                )}

                {/* Publications */}
                {msg.data.research_insights?.length > 0 && (
                  <section>
                    <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
                      📄 Research Publications
                      <span className="bg-gray-100 text-gray-500 text-xs px-2 py-0.5 rounded-full">
                        {msg.data.research_insights.length}
                      </span>
                    </h3>
                    <div className="grid gap-3 sm:grid-cols-2">
                      {msg.data.research_insights.map((ins, i) => (
                        <PublicationCard
                          key={i} insight={ins}
                          onBookmark={handleBookmark}
                          isBookmarked={isBookmarked(ins.paper_id)}
                          userId={userId}
                        />
                      ))}
                    </div>
                  </section>
                )}

                {/* Clinical Trials */}
                {msg.data.clinical_trials?.length > 0 && (
                  <section>
                    <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
                      🧪 Clinical Trials
                      <span className="bg-gray-100 text-gray-500 text-xs px-2 py-0.5 rounded-full">
                        {msg.data.clinical_trials.length}
                      </span>
                    </h3>
                    <div className="grid gap-3 sm:grid-cols-2">
                      {msg.data.clinical_trials.map((t, i) => (
                        <TrialCard
                          key={i} trial={t}
                          onBookmark={handleBookmark}
                          isBookmarked={isBookmarked(t.nct_id)}
                          userId={userId}
                        />
                      ))}
                    </div>
                  </section>
                )}

                {/* Sources */}
                <SourcesPanel sources={msg.data.sources} />

                {/* Follow-up suggestions */}
                {msg.data.follow_up_suggestions?.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-gray-500 mb-2">Suggested follow-up questions:</p>
                    <div className="flex flex-wrap gap-2">
                      {msg.data.follow_up_suggestions.map((s, i) => (
                        <button key={i} onClick={() => submit(s.question)}
                                title={s.rationale}
                                className="text-xs bg-white border border-gray-200 text-gray-700 px-3 py-1.5 rounded-full hover:bg-blue-50 hover:border-blue-300 hover:text-blue-700 transition-colors text-left">
                          {s.question}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Pipeline */}
                <PipelinePanel data={msg.data} />
              </div>
            )}
          </div>
        ))}

        {loading && <LoadingIndicator />}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-700 flex items-start gap-2">
            <span className="text-red-400 mt-0.5">⚠️</span>
            <span>{error}</span>
          </div>
        )}

        <div ref={bottomRef} />
      </main>

      {/* Input */}
      <footer className="bg-white border-t border-gray-200 px-4 py-4 shadow-sm">
        <div className="max-w-4xl mx-auto flex gap-3">
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === "Enter" && !loading && submit()}
            placeholder={isFollowup(messages) ? "Ask a follow-up question..." : "Ask about this condition..."}
            disabled={loading}
            className="flex-1 border border-gray-300 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50 transition-all"
          />
          <button
            onClick={() => submit()}
            disabled={loading || !query.trim()}
            className="bg-blue-600 text-white px-5 py-2.5 rounded-xl text-sm font-semibold hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm">
            {loading ? "..." : "Send"}
          </button>
        </div>
      </footer>

      {/* Bookmarks sidebar */}
      {showBookmarks && (
        <>
          <div className="fixed inset-0 bg-black bg-opacity-20 z-40" onClick={() => setShowBookmarks(false)} />
          <BookmarksSidebar bookmarks={bookmarks} onClose={() => setShowBookmarks(false)} />
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function Field({ label, value, onChange, placeholder }) {
  return (
    <div>
      <label className="text-sm font-medium text-gray-700 block mb-1">{label}</label>
      <input
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
      />
    </div>
  );
}

function isFollowup(messages) {
  return messages.some(m => m.role === "assistant");
}
