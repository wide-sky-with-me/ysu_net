"""The accuracy scorer stays offline: it only reads a labelled TSV."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "ysu_captcha_accuracy", ROOT / "packaging/captcha_accuracy.py"
)
accuracy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(accuracy)


class ScorerTests(unittest.TestCase):
    def run_score(self, rows: str) -> str:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "labels.tsv").write_text(rows, encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(accuracy.score(type("Args", (), {"out": directory})()), 0)
            return output.getvalue()

    def test_counts_exact_and_case_insensitive_separately(self):
        text = self.run_score(
            "# 注释行\n"
            "01.jpg\tnb4f\tddddocr\t11\tnB4f\n"
            "02.jpg\tth3c\tddddocr\t10\ttH3C\n"
            "03.jpg\tabcd\tddddocr\t12\twmxy\n"
        )
        self.assertIn("样本 3", text)
        self.assertIn("完全一致 0/3", text)
        self.assertIn("忽略大小写一致 2/3", text)
        self.assertIn("03.jpg", text)
        self.assertIn("门户若区分大小写", text)

    def test_skips_rows_without_a_label_and_refuses_an_empty_file(self):
        text = self.run_score("01.jpg\tnb4f\tddddocr\t11\tnb4f\n02.jpg\tth3c\tddddocr\t10\t\n")
        self.assertIn("样本 1", text)
        self.assertIn("完全一致 1/1", text)
        with self.assertRaises(SystemExit):
            self.run_score("# 只有注释\n")


if __name__ == "__main__":
    unittest.main()
