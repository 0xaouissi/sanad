import { useEffect, useState } from "react";
import { RatingsSummary, api } from "../api";
import { Dict, Lang } from "../i18n";

export function Ratings({
  t,
  lang,
  onError,
}: {
  t: Dict;
  lang: Lang;
  onError: (e: unknown) => void;
}) {
  const [data, setData] = useState<RatingsSummary | null>(null);

  useEffect(() => {
    api
      .ratings()
      .then(setData)
      .catch(onError);
  }, [onError]);

  return (
    <section className="panel">
      <h2>{t.ratings}</h2>
      {data === null ? (
        <p className="muted">{t.loading}</p>
      ) : (
        <>
          <div className="row" style={{ marginBottom: 12 }}>
            <span className="badge ready">
              👍 {t.thumbsUp}: {data.up}
            </span>
            <span className="badge failed">
              👎 {t.thumbsDown}: {data.down}
            </span>
          </div>
          {data.items.length === 0 ? (
            <p className="muted">{t.noRatings}</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>{t.question}</th>
                  <th>{t.answer}</th>
                  <th>{t.date}</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.message_id}>
                    <td>
                      {item.rating === "up" ? "👍" : "👎"} {item.question ?? "—"}
                    </td>
                    <td>{item.answer}</td>
                    <td>{new Date(item.created_at).toLocaleString(lang)}</td>
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