from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import check_repo


def build_valid_repository(root: Path) -> None:
    for value in check_repo.REQUIRED_ROOT_FILES:
        (root / value).write_text("placeholder\n", encoding="utf-8")
    (root / "README.md").write_text(
        "[线性代数](./线性代数/)\n[数据结构](./数据结构/)\n",
        encoding="utf-8",
    )

    linear = root / "线性代数"
    (linear / "攻略").mkdir(parents=True)
    (linear / "考试").mkdir()
    (linear / "README.md").write_text(
        "[指南](./攻略/学习指南.md)\n"
        "[试卷](./考试/模拟卷.md)\n"
        "[解答](./考试/学生解答.md)\n",
        encoding="utf-8",
    )
    (linear / "攻略" / "学习指南.md").write_text("原创指南\n", encoding="utf-8")
    (linear / "考试" / "模拟卷.md").write_text(
        "项目结构演示，不是真实历年试卷。\n", encoding="utf-8"
    )
    (linear / "考试" / "学生解答.md").write_text(
        "非标准答案，仅供复习核对。\n", encoding="utf-8"
    )

    data = root / "数据结构"
    for directory in check_repo.DATA_STRUCTURE_DIRS:
        (data / directory).mkdir(parents=True, exist_ok=True)
    (data / "README.md").write_text(
        "[文件说明](./文件说明.md)\n"
        "[复习资料](./复习资料/)\n"
        "[练习与答案](./练习与答案/)\n"
        "[考试](./考试/)\n"
        "非标准答案，仅供复习核对。\n",
        encoding="utf-8",
    )
    (data / "文件说明.md").write_text("资料来源于网络整理。\n", encoding="utf-8")
    (data / "复习资料" / "复习.pdf").write_bytes(b"review-pdf")
    (data / "练习与答案" / "答案.txt").write_text("answer\n", encoding="utf-8")
    (data / "考试" / "试卷.pdf").write_bytes(b"exam-pdf")


class RepositoryCheckTests(unittest.TestCase):
    def test_valid_two_course_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_valid_repository(root)
            result = check_repo.audit_repository(root)
            self.assertTrue(result.ok, result.issues)

    def test_missing_source_description(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_valid_repository(root)
            (root / "数据结构" / "文件说明.md").write_text("其他文字\n", encoding="utf-8")
            result = check_repo.audit_repository(root)
            self.assertIn("source-description", {issue.code for issue in result.issues})

    def test_rejects_word_file_in_data_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_valid_repository(root)
            (root / "数据结构" / "复习资料" / "讲义.docx").write_bytes(b"word")
            result = check_repo.audit_repository(root)
            self.assertIn("data-structure-word-file", {issue.code for issue in result.issues})

    def test_detects_duplicate_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_valid_repository(root)
            source = root / "数据结构" / "考试" / "试卷.pdf"
            (root / "数据结构" / "考试" / "重复试卷.pdf").write_bytes(source.read_bytes())
            result = check_repo.audit_repository(root)
            self.assertIn("duplicate-resource", {issue.code for issue in result.issues})

    def test_requires_answer_disclaimer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_valid_repository(root)
            readme = root / "数据结构" / "README.md"
            readme.write_text(readme.read_text(encoding="utf-8").replace("非标准答案，仅供复习核对。", ""), encoding="utf-8")
            result = check_repo.audit_repository(root)
            self.assertIn("solution-disclaimer", {issue.code for issue in result.issues})

    def test_detects_size_sensitive_text_and_broken_link(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_valid_repository(root)
            guide = root / "线性代数" / "攻略" / "学习指南.md"
            guide.write_text(
                "[missing](./不存在.md)\nphone 13800138000\napi_key = super-secret-value\n",
                encoding="utf-8",
            )
            result = check_repo.audit_repository(root, max_file_size=10)
            codes = {issue.code for issue in result.issues}
            self.assertIn("file-too-large", codes)
            self.assertIn("possible-pii", codes)
            self.assertIn("possible-secret", codes)
            self.assertIn("broken-link", codes)

    def test_root_readme_must_link_both_courses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_valid_repository(root)
            (root / "README.md").write_text("没有课程入口。\n", encoding="utf-8")
            result = check_repo.audit_repository(root)
            self.assertEqual(
                sum(issue.code == "course-navigation" for issue in result.issues), 2
            )


if __name__ == "__main__":
    unittest.main()
