import importlib.util
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import fitz
from PIL import Image


ROOT = Path(__file__).parent


def load_script(module_name, filename):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


converter = load_script("convert_to_htmlz", "01_convert_to_htmlz.py")
translator = load_script("translate_md", "03_translate_md.py")
merger = load_script("merge_md", "04_merge_md.py")
pdf_converter = load_script("pdf_to_md", "pdf2md.py")
html_converter = load_script("md_to_html", "05_md_to_html.py")
publisher = load_script("calibre_publisher", "calibre_html_publish.py")
format_generator = load_script("format_generator", "07_generate_formats.py")


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


class ImagePipelineTest(unittest.TestCase):
    def test_pdf_images_are_extracted_and_referenced(self):
        image_buffer = BytesIO()
        Image.new("RGB", (24, 16), "red").save(image_buffer, format="PNG")

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_file = Path(temp_dir) / "input.pdf"
            markdown_file = Path(temp_dir) / "input.md"
            document = fitz.open()
            page = document.new_page()
            page.insert_text((72, 72), "Before image")
            page.insert_image(
                fitz.Rect(72, 100, 192, 180), stream=image_buffer.getvalue()
            )
            document.save(pdf_file)
            document.close()

            pdf_converter.pdf_to_markdown(str(pdf_file), str(markdown_file))

            markdown = markdown_file.read_text(encoding="utf-8")
            image_paths = translator.extract_markdown_image_paths(markdown)
            self.assertEqual(image_paths, ["images/image_p0000_0.png"])
            self.assertTrue((Path(temp_dir) / image_paths[0]).is_file())
            self.assertTrue(
                (Path(temp_dir) / pdf_converter.PDF_IMAGE_CACHE_MARKER).is_file()
            )

    def test_pdf_blocks_follow_visual_page_order(self):
        image_buffer = BytesIO()
        Image.new("RGB", (24, 16), "red").save(image_buffer, format="PNG")

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_file = Path(temp_dir) / "input.pdf"
            markdown_file = Path(temp_dir) / "input.md"
            document = fitz.open()
            page = document.new_page()
            # Insert text first in the content stream, but place the image
            # above it visually.
            page.insert_text((72, 220), "Figure caption")
            page.insert_image(
                fitz.Rect(72, 100, 192, 180), stream=image_buffer.getvalue()
            )
            document.save(pdf_file)
            document.close()

            pdf_converter.pdf_to_markdown(str(pdf_file), str(markdown_file))

            markdown = markdown_file.read_text(encoding="utf-8")
            self.assertLess(markdown.index("![]("), markdown.index("Figure caption"))

    def test_existing_markdown_image_cache_is_verified(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            images = base / "images"
            images.mkdir()
            markdown_file = base / "input.md"
            markdown_file.write_text(
                "![Figure](images/figure.png)", encoding="utf-8"
            )

            self.assertFalse(
                converter.markdown_image_cache_is_complete(markdown_file)
            )
            (images / "figure.png").write_bytes(b"image")
            self.assertTrue(
                converter.markdown_image_cache_is_complete(markdown_file)
            )

    def test_translation_must_preserve_image_paths(self):
        source = "Before\n\n![Figure](images/figure-01.png)\n\nAfter"
        valid = "之前\n\n![图](images/figure-01.png)\n\n之后"
        changed = valid.replace("figure-01.png", "figure-02.png")

        self.assertEqual(
            translator.validate_image_references(source, valid),
            (True, None),
        )
        is_valid, error = translator.validate_image_references(source, changed)
        self.assertFalse(is_valid)
        self.assertIn("image path 1 changed", error)

    def test_model_added_image_is_restored_to_caption_text(self):
        source = "Figure 5.1 - Binding an event"
        translated = "![图 5.1 - 绑定事件](media/image-001.png)"

        corrected, removed = translator.remove_added_image_references(
            source, translated
        )

        self.assertEqual(removed, 1)
        self.assertEqual(corrected, "图 5.1 - 绑定事件")
        self.assertEqual(
            translator.validate_image_references(source, corrected),
            (True, None),
        )

    def test_added_image_is_corrected_without_retrying_translation(self):
        source = "Figure 5.1 - Binding an event"
        translated = "![图 5.1 - 绑定事件](media/image-001.png)"
        response = f"<!-- START -->\n{translated}\n<!-- END -->"

        with patch.object(translator, "ds_translate", return_value=response) as request:
            result = translator.translate_with_deepseek(source, "zh")

        self.assertEqual(result, "图 5.1 - 绑定事件")
        request.assert_called_once()

    def test_prompt_does_not_suggest_a_fake_image_path(self):
        prompt = translator.create_translation_prompt("zh")

        self.assertNotIn("media/image-001.png", prompt)
        self.assertIn("绝对不要根据 Figure", prompt)

    def test_translation_retries_after_image_path_is_modified(self):
        source = "![Figure](images/figure-01.png)"
        invalid = "![图](images/figure-02.png)"
        valid = "![图](images/figure-01.png)"
        responses = [
            f"<!-- START -->\n{invalid}\n<!-- END -->",
            f"<!-- START -->\n{valid}\n<!-- END -->",
        ]

        with patch.object(translator, "ds_translate", side_effect=responses):
            with patch.object(translator.time, "sleep"):
                result = translator.translate_with_deepseek(source, "zh")

        self.assertEqual(result, valid)

    def test_html_publisher_copies_nested_referenced_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            image_file = base / "assets" / "figures" / "one.png"
            image_file.parent.mkdir(parents=True)
            image_file.write_bytes(b"image-data")
            html_file = base / "book.html"
            html_file.write_text(
                '<html><body><img src="assets/figures/one.png"></body></html>',
                encoding="utf-8",
            )
            work_dir = base / "work"
            work_dir.mkdir()

            count = publisher.copy_images_if_needed(html_file, work_dir)

            self.assertEqual(count, 1)
            self.assertEqual(
                (work_dir / "assets" / "figures" / "one.png").read_bytes(),
                b"image-data",
            )

    def test_missing_html_image_is_reported_before_conversion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            html_file = Path(temp_dir) / "book.html"
            html_file.write_text(
                '<html><body><img src="images/missing.png"></body></html>',
                encoding="utf-8",
            )

            self.assertEqual(
                html_converter.find_missing_html_images(html_file),
                ["images/missing.png"],
            )
            with self.assertRaises(FileNotFoundError):
                publisher.copy_images_if_needed(html_file, Path(temp_dir) / "work")

    def test_format_is_regenerated_when_an_image_is_newer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            image_file = base / "images" / "figure.png"
            image_file.parent.mkdir()
            image_file.write_bytes(b"image")
            html_file = base / "book.html"
            html_file.write_text(
                '<html><body><img src="images/figure.png"></body></html>',
                encoding="utf-8",
            )
            output_file = base / "book.pdf"
            output_file.write_bytes(b"pdf")

            os.utime(html_file, (10, 10))
            os.utime(image_file, (10, 10))
            os.utime(output_file, (20, 20))
            self.assertTrue(
                format_generator.output_is_current(output_file, html_file)
            )

            os.utime(image_file, (30, 30))
            self.assertFalse(
                format_generator.output_is_current(output_file, html_file)
            )

    def test_merged_markdown_is_regenerated_for_a_new_translation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            source = base / "page0001.md"
            translated = base / "output_page0001.md"
            merged = base / "output.md"
            source.write_text("source", encoding="utf-8")
            translated.write_text("translated", encoding="utf-8")
            merged.write_text("translated", encoding="utf-8")

            os.utime(source, (10, 10))
            os.utime(translated, (10, 10))
            os.utime(merged, (20, 20))
            self.assertTrue(merger.merged_output_is_current(base, merged))

            os.utime(translated, (30, 30))
            self.assertFalse(merger.merged_output_is_current(base, merged))


if __name__ == "__main__":
    unittest.main()
