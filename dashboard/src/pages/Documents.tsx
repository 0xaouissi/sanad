import { useCallback, useEffect, useRef, useState } from "react";
import { DocumentOut, api } from "../api";
import { Dict } from "../i18n";

const STATUS_LABEL: Record<DocumentOut["status"], keyof Dict> = {
  pending: "statusPending",
  processing: "statusProcessing",
  ready: "statusReady",
  failed: "statusFailed",
};

export function Documents({
  t,
  isOwner,
  onError,
}: {
  t: Dict;
  isOwner: boolean;
  onError: (e: unknown) => void;
}) {
  const [docs, setDocs] = useState<DocumentOut[] | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    api
      .documents()
      .then(setDocs)
      .catch(onError);
  }, [onError]);

  useEffect(load, [load]);

  // Ingestion runs in the background; refresh while anything is in flight.
  useEffect(() => {
    if (!docs?.some((d) => d.status === "pending" || d.status === "processing")) return;
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, [docs, load]);

  async function upload() {
    const file = fileInput.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      await api.uploadDocument(file);
      if (fileInput.current) fileInput.current.value = "";
      load();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  async function remove(doc: DocumentOut) {
    if (!window.confirm(t.confirmDeleteDocument)) return;
    try {
      await api.deleteDocument(doc.id);
      load();
    } catch (e) {
      onError(e);
    }
  }

  async function reindex(doc: DocumentOut) {
    if (!window.confirm(t.confirmReindex)) return;
    try {
      await api.reindexDocument(doc.id);
      load();
    } catch (e) {
      onError(e);
    }
  }

  return (
    <section className="panel">
      <h2>{t.documents}</h2>
      {isOwner && (
        <div className="row" style={{ marginBottom: 12 }}>
          <input
            ref={fileInput}
            id="doc-file"
            type="file"
            accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg"
            style={{ width: "auto" }}
          />
          <button className="primary" id="doc-upload" disabled={busy} onClick={upload}>
            {busy ? t.uploading : t.upload}
          </button>
        </div>
      )}
      {docs === null ? (
        <p className="muted">{t.loading}</p>
      ) : docs.length === 0 ? (
        <p className="muted">{t.noDocuments}</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>{t.filename}</th>
              <th>{t.status}</th>
              <th>{t.chunks}</th>
              {isOwner && <th>{t.actions}</th>}
            </tr>
          </thead>
          <tbody>
            {docs.map((doc) => (
              <tr key={doc.id}>
                <td>
                  {doc.filename}
                  {doc.error && <div className="muted">{doc.error}</div>}
                </td>
                <td>
                  <span className={`badge ${doc.status}`}>{t[STATUS_LABEL[doc.status]]}</span>
                </td>
                <td>{doc.chunk_count}</td>
                {isOwner && (
                  <td>
                    <div className="row">
                      <button className="ghost" onClick={() => reindex(doc)}>
                        {t.reindex}
                      </button>
                      <button className="danger" onClick={() => remove(doc)}>
                        {t.delete}
                      </button>
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}