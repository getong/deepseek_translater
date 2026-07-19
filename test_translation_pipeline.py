import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parent


def load_script(module_name, filename):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


converter = load_script("convert_to_htmlz", "01_convert_to_htmlz.py")
translator = load_script("translate_md", "03_translate_md.py")


class HtmlToMarkdownTest(unittest.TestCase):
    def test_calibre_code_spans_become_plain_fenced_code(self):
        html = """<html><body>
<p>Declarations:</p>
<p class="calibre33"><span class="calibre15">UFUNCTION</span><span class="calibre15">(BlueprintCallable, BlueprintNativeEvent, Category=</span><span class="calibre15">&quot;PawsInTheShell|</span></p>
<p class="calibre33"><span class="calibre15">Defence&quot;</span><span class="calibre15">)</span></p>
<p class="calibre33"><span class="calibre15">void</span> <span class="calibre15">SetIsInSafeZone</span><span class="calibre15">(</span><span class="calibre15">const bool</span><span class="calibre15"> bNewInSafeZone);</span></p>
</body></html>"""

        with tempfile.TemporaryDirectory() as temp_dir:
            html_file = Path(temp_dir) / "input.html"
            markdown_file = Path(temp_dir) / "input.md"
            html_file.write_text(html, encoding="utf-8")

            self.assertTrue(
                converter.convert_html_to_markdown(str(html_file), str(markdown_file))
            )
            markdown = markdown_file.read_text(encoding="utf-8")

        self.assertIn("``` text", markdown)
        self.assertIn("UFUNCTION(BlueprintCallable", markdown)
        self.assertIn("void SetIsInSafeZone(const bool bNewInSafeZone);", markdown)
        self.assertNotIn("[UFUNCTION]", markdown)
        self.assertNotIn("[void]", markdown)

    def test_markdown_split_does_not_cut_a_fenced_code_block(self):
        markdown = """Intro text.

``` cpp
UFUNCTION(BlueprintCallable)
void SetIsInSafeZone(const bool bNewInSafeZone);
bool IsInSafeZone() const;
```

Following text.
"""

        with tempfile.TemporaryDirectory() as temp_dir:
            markdown_file = Path(temp_dir) / "input.md"
            markdown_file.write_text(markdown, encoding="utf-8")
            chunk_count = converter.split_markdown_by_size(
                str(markdown_file), temp_dir, target_size=40
            )
            chunks = [
                (Path(temp_dir) / f"page{index:04d}.md").read_text(encoding="utf-8")
                for index in range(1, chunk_count + 1)
            ]

        code_chunks = [chunk for chunk in chunks if "UFUNCTION" in chunk]
        self.assertEqual(len(code_chunks), 1)
        self.assertEqual(len(translator.extract_fenced_code_blocks(code_chunks[0])), 1)


class CodeProtectionTest(unittest.TestCase):
    SOURCE = """Before.

``` cpp
UFUNCTION(BlueprintCallable)
void SetIsInSafeZone(const bool bNewInSafeZone); // Set safe-zone state
bool IsInSafeZone() const;
```

After.
"""

    def test_only_comment_text_may_change(self):
        translated = self.SOURCE.replace("Before.", "之前。").replace(
            "Set safe-zone state", "设置安全区域状态"
        ).replace("After.", "之后。")

        self.assertEqual(translator.validate_code_blocks(self.SOURCE, translated), (True, None))

    def test_added_brackets_are_rejected(self):
        translated = self.SOURCE.replace(
            "UFUNCTION(BlueprintCallable)", "[UFUNCTION][(BlueprintCallable)]"
        )

        is_valid, error = translator.validate_code_blocks(self.SOURCE, translated)

        self.assertFalse(is_valid)
        self.assertIn("non-comment code changed", error)

    def test_translation_retries_after_code_is_modified(self):
        invalid = self.SOURCE.replace(
            "UFUNCTION(BlueprintCallable)", "[UFUNCTION][(BlueprintCallable)]"
        )
        valid = self.SOURCE.replace("Before.", "之前。").replace(
            "Set safe-zone state", "设置安全区域状态"
        ).replace("After.", "之后。")
        responses = [
            f"<!-- START -->\n{invalid}\n<!-- END -->",
            f"<!-- START -->\n{valid}\n<!-- END -->",
        ]

        with patch.object(translator, "ds_translate", side_effect=responses):
            with patch.object(translator.time, "sleep"):
                result = translator.translate_with_deepseek(self.SOURCE, "zh")

        self.assertEqual(result, valid.strip())


if __name__ == "__main__":
    unittest.main()
