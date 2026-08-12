import unittest

from markdown_cleanup import (
    contains_internal_anchor_artifacts,
    remove_internal_anchor_artifacts,
)


class MarkdownCleanupTest(unittest.TestCase):
    def test_removes_anchor_tokens_joined_to_prose(self):
        source = (
            "Understandingidx_608aa348, each type.\n"
            "theidx_c9881525 maintenance transaction\n"
            "idx_bf7c433dframework acts as a mirror\n"
            "idx_0992911callow multiple callbacks\n"
            "idx_53273f9cexecutor starvation"
        )

        cleaned, removed = remove_internal_anchor_artifacts(source)

        self.assertEqual(removed, 5)
        self.assertEqual(
            cleaned,
            "Understanding, each type.\n"
            "the maintenance transaction\n"
            "framework acts as a mirror\n"
            "allow multiple callbacks\n"
            "executor starvation",
        )

    def test_removes_markdown_and_html_anchor_markup(self):
        source = (
            "# Heading {#idx_bf7c433d}\n"
            "[Jump](#idx_608aa348)\n"
            "[Visible text]{#idx_c9881525 .calibre}\n"
            '<a id="idx_53273f9c"></a>Body\n'
            '<a href="#idx_0992911c">Linked text</a>'
        )

        cleaned, removed = remove_internal_anchor_artifacts(source)

        self.assertEqual(removed, 5)
        self.assertEqual(
            cleaned,
            "# Heading\nJump\nVisible text\nBody\nLinked text",
        )

    def test_removes_shortened_and_backticked_translation_tokens(self):
        source = (
            "工程师 idx_6421b6 查询 Loki，然后检查 "
            "`idx_a34fd1c` 标准。C++ idx_b84d3ff6 术语。"
        )

        cleaned, removed = remove_internal_anchor_artifacts(source)

        self.assertEqual(removed, 3)
        self.assertEqual(cleaned, "工程师查询 Loki，然后检查标准。C++ 术语。")

    def test_preserves_chinese_grammar_around_anchor(self):
        source = "这重现了 idx_53273f9c 的执行器饥饿。"

        cleaned, removed = remove_internal_anchor_artifacts(source)

        self.assertEqual(removed, 1)
        self.assertEqual(cleaned, "这重现了的执行器饥饿。")

    def test_preserves_normal_identifiers(self):
        source = "Keep idx_counter, idx_1234, and index_deadbeef."

        cleaned, removed = remove_internal_anchor_artifacts(source)

        self.assertEqual(removed, 0)
        self.assertEqual(cleaned, source)
        self.assertFalse(contains_internal_anchor_artifacts(cleaned))

    def test_eight_digit_anchor_does_not_consume_following_hex_letter(self):
        source = "idx_b84d3ff6a technical term"

        cleaned, removed = remove_internal_anchor_artifacts(source)

        self.assertEqual(removed, 1)
        self.assertEqual(cleaned, "a technical term")


if __name__ == "__main__":
    unittest.main()
