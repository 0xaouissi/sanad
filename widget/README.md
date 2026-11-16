# Sanad widget

Plain-JavaScript embeddable chat widget: one script tag, Shadow DOM style
isolation, RTL, streaming answers. No framework, tiny bundle.

```html
<script src="http://localhost:8000/widget.js" data-site-key="pk-…" defer></script>
```

The `pk-…` site key is public by design and only works on the company's
allowed domains; the secret `sk-…` key never belongs in a page.

Configuration attributes (`data-api-url`, `data-color`, `data-logo`,
`data-welcome`, `data-lang`, `data-theme`), the site-key threat model, the
`textContent`-only rendering guarantee, the handoff form and the real-browser
tests are documented in the main README:
[The embeddable widget](../README.md#the-embeddable-widget-step-4).
A runnable demo page and recorded GIFs: [../docs/demo.md](../docs/demo.md).