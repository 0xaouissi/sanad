import { FormEvent, useCallback, useEffect, useState } from "react";
import { DashboardSettings, UserOut, api } from "../api";
import { Dict } from "../i18n";

export function SettingsPage({
  t,
  isOwner,
  onError,
}: {
  t: Dict;
  isOwner: boolean;
  onError: (e: unknown) => void;
}) {
  const [settings, setSettings] = useState<DashboardSettings | null>(null);
  const [domains, setDomains] = useState("");
  const [store, setStore] = useState(true);
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const [rotated, setRotated] = useState<{ api_key: string; site_key: string } | null>(null);
  const [deletedCount, setDeletedCount] = useState<number | null>(null);
  const [users, setUsers] = useState<UserOut[]>([]);
  const [viewerEmail, setViewerEmail] = useState("");
  const [viewerPassword, setViewerPassword] = useState("");

  const load = useCallback(() => {
    api
      .settings()
      .then((s) => {
        setSettings(s);
        setDomains(s.allowed_domains.join("\n"));
        setStore(s.store_conversations);
      })
      .catch(onError);
    if (isOwner) api.users().then(setUsers).catch(onError);
  }, [isOwner, onError]);

  useEffect(load, [load]);

  if (settings === null) {
    return (
      <section className="panel">
        <p className="muted">{t.loading}</p>
      </section>
    );
  }

  const snippet = `<script src="${location.origin}/widget.js" data-site-key="${settings.site_key}" defer></script>`;

  async function copySnippet() {
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      onError(e);
    }
  }

  async function saveSettings(e: FormEvent) {
    e.preventDefault();
    try {
      const updated = await api.updateSettings({
        allowed_domains: domains
          .split("\n")
          .map((d) => d.trim())
          .filter(Boolean),
        store_conversations: store,
      });
      setSettings(updated);
      setDomains(updated.allowed_domains.join("\n"));
      setStore(updated.store_conversations);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      onError(err);
    }
  }

  async function rotate() {
    if (!window.confirm(t.confirmRotate)) return;
    try {
      const keys = await api.rotateKeys();
      setRotated(keys);
      load();
    } catch (e) {
      onError(e);
    }
  }

  async function deleteConversations() {
    if (!window.confirm(t.confirmDeleteConversations)) return;
    try {
      const result = await api.deleteConversations();
      setDeletedCount(result.deleted);
    } catch (e) {
      onError(e);
    }
  }

  async function addViewer(e: FormEvent) {
    e.preventDefault();
    try {
      await api.addViewer(viewerEmail, viewerPassword);
      setViewerEmail("");
      setViewerPassword("");
      load();
    } catch (err) {
      onError(err);
    }
  }

  return (
    <>
      <section className="panel">
        <h2>{t.widgetSnippet}</h2>
        <p className="muted">{t.snippetHint}</p>
        <code className="snippet" id="widget-snippet">
          {snippet}
        </code>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="ghost" id="copy-snippet" onClick={copySnippet}>
            {copied ? t.copied : t.copy}
          </button>
        </div>
      </section>

      <section className="panel">
        <h2>{t.settings}</h2>
        <form onSubmit={saveSettings}>
          <label htmlFor="allowed-domains">{t.allowedDomains}</label>
          <textarea
            id="allowed-domains"
            rows={3}
            dir="ltr"
            value={domains}
            disabled={!isOwner}
            onChange={(e) => setDomains(e.target.value)}
          />
          <p className="muted">{t.domainsHint}</p>
          <h3>{t.privacy}</h3>
          <div className="checkbox-row">
            <input
              id="store-conversations"
              type="checkbox"
              checked={store}
              disabled={!isOwner}
              onChange={(e) => setStore(e.target.checked)}
            />
            <label htmlFor="store-conversations">{t.storeConversations}</label>
          </div>
          <p className="muted">{t.storeHint}</p>
          {isOwner && (
            <div className="row">
              <button className="primary" id="save-settings" type="submit">
                {t.save}
              </button>
              {saved && <span className="muted">{t.saved}</span>}
            </div>
          )}
        </form>
      </section>

      {isOwner && (
        <section className="panel keys">
          <h2>{t.apiKeys}</h2>
          <button className="danger" id="rotate-keys" onClick={rotate}>
            {t.rotateKeys}
          </button>
          {rotated && (
            <div className="banner error" role="alert" style={{ marginTop: 12 }}>
              <p>{t.rotatedWarning}</p>
              <p>
                {t.newApiKey}: <code id="new-api-key">{rotated.api_key}</code>
              </p>
              <p>
                {t.newSiteKey}: <code id="new-site-key">{rotated.site_key}</code>
              </p>
            </div>
          )}
        </section>
      )}

      <section className="panel">
        <h2>{t.data}</h2>
        <div className="row">
          {isOwner && (
            <a className="ghost" id="export-data" href="/api/v1/dashboard/export" download>
              {t.exportData}
            </a>
          )}
          {isOwner && (
            <button className="danger" id="delete-conversations" onClick={deleteConversations}>
              {t.deleteConversations}
            </button>
          )}
          {deletedCount !== null && (
            <span className="muted">
              {t.deleted}: {deletedCount}
            </span>
          )}
        </div>
      </section>

      {isOwner && (
        <section className="panel">
          <h2>{t.users}</h2>
          <table>
            <thead>
              <tr>
                <th>{t.email}</th>
                <th>{t.role}</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.email}</td>
                  <td>{u.role === "owner" ? t.owner : t.viewer}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>{t.addViewer}</h3>
          <form onSubmit={addViewer}>
            <label htmlFor="viewer-email">{t.viewerEmail}</label>
            <input
              id="viewer-email"
              type="email"
              required
              value={viewerEmail}
              onChange={(e) => setViewerEmail(e.target.value)}
            />
            <label htmlFor="viewer-password">{t.viewerPassword}</label>
            <input
              id="viewer-password"
              type="password"
              required
              minLength={8}
              value={viewerPassword}
              onChange={(e) => setViewerPassword(e.target.value)}
            />
            <div className="row" style={{ marginTop: 10 }}>
              <button className="primary" id="add-viewer" type="submit">
                {t.add}
              </button>
            </div>
          </form>
        </section>
      )}
    </>
  );
}