from __future__ import annotations

from pathlib import Path

import pytest

from editor_pdf_sync import (
    EditorPdfSyncMap,
    MtexTraceArtifact,
    TRACE_ARTIFACT_VERSION,
    TraceMappingSpan,
    extract_source_landmarks,
    parse_synctex_view_output,
    parse_aux_landmarks,
    parse_toc_landmarks,
    write_trace_artifact,
)


def test_extract_source_landmarks_tracks_heading_hierarchy() -> None:
    text = (
        "\\section{Intro}\n"
        "Body.\n"
        "\\subsection{Details}\n"
        "More.\n"
        "\\subsubsection{Deep Dive}\n"
    )

    landmarks = extract_source_landmarks(text)

    assert [(landmark.command, landmark.title, landmark.line_number) for landmark in landmarks] == [
        ("section", "Intro", 1),
        ("subsection", "Details", 3),
        ("subsubsection", "Deep Dive", 5),
    ]
    assert landmarks[0].parent_index is None
    assert landmarks[1].parent_index == 0
    assert landmarks[2].parent_index == 1


def test_parse_toc_and_aux_landmarks_read_compiled_heading_pages() -> None:
    toc_text = (
        r"\contentsline {section}{\numberline {1}Experiment Description}{3}{section.1}%" "\n"
        r"\contentsline {subsection}{\numberline {1.1}Setup}{4}{subsection.1.1}%" "\n"
    )
    aux_text = (
        r"\@writefile{toc}{\contentsline {section}{\numberline {1}Experiment Description}{3}{section.1}\protected@file@percent }" "\n"
        r"\@writefile{toc}{\contentsline {subsection}{\numberline {1.1}Setup}{4}{subsection.1.1}\protected@file@percent }" "\n"
    )

    toc_landmarks = parse_toc_landmarks(toc_text)
    aux_landmarks = parse_aux_landmarks(aux_text)

    assert [(landmark.command, landmark.normalized_title, landmark.page_index) for landmark in toc_landmarks] == [
        ("section", "experiment description", 2),
        ("subsection", "setup", 3),
    ]
    assert [(landmark.command, landmark.normalized_title, landmark.page_index) for landmark in aux_landmarks] == [
        ("section", "experiment description", 2),
        ("subsection", "setup", 3),
    ]


def test_sync_map_resolves_current_heading_page_and_falls_back_to_parent(tmp_path) -> None:
    source_text = (
        "\\section{Intro}\n"
        "Intro body.\n"
        "\\subsection{Details}\n"
        "Detail body.\n"
        "\\section{Conclusion}\n"
        "Wrap up.\n"
    )
    toc_path = tmp_path / "demo.toc"
    toc_path.write_text(
        r"\contentsline {section}{\numberline {1}Intro}{2}{section.1}%" "\n"
        r"\contentsline {section}{\numberline {2}Conclusion}{5}{section.2}%" "\n",
        encoding="utf-8",
    )

    sync_map = EditorPdfSyncMap()
    sync_map.update_source(source_text)
    sync_map.update_compiled_landmarks(toc_path=toc_path, aux_path=None)

    intro_target = sync_map.resolve_target_for_line(2)
    detail_target = sync_map.resolve_target_for_line(4)
    conclusion_target = sync_map.resolve_target_for_line(6)

    assert intro_target is not None
    assert intro_target.landmark.title == "Intro"
    assert intro_target.page_index == 1

    assert detail_target is not None
    assert detail_target.landmark.title == "Intro"
    assert detail_target.page_index == 1

    assert conclusion_target is not None
    assert conclusion_target.landmark.title == "Conclusion"
    assert conclusion_target.page_index == 4


