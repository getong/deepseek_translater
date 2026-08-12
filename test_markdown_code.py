import unittest
from unittest.mock import patch

import importlib

from markdown_code import (
    fence_unmarked_code_blocks,
    mask_fenced_code_blocks,
    partition_fenced_code_blocks,
    remove_model_added_code_fences,
    restore_fenced_code_blocks,
    restore_source_code_in_translation,
)


class MarkdownCodeTest(unittest.TestCase):
    def test_fences_unreal_cpp_and_build_cs_samples(self):
        source = """Intro text.
UCLASS()
class RPG_API ARPGCharacter : public ACharacter
{
GENERATED_BODY()
public:
// Sets default values for this character's properties
ARPGCharacter();
}
Adding the module
public class RPG : ModuleRules
{
public RPG(ReadOnlyTargetRules Target) : base(Target)
{
/// Import the module
PublicDependencyModuleNames.AddRange(new string[] { "Core" });
}
}
After text."""

        fenced, count = fence_unmarked_code_blocks(source)

        self.assertEqual(count, 2)
        self.assertIn(
            "```cpp\nUCLASS()\nclass RPG_API ARPGCharacter : public ACharacter",
            fenced,
        )
        self.assertIn("```csharp\npublic class RPG : ModuleRules", fenced)
        self.assertIn("\n```\n\nAdding the module", fenced)

    def test_fences_qualified_cpp_constructor(self):
        source = """Before.
ARPGCharacter::ARPGCharacter()
{
 // Attach the head to the body
 HeadMesh->SetupAttachment(GetMesh(), "Head");
}
After."""

        fenced, count = fence_unmarked_code_blocks(source)

        self.assertEqual(count, 1)
        self.assertIn("```cpp\nARPGCharacter::ARPGCharacter()", fenced)
        self.assertIn("// Attach the head to the body", fenced)

    def test_fences_cpp_method_with_return_type(self):
        source = """Before.
void UHairSelectorWidget::NativeConstruct()
{
    Super::NativeConstruct();
}
After."""

        fenced, count = fence_unmarked_code_blocks(source)

        self.assertEqual(count, 1)
        self.assertIn("```cpp\nvoid UHairSelectorWidget::NativeConstruct()", fenced)

    def test_fences_multiline_cpp_method_signature(self):
        source = """Before.
FReply UDialogueWidget::NativeOnKeyDown(const FGeometry&
InGeometry, const FKeyEvent& InKeyEvent)
{
    return reply.Handled();
}
After."""

        fenced, count = fence_unmarked_code_blocks(source)

        self.assertEqual(count, 1)
        self.assertIn(
            "```cpp\nFReply UDialogueWidget::NativeOnKeyDown(const FGeometry&",
            fenced,
        )
        self.assertIn("return reply.Handled();\n}\n```", fenced)

    def test_mask_and_restore_preserve_entire_block_exactly(self):
        source = """Translated prose.

```cpp
UCLASS()
// Do not translate this comment
class RPG_API ARPGCharacter : public ACharacter
```

More prose."""

        masked, blocks = mask_fenced_code_blocks(source)

        self.assertNotIn("UCLASS", masked)
        self.assertNotIn("Do not translate", masked)
        self.assertIn("<!-- DTS_CODE_BLOCK_0001 -->", masked)
        restored, removed = restore_fenced_code_blocks(masked, blocks)
        self.assertEqual(removed, 0)
        self.assertEqual(restored, source)

    def test_partitions_prose_and_code_without_changing_content(self):
        source = "Before.\n```cpp\nint value = 1;\n```\nAfter."

        segments = partition_fenced_code_blocks(source)

        self.assertEqual([is_code for is_code, _ in segments], [False, True, False])
        self.assertEqual("".join(segment for _, segment in segments), source)

    def test_restore_rejects_changed_placeholder(self):
        source = "```cpp\nint value = 1;\n```"
        masked, blocks = mask_fenced_code_blocks(source)

        with self.assertRaisesRegex(ValueError, "code placeholders changed"):
            restore_fenced_code_blocks(masked.replace("0001", "0002"), blocks)

    def test_unwraps_model_added_fences_before_restoring_source_code(self):
        source = "```cpp\nint value = 1;\n```"
        masked, blocks = mask_fenced_code_blocks(source)
        translated = (
            "译文。\n\n```markdown\n额外说明\n```\n\n"
            f"{masked}\n"
        )

        restored, removed = restore_fenced_code_blocks(translated, blocks)

        self.assertEqual(removed, 1)
        self.assertIn("译文。\n\n额外说明", restored)
        self.assertIn(source, restored)
        self.assertEqual(restored.count("```cpp"), 1)

    def test_unwrap_preserves_unclosed_fence_as_prose(self):
        source = "Before\n```markdown\nunclosed"

        cleaned, removed = remove_model_added_code_fences(source)

        self.assertEqual(removed, 0)
        self.assertEqual(cleaned, source)

    def test_repairs_translated_code_in_existing_cache(self):
        source = """Before.
UCLASS()
class RPG_API ATest : public AActor
{
// Original English comment
}
After."""
        translated = """译文前。
UCLASS()
class RPG_API ATest : public AActor
{
// 被翻译的注释
}
译文后。"""

        repaired, changed, error = restore_source_code_in_translation(
            source, translated
        )

        self.assertTrue(changed)
        self.assertIsNone(error)
        self.assertIn("译文前。", repaired)
        self.assertIn("译文后。", repaired)
        self.assertIn("// Original English comment", repaired)
        self.assertNotIn("// 被翻译的注释", repaired)
        self.assertIn("```cpp\nUCLASS()", repaired)

    def test_cache_repair_rejects_unmatched_code_blocks(self):
        source = "```cpp\nint first;\n```\n```cpp\nint second;\n```"
        translated = "```cpp\nint first;\n```"

        _, changed, error = restore_source_code_in_translation(source, translated)

        self.assertFalse(changed)
        self.assertEqual(error, "code block count changed (2 -> 1)")

    def test_cache_repair_rejects_different_code_with_same_block_count(self):
        source = "```cpp\nvoid First()\n{\n}\n```"
        translated = "```cpp\nvoid Different()\n{\n}\n```"

        _, changed, error = restore_source_code_in_translation(source, translated)

        self.assertFalse(changed)
        self.assertEqual(error, "code block 1 does not match the source sample")

    def test_existing_fences_are_idempotent(self):
        source = "```cpp\nUCLASS()\nclass RPG_API ATest : public AActor\n{\n}\n```"

        fenced, count = fence_unmarked_code_blocks(source)

        self.assertEqual(count, 0)
        self.assertEqual(fenced, source)

    def test_existing_fence_preserves_crlf_exactly(self):
        source = "```cpp\r\nint value = 1;\r\n```\r\n"

        fenced, count = fence_unmarked_code_blocks(source)

        self.assertEqual(count, 0)
        self.assertEqual(fenced, source)

    def test_translation_never_sends_code_and_restores_it_exactly(self):
        translate_md = importlib.import_module("03_translate_md")
        source = """Before code.
UCLASS()
class RPG_API ARPGCharacter : public ACharacter
{
// Sets default values for this character's properties
GENERATED_BODY()
}
After code."""
        original_code = """```cpp
UCLASS()
class RPG_API ARPGCharacter : public ACharacter
{
// Sets default values for this character's properties
GENERATED_BODY()
}
```"""

        def fake_translate(request):
            self.assertNotIn("UCLASS()", request)
            self.assertNotIn("Sets default values", request)
            self.assertNotIn("DTS_CODE_BLOCK", request)
            if "Before code." in request:
                return "<!-- START -->\n翻译前文。\n<!-- END -->"
            return "<!-- START -->\n翻译后文。\n<!-- END -->"

        with patch.object(
            translate_md, "ds_translate", side_effect=fake_translate
        ) as mocked_translate:
            translated = translate_md.translate_with_deepseek(source, "zh")

        self.assertEqual(mocked_translate.call_count, 2)
        self.assertIn(original_code, translated)
        self.assertIn("// Sets default values for this character's properties", translated)

    def test_translation_preserves_consecutive_code_without_placeholders(self):
        translate_md = importlib.import_module("03_translate_md")
        blocks = [f"```cpp\nint value_{index} = {index};\n```" for index in range(8)]
        source = "\n\n".join(blocks[:7]) + "\n\nTranslate this.\n\n" + blocks[7]

        def fake_translate(request):
            self.assertNotIn("DTS_CODE_BLOCK", request)
            for block in blocks:
                self.assertNotIn(block, request)
            return "<!-- START -->\n翻译正文。\n<!-- END -->"

        with patch.object(
            translate_md, "ds_translate", side_effect=fake_translate
        ) as mocked_translate:
            translated = translate_md.translate_with_deepseek(source, "zh")

        self.assertEqual(mocked_translate.call_count, 1)
        self.assertIn("翻译正文。", translated)
        for block in blocks:
            self.assertIn(block, translated)
        valid, error = translate_md.validate_code_blocks(source, translated)
        self.assertTrue(valid, error)

    def test_translation_accepts_chunk_ending_with_code_block(self):
        translate_md = importlib.import_module("03_translate_md")
        source = "```cpp\n// Original comment\nint value = 1;\n```\n"

        with patch.object(
            translate_md,
            "ds_translate",
        ) as mocked_translate:
            translated = translate_md.translate_with_deepseek(source, "zh")

        mocked_translate.assert_not_called()
        self.assertEqual(
            translated,
            source,
        )

    def test_translation_removes_extra_fence_without_retrying(self):
        translate_md = importlib.import_module("03_translate_md")
        source = """```cpp
int first = 1;
```
Between.
```cpp
int second = 2;
```
More.
```cpp
int third = 3;
```"""

        def fake_translate(request):
            self.assertNotIn("DTS_CODE_BLOCK", request)
            self.assertNotIn("int first", request)
            prose = "模型新增围栏" if "Between." in request else "更多正文"
            return (
                f"<!-- START -->\n```markdown\n{prose}\n```\n<!-- END -->"
            )

        with patch.object(
            translate_md, "ds_translate", side_effect=fake_translate
        ) as mocked_translate:
            translated = translate_md.translate_with_deepseek(source, "zh")

        self.assertEqual(mocked_translate.call_count, 2)
        self.assertEqual(len(translate_md.extract_fenced_code_blocks(translated)), 3)
        self.assertIn("模型新增围栏", translated)
        valid, error = translate_md.validate_code_blocks(source, translated)
        self.assertTrue(valid, error)


if __name__ == "__main__":
    unittest.main()
