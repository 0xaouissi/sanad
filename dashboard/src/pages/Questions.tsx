import { useEffect, useState } from "react";
import { FailedQuestion, api } from "../api";
import { Dict, Lang } from "../i18n";

export function Questions({
  t,
  lang,
  onError,
}: {
  t: Dict;
  lang: Lang;
  onError: (e: unknown) => void;
}) {
  const [items, setItems] = useState<FailedQuestion[] | null>(null);

  useEffect(() => {
    api
      .failedQuestions()
      .then(setItems)
      .catch(onError);
  }, [onError]);

  return (
    <section className="panel">
      <h2>{t.questions}</h2>
      {items === null ? (
        <p className="muted">{t.loading}</p>
      ) : items.length === 0 ? (
        <p className="muted">{t.noFailedQuestions}</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>{t.question}</th>
              <th>{t.language}</th>
              <th>{t.date}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.message_id}>
                <td>{item.question}</td>
                <td>{item.language ?? "—"}</td>
                <td>{new Date(item.created_at).toLocaleString(lang)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}