def test_sync_map_resolves_pdf_page_back_to_nearest_mapped_heading(tmp_path) -> None:
    source_text = (
        "\\section{Intro}\n"
        "Intro body.\n"
        "\\subsection{Details}\n"
        "Detail body.\n"
        "\\section{Conclusion}\n"
        "Wrap up.\n"
    )
    toc_path = tmp_path / "demo.toc"
    toc_path.write_text(
        r"\contentsline {section}{\numberline {1}Intro}{2}{section.1}%" "\n"
        r"\contentsline {subsection}{\numberline {1.1}Details}{3}{subsection.1.1}%" "\n"
        r"\contentsline {section}{\numberline {2}Conclusion}{5}{section.2}%" "\n",
        encoding="utf-8",
    )

    sync_map = EditorPdfSyncMap()
    sync_map.update_source(source_text)
    sync_map.update_compiled_landmarks(toc_path=toc_path, aux_path=None)

    intro_target = sync_map.resolve_source_target_for_page(1)
    detail_target = sync_map.resolve_source_target_for_page(3)
    conclusion_target = sync_map.resolve_source_target_for_page(4)
    unmapped_target = sync_map.resolve_source_target_for_page(0)

    assert intro_target is not None
    assert intro_target.landmark.title == "Intro"
    assert intro_target.line_number == 1

    assert detail_target is not None
    assert detail_target.landmark.title == "Details"
    assert detail_target.line_number == 3

    assert conclusion_target is not None
    assert conclusion_target.landmark.title == "Conclusion"
    assert conclusion_target.line_number == 5

    assert unmapped_target is None


def test_parse_synctex_view_output_extracts_forward_records() -> None:
    output = (
        "This is SyncTeX command line utility, version 1.5\n"
        "SyncTeX result begin\n"
        "Output:C:\\\\tmp\\\\demo.pdf\n"
        "Page:2\n"
        "x:100.5\n"
        "y:200.5\n"
        "h:101.0\n"
        "v:201.0\n"
        "W:300.0\n"
        "H:10.0\n"
        "SyncTeX result end\n"
    )

    records = parse_synctex_view_output(output)

    assert len(records) == 1
    assert records[0].page_index == 1
    assert records[0].x == pytest.approx(100.5)
    assert records[0].height == pytest.approx(10.0)


def test_sync_map_prefers_trace_and_synctex_before_landmark_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_text = (
        "\\section{Intro}\n"
        "Body line.\n"
        "\\section{Conclusion}\n"
        "Done.\n"
    )
    pdf_path = tmp_path / "demo.pdf"
    tex_path = tmp_path / "demo.tex"
    synctex_path = tmp_path / "demo.synctex.gz"
    trace_path = tmp_path / "demo.mtextrace.json"
    toc_path = tmp_path / "demo.toc"

    pdf_path.write_bytes(b"%PDF-1.4\n%trace\n")
    tex_path.write_text("% generated tex\n", encoding="utf-8")
    synctex_path.write_bytes(b"mock")
    toc_path.write_text(
        r"\contentsline {section}{\numberline {1}Intro}{2}{section.1}%" "\n"
        r"\contentsline {section}{\numberline {2}Conclusion}{5}{section.2}%" "\n",
        encoding="utf-8",
    )
    write_trace_artifact(
        trace_path,
        MtexTraceArtifact(
            version=TRACE_ARTIFACT_VERSION,
            source_path=tmp_path / "demo.mtex",
            tex_path=tex_path,
            pdf_path=pdf_path,
            synctex_path=synctex_path,
            synctex_enabled=True,
            spans=[
                TraceMappingSpan(source_start_line=2, source_end_line=2, tex_start_line=14, tex_end_line=14, kind="source_line"),
            ],
        ),
    )

    sync_map = EditorPdfSyncMap()
    sync_map.update_source(source_text)
    sync_map.update_compiled_landmarks(toc_path=toc_path, aux_path=None)
    sync_map.update_trace_artifact(trace_path)

    monkeypatch.setattr(
        "editor_pdf_sync.query_synctex_forward",
        lambda **kwargs: [
            type("Record", (), {"page_index": 6, "x": 0.0, "y": 0.0, "h": 0.0, "v": 0.0, "width": 0.0, "height": 0.0, "output_path": None})()
        ],
    )

    trace_target = sync_map.resolve_target_for_line(2)
    landmark_target = sync_map.resolve_target_for_line(4)

    assert trace_target is not None
    assert trace_target.strategy == "synctex"
    assert trace_target.page_index == 6
    assert trace_target.tex_line == 14

    assert landmark_target is not None
    assert landmark_target.strategy == "landmark"
    assert landmark_target.page_index == 4
