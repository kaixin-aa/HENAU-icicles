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
    for course in check_repo.COURSES:
        course_root = root / course
        (course_root / "攻略").mkdir(parents=True)
        (course_root / "考试").mkdir(parents=True)
        (course_root / "README.md").write_text(
            "[指南](./攻略/学习指南.md)\n"
            "[卷](./考试/模拟卷.md)\n"
            "[解答](./考试/学生解答.md)\n",
            encoding="utf-8",
        )
        (course_root / "攻略" / "学习指南.md").write_text("原创指南\n", encoding="utf-8")
        (course_root / "考试" / "模拟卷.md").write_text(
            "项目结构演示，不是真实历年试卷。\n", encoding="utf-8"
        )
        (course_root / "考试" / "学生解答.md").write_text(
            "非标准答案，仅供复习核对。\n", encoding="utf-8"
        )


class RepositoryCheckTests(unittest.TestCase):
    def test_valid_two_course_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_valid_repository(root)
            result = check_repo.audit_repository(root)
            self.assertTrue(result.ok, result.issues)

    def test_missing_course_file_and_disclaimer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_valid_repository(root)
            (root / "线性代数" / "攻略" / "学习指南.md").unlink()
            (root / "数据结构" / "考试" / "模拟卷.md").write_text("普通练习\n", encoding="utf-8")
            result = check_repo.audit_repository(root)
            codes = {issue.code for issue in result.issues}
            self.assertIn("required-course-file", codes)
            self.assertIn("exam-disclaimer", codes)

    def test_rejects_banned_extension_and_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_valid_repository(root)
            (root / "线性代数" / "setup.exe").write_bytes(b"not executable")
            dependency = root / "数据结构" / "node_modules"
            dependency.mkdir()
            (dependency / "package.js").write_text("x", encoding="utf-8")
            result = check_repo.audit_repository(root)
            codes = {issue.code for issue in result.issues}
            self.assertIn("banned-extension", codes)
            self.assertIn("banned-directory", codes)

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
            (root / "README.md").write_text("只有文字，没有课程入口。\n", encoding="utf-8")
            result = check_repo.audit_repository(root)
            self.assertEqual(
                sum(issue.code == "course-navigation" for issue in result.issues), 2
            )


if __name__ == "__main__":
    unittest.main()
