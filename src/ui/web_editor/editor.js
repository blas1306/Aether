import {EditorView, minimalSetup} from "./vendor/codemirror.bundle.js";

function reportError(message) {
  const status = document.getElementById("status");
  document.getElementById("editor").style.display = "none";
  status.style.display = "block";
  status.textContent = "CodeMirror failed to load.\n" + String(message);
  window.notifyPythonError(status.textContent);
}

function boot() {
  try {
    let suppressChange = false;
    const theme = EditorView.theme({
      "&": {backgroundColor: "#1e1e1e", color: "#e3e6ea"},
      ".cm-content": {caretColor: "#ffffff"},
      ".cm-cursor": {borderLeftColor: "#ffffff"},
      ".cm-gutters": {
        backgroundColor: "#1e1e1e",
        color: "#858585",
        borderRightColor: "#343a40"
      },
      ".cm-activeLine": {backgroundColor: "#2b3036"},
      ".cm-activeLineGutter": {backgroundColor: "#2b3036"},
      ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
        backgroundColor: "#315f8f"
      }
    }, {dark: true});

    const notifyTextChanged = EditorView.updateListener.of((update) => {
      if (update.docChanged && !suppressChange && window.__pythonBridge) {
        window.__pythonBridge.editorTextChanged(
          update.state.doc.toString(),
          update.state.selection.main.head
        );
      }
      if (update.selectionSet && window.__pythonBridge) {
        window.__pythonBridge.editorCursorChanged(update.state.selection.main.head);
      }
    });

    const view = new EditorView({
      doc: "",
      extensions: [
        minimalSetup,
        notifyTextChanged,
        theme
      ],
      parent: document.getElementById("editor")
    });

    function clampPosition(pos) {
      const length = view.state.doc.length;
      return Math.max(0, Math.min(Number(pos) || 0, length));
    }

    window.codeMirrorAdapter = {
      setText(text) {
        suppressChange = true;
        try {
          view.dispatch({
            changes: {from: 0, to: view.state.doc.length, insert: String(text)}
          });
        } finally {
          suppressChange = false;
        }
      },
      setCursorPosition(pos) {
        const position = clampPosition(pos);
        view.dispatch({selection: {anchor: position}, scrollIntoView: true});
      },
      goToLine(line, column) {
        const lineNumber = Number(line) || 1;
        const col = Math.max(0, Number(column) || 0);
        if (lineNumber < 1 || lineNumber > view.state.doc.lines) {
          return false;
        }
        const targetLine = view.state.doc.line(lineNumber);
        const position = targetLine.from + Math.min(col, targetLine.length);
        view.dispatch({selection: {anchor: position}, scrollIntoView: true});
        view.focus();
        return true;
      },
      focusEditor() {
        view.focus();
      }
    };

    window.notifyPythonReady();
  } catch (error) {
    reportError(error);
  }
}

boot();
