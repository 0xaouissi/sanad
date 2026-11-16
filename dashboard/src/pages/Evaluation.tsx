import { useCallback, useEffect, useState } from "react";
import { EvalCaseResult, EvalState, api } from "../api";
import { Dict } from "../i18n";

const CHECK_LABELS: Record<string, keyof Dict> = {
  facts: "checkFacts",
  citations: "checkCitations",
  refusal: "checkRefusal",
  no_citations: "checkNoCitations",
  no_prompt_leak: "checkNoPromptLeak",
};

const CATEGORY_LABELS: Record<string, keyof Dict> = {
  grounded: "grounded",
  out_of_scope: "outOfScope",
  injection: "injection",
};

export function Evaluation({
  t,
  isOwner,
  onError,
}: {
  t: Dict;
  isOwner: boolean;
  onError: (e: unknown) => void;
}) {
  const [state, setState] = useState<EvalState | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .evalState()
      .then(setState)
      .catch(onError);
  }, [onError]);

  useEffect(() => {
    load();
  }, [load]);

  const running = state?.status === "running";

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [running, load]);

  const run = async () => {
    setBusy(true);
    try {
      await api.runEval();
      load();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };

  const categoryLabel = (c: string) => t[CATEGORY_LABELS[c] ?? "category"];
  const failedChecks = (r: EvalCaseResult) =>
    Object.entries(r.checks)
      .filter(([, ok]) => !ok)
      .map(([name]) => t[CHECK_LABELS[name] ?? "result"])
      .join(", ");

  return (
    <section className="panel">
      <h2>{t.evaluation}</h2>
      <p className="muted">{t.evalHint}</p>
      {state === null ? (
        <p className="muted">{t.loading}</p>
      ) : (
        <>
          {!state.documents_ready && (
            <div className="banner error" role="alert">
              {t.documentsMissing}
            </div>
          )}
          <div className="row">
            {isOwner && (
              <button id="run-eval" onClick={run} disabled={busy || running}>
                {running ? t.evalRunning : t.runEval}
              </button>
            )}
            {state.status === "idle" && <span className="muted">{t.evalIdle}</span>}
            {running && (
              <span id="eval-progress" className="muted">
                {t.progress}: {state.completed ?? 0}/{state.total ?? state.golden.total}
              </span>
            )}
            {state.status === "done" && (
              <span className="badge ready" id="eval-status">
                {t.evalDone}
              </span>
            )}
          </div>
          {state.status === "failed" && (
            <div className="banner error" role="alert" id="eval-error">
              {t.evalFailed}: {state.error}
            </div>
          )}
          <h3>{t.questionsPerLanguage}</h3>
          <table id="golden-languages">
            <thead>
              <tr>
                <th>{t.language}</th>
                <th>{t.question}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(state.golden.per_language).map(([code, count]) => (
                <tr key={code}>
                  <td>{code}</td>
                  <td>{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {state.summary && (
            <>
              <h3>
                {t.result}: {state.summary.passed}/{state.summary.total} {t.passed}
              </h3>
              <table id="eval-summary">
                <thead>
                  <tr>
                    <th>{t.language}</th>
                    <th>{t.category}</th>
                    <th>{t.passed}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(state.summary.per_language).map(([code, b]) => (
                    <tr key={`lang-${code}`}>
                      <td>{code}</td>
                      <td>—</td>
                      <td>
                        {b.passed}/{b.total}
                      </td>
                    </tr>
                  ))}
                  {Object.entries(state.summary.per_category).map(([cat, b]) => (
                    <tr key={`cat-${cat}`}>
                      <td>—</td>
                      <td>{categoryLabel(cat)}</td>
                      <td>
                        {b.passed}/{b.total}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {state.results && state.results.length > 0 && (
            <table id="eval-results">
              <thead>
                <tr>
                  <th>{t.result}</th>
                  <th>{t.question}</th>
                  <th>{t.language}</th>
                  <th>{t.category}</th>
                  <th>{t.answer}</th>
                </tr>
              </thead>
              <tbody>
                {state.results.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <span className={r.passed ? "badge ready" : "badge failed"}>
                        {r.passed ? t.pass : t.fail}
                      </span>
                      {!r.passed && <div className="muted">{failedChecks(r)}</div>}
                    </td>
                    <td>{r.question}</td>
                    <td>{r.language}</td>
                    <td>{categoryLabel(r.category)}</td>
                    <td className="muted">{r.answer.slice(0, 160)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}