import unittest
from pathlib import Path

from execution_results import StructuredLogCollector, variable_summaries_from_snapshot


class StructuredLogCollectorTests(unittest.TestCase):
    def test_build_result_splits_warnings_and_errors(self) -> None:
        collector = StructuredLogCollector()
        collector.add_entry("Compile started", source="app")
        collector.add_text("Warning: rerun may be needed.\n", source="stdout")
        collector.add_text("error: missing package\n", source="stderr")

        result = collector.build_result(
            success=False,
            source_path=Path("main.mtex"),
            pdf_path=None,
            build_dir=Path("build"),
            output_files=[],
            variables=[],
        )

        self.assertEqual(len(result.logs), 3)
        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.warnings[0].level, "warning")
        self.assertEqual(result.errors[0].level, "error")

    def test_variable_summaries_from_snapshot_normalizes_entries(self) -> None:
        summaries = variable_summaries_from_snapshot(
            [{"name": "A", "class": "Matrix", "size": "2x2", "summary": "[1 2; 3 4]"}]
        )

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].name, "A")
        self.assertEqual(summaries[0].value_type, "Matrix")
        self.assertEqual(summaries[0].size, "2x2")


if __name__ == "__main__":
    unittest.main()
