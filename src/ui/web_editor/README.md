# Web Editor Assets

This directory contains the local web assets used by the experimental
`CodeMirrorEditor` adapter.

Runtime loading is offline: `codemirror_editor.py` opens `index.html` with
`QWebEngineView.load(QUrl.fromLocalFile(...))`, and `editor.js` imports
`./vendor/codemirror.bundle.js`. No CDN or internet access is required when the
application runs.

`vendor/codemirror.bundle.js` is a generated asset. It currently contains the
minimal CodeMirror 6 exports used by the prototype:

- `EditorView`
- `minimalSetup`

To regenerate the bundle once Node/npm are available:

```bash
cd tools/web_editor
npm install
npm run build
```

Do not edit files in `vendor/` by hand. Update `tools/web_editor/src/codemirror-entry.js`
and rebuild instead.

This adapter is still experimental. It intentionally does not implement
autocomplete, diagnostics, full selection support, or feature parity with
`CodeEditor`.
