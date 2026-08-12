#!/usr/bin/env python3
"""
Step 3: Translate markdown files using DeepSeek API
Translates each pageXXXX.md file to output_pageXXXX.md
"""

import os
import sys
import glob
import time
import argparse
import re
from collections import Counter

from deepseek_client import translate as ds_translate, check_api
from markdown_cleanup import remove_internal_anchor_artifacts
from markdown_code import (
    fence_unmarked_code_blocks,
    partition_fenced_code_blocks,
    remove_model_added_code_fences,
    restore_source_code_in_translation,
)


def load_config(temp_dir):
    """Load configuration from step 1"""
    config_file = os.path.join(temp_dir, 'config.txt')
    if not os.path.exists(config_file):
        print("Error: config.txt not found. Run 01_prepare_env.py first.")
        sys.exit(1)

    config = {}
    with open(config_file, 'r', encoding='utf-8') as f:
        for line in f:
            if '=' in line:
                key, value = line.strip().split('=', 1)
                config[key] = value

    return config


def get_language_name(lang_code):
    """Convert language code to full name"""
    lang_map = {
        'zh': 'Chinese',
        'en': 'English',
        'ja': 'Japanese',
        'ko': 'Korean',
        'fr': 'French',
        'de': 'German',
        'es': 'Spanish',
        'it': 'Italian',
        'pt': 'Portuguese',
        'ru': 'Russian',
        'ar': 'Arabic',
        'hi': 'Hindi',
        'th': 'Thai',
        'vi': 'Vietnamese'
    }
    return lang_map.get(lang_code.lower(), lang_code)


def create_translation_prompt(output_lang, custom_prompt=None):
    """Create translation prompt with optional custom additions"""
    lang_name = get_language_name(output_lang)

    base_prompt = f"""请翻译markdown文件为 {lang_name}. 
IMPORTANT REQUIREMENTS:
1.	严格保持 Markdown 格式不变，包括标题、链接、图片引用等
2.	仅翻译文字内容，保留所有 Markdown 语法和文件名
3.	删除页码、空链接、不必要的字符和如: 行末的'\\' 
4.	删除只有数字的行，那可能是页码
5. 保证格式和语义准确翻译内容自然流畅
6.	只输出翻译后的正文内容，不要有任何说明、提示、注释或对话内容。
7.  CRITICAL OUTPUT FORMAT: 你的回复必须严格遵循以下格式：
    - 第一行必须是：<!-- START -->
    - 然后是翻译后的markdown内容
    - 最后一行必须是：<!-- END -->
    - 不要在这些标记之前或之后添加任何说明、警告、代码块标记或其他内容
    - 不要在正文外额外包裹markdown代码块；原文已有的代码围栏必须原样保留
    - 不要输出任何解释性文字或元数据
    - 不要输出"我来帮您翻译"、"以下是翻译结果"等开场白
    - 不要输出任何关于翻译质量、注意事项的说明
    - 严格按照三行格式输出：<!-- START -->、翻译内容、<!-- END -->
    - “翻译内容”前后不要添加方括号、圆括号、引号或其他包装符号
    - 如果输出不符合此格式，系统将重新请求翻译
8.  表达清晰简洁，不要使用复杂的句式。请严格按顺序翻译，不要跳过任何内容。
9.  必须保留所有图片引用，包括：
    - 只保留原文中实际存在的 ![alt](path) 图片引用，并且必须完整保留
    - 图片文件名和路径不要修改
    - 图片alt文本可以翻译，但必须保留图片引用结构
    - 不要删除、过滤或忽略任何图片相关内容
    - 绝对不要根据 Figure、Figure 1.1、图注或上下文自行新增图片引用
    - 普通 Figure/图注文本仍然是普通文本，只翻译文字，不要转换成 ![]() 语法
10. 智能识别和处理多级标题，按照以下规则添加markdown标记：
    - 主标题（书名、章节名等）使用 # 标记
    - 一级标题（大节标题）使用 ## 标记  
    - 二级标题（小节标题）使用 ### 标记
    - 三级标题（子标题）使用 #### 标记
    - 四级及以下标题使用 ##### 标记
11. 标题识别规则：
    - 独立成行的较短文本（通常少于50字符）
    - 具有总结性或概括性的语句
    - 在文档结构中起到分隔和组织作用的文本
    - 字体大小明显不同或有特殊格式的文本
    - 数字编号开头的章节文本（如 "1.1 概述"、"第三章"等）
12. 标题层级判断：
    - 根据上下文和内容重要性判断标题层级
    - 章节类标题通常为高层级（# 或 ##）
    - 小节、子节标题依次降级（### #### #####）
    - 保持同一文档内标题层级的一致性
13. 注意事项：
    - 不要过度添加标题标记，只对真正的标题文本添加
    - 正文段落不要添加标题标记
    - 如果原文已有markdown标题标记，保持其层级结构
14. 严格保护代码：
    - 源代码块已由系统从待翻译正文中分离，并将在翻译后按原位置逐字符恢复
    - 不要自行补写、概括或重复任何源代码，也不要添加代码围栏
    - 行内代码、API名称、类型名、函数名、文件路径和命令必须原样保留
15. 不要输出 idx_bf7c433d 这类 idx_ 加十六进制哈希的内部索引锚点"""
    if custom_prompt:
        base_prompt += f"\n\nADDITIONAL INSTRUCTIONS:\n{custom_prompt}"

    base_prompt += "\n\n markdown文件正文:"

    return base_prompt


def extract_content_between_markers(text):
    """Extract marked content, tolerating a missing END on complete responses."""
    start_marker = '<!-- START -->'
    end_marker = '<!-- END -->'

    start_pos = text.find(start_marker)
    end_pos = text.find(end_marker)

    if start_pos == -1:
        for variation in ['<!--START-->', '<!-- START-->', '<!--START -->', '<!-- START-->']:
            start_pos = text.find(variation)
            if start_pos != -1:
                start_marker = variation
                break

    if end_pos == -1:
        for variation in ['<!--END-->', '<!-- END-->', '<!--END -->', '<!-- END-->']:
            end_pos = text.find(variation)
            if end_pos != -1:
                end_marker = variation
                break

    if start_pos != -1 and end_pos != -1 and start_pos < end_pos:
        content_start = start_pos + len(start_marker)
        extracted = text[content_start:end_pos].strip()
        return extracted

    if start_pos != -1 and end_pos == -1:
        content_start = start_pos + len(start_marker)
        extracted = text[content_start:].strip()
        if extracted:
            print("    Warning: END marker missing; accepting normally completed response")
            return extracted

    return None


def extract_fenced_code_blocks(text):
    """Return fenced code blocks with their exact fences and body text."""
    blocks = []
    opening = None
    body_lines = []

    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if opening is None:
            match = re.match(r'^(`{3,}|~{3,})[^\r\n]*(?:\r?\n)?$', stripped)
            if match:
                opening = (line, match.group(1)[0], len(match.group(1)))
                body_lines = []
            continue

        opening_line, fence_char, fence_length = opening
        closing_pattern = rf'^{re.escape(fence_char)}{{{fence_length},}}[ \t]*(?:\r?\n)?$'
        if re.match(closing_pattern, stripped):
            blocks.append((opening_line, ''.join(body_lines), line))
            opening = None
            body_lines = []
        else:
            body_lines.append(line)

    return blocks


def validate_code_blocks(source, translated):
    """Ensure every fenced code block is copied byte-for-byte."""
    source_blocks = extract_fenced_code_blocks(source)
    translated_blocks = extract_fenced_code_blocks(translated)

    if len(source_blocks) != len(translated_blocks):
        return False, (
            "code block count changed "
            f"({len(source_blocks)} -> {len(translated_blocks)})"
        )

    for index, (source_block, translated_block) in enumerate(
        zip(source_blocks, translated_blocks), 1
    ):
        source_opening, source_body, source_closing = source_block
        translated_opening, translated_body, translated_closing = translated_block
        if source_opening != translated_opening:
            return False, f"code block {index} opening fence changed"
        if source_body != translated_body:
            return False, f"code block {index} body was not copied exactly"
        if source_closing.rstrip('\r\n') != translated_closing.rstrip('\r\n'):
            return False, f"code block {index} closing fence changed"

    return True, None


MARKDOWN_IMAGE_PATTERN = re.compile(
    r'!\[(?P<alt>[^\]]*)\]\(\s*'
    r'(?:<(?P<angle_path>[^>\n]+)>|(?P<plain_path>[^\s)\n]+))'
    r'(?:\s+(?:"[^"\n]*"|\'[^\'\n]*\'|\([^\)\n]*\)))?\s*\)',
    re.MULTILINE,
)


def extract_markdown_image_paths(text):
    """Return local/remote image paths in Markdown order, ignoring translated alt text."""
    return [
        match.group('angle_path') or match.group('plain_path')
        for match in MARKDOWN_IMAGE_PATTERN.finditer(text)
    ]


def remove_added_image_references(source, translated):
    """Turn model-added image syntax back into its translated alt text."""
    source_paths = extract_markdown_image_paths(source)
    translated_matches = list(MARKDOWN_IMAGE_PATTERN.finditer(translated))
    if len(translated_matches) <= len(source_paths):
        return translated, 0

    remaining_paths = Counter(source_paths)
    replacements = []
    for match in translated_matches:
        image_path = match.group('angle_path') or match.group('plain_path')
        if remaining_paths[image_path] > 0:
            remaining_paths[image_path] -= 1
            continue
        replacements.append((match.start(), match.end(), match.group('alt')))

    corrected = translated
    for start, end, alt_text in reversed(replacements):
        corrected = corrected[:start] + alt_text + corrected[end:]

    is_valid, _ = validate_image_references(source, corrected)
    if not is_valid:
        return translated, 0
    return corrected, len(replacements)


def validate_image_references(source, translated):
    """Ensure translation preserves every image path in its original order."""
    source_paths = extract_markdown_image_paths(source)
    translated_paths = extract_markdown_image_paths(translated)
    if source_paths == translated_paths:
        return True, None

    if len(source_paths) != len(translated_paths):
        return False, (
            f"image reference count changed "
            f"({len(source_paths)} -> {len(translated_paths)})"
        )

    for index, (source_path, translated_path) in enumerate(
        zip(source_paths, translated_paths), 1
    ):
        if source_path != translated_path:
            return False, (
                f"image path {index} changed "
                f"({source_path!r} -> {translated_path!r})"
            )

    return False, "image reference order changed"


def _translate_prose_with_deepseek(text, output_lang, custom_prompt=None, max_retries=3):
    """Translate one code-free prose segment with retries."""
    prompt = create_translation_prompt(output_lang, custom_prompt)

    for attempt in range(max_retries):
        if attempt > 0:
            print(f"    Retry attempt {attempt + 1}/{max_retries}")
            time.sleep(1)

        try:
            full_input = f"{prompt}\n\n{text}"

            print(f"    Starting DeepSeek translation (attempt {attempt + 1})...")
            translated_text = ds_translate(full_input)

            if translated_text is None:
                print(f"    Attempt {attempt + 1}: DeepSeek API returned None")
                continue

            extracted_content = extract_content_between_markers(translated_text)

            if extracted_content and len(extracted_content.strip()) > 0:
                extracted_content, removed_anchors = remove_internal_anchor_artifacts(
                    extracted_content
                )
                if removed_anchors:
                    print(f"    Removed {removed_anchors} internal anchor(s) from translation")
                extracted_content, removed_code_fences = remove_model_added_code_fences(
                    extracted_content
                )
                if removed_code_fences:
                    print(
                        f"    Removed {removed_code_fences} model-added code "
                        "fence(s) from translated prose"
                    )
                extracted_content, removed_images = remove_added_image_references(
                    text, extracted_content
                )
                if removed_images:
                    print(
                        f"    Corrected {removed_images} model-added image "
                        "reference(s), preserving their alt text"
                    )
                images_are_valid, image_error = validate_image_references(text, extracted_content)
                if not images_are_valid:
                    print(f"    Attempt {attempt + 1}: Rejected translation because {image_error}")
                    continue
                code_is_valid, code_error = validate_code_blocks(text, extracted_content)
                if not code_is_valid:
                    print(f"    Attempt {attempt + 1}: Rejected translation because {code_error}")
                    continue
                if attempt > 0:
                    print(f"    Translation successful on attempt {attempt + 1}")
                return extracted_content
            else:
                print(f"    Attempt {attempt + 1}: Failed to extract content between START/END markers")
                print(f"    Raw output (first 300 chars): {translated_text[:300]}...")

                has_start = False
                has_end = False

                start_variations = ['<!-- START -->', '<!--START-->', '<!-- START-->', '<!--START -->']
                end_variations = ['<!-- END -->', '<!--END-->', '<!-- END-->', '<!--END -->']

                for var in start_variations:
                    if var in translated_text:
                        has_start = True
                        break

                for var in end_variations:
                    if var in translated_text:
                        has_end = True
                        break

                if not has_start:
                    print(f"    No START marker found")
                if not has_end:
                    print(f"    No END marker found")

                if has_start and has_end:
                    print(f"    Attempting emergency extraction...")
                    lines = translated_text.split('\n')
                    start_line = -1
                    end_line = -1

                    for i, line in enumerate(lines):
                        if any(marker in line for marker in start_variations):
                            start_line = i
                        if any(marker in line for marker in end_variations):
                            end_line = i
                            break

                    if start_line != -1 and end_line != -1 and start_line < end_line:
                        emergency_content = '\n'.join(lines[start_line+1:end_line]).strip()
                        if emergency_content:
                            emergency_content, removed_anchors = remove_internal_anchor_artifacts(
                                emergency_content
                            )
                            if removed_anchors:
                                print(
                                    f"    Removed {removed_anchors} internal anchor(s) "
                                    "from emergency extraction"
                                )
                            emergency_content, removed_code_fences = (
                                remove_model_added_code_fences(emergency_content)
                            )
                            if removed_code_fences:
                                print(
                                    f"    Removed {removed_code_fences} model-added "
                                    "code fence(s) from emergency extraction"
                                )
                            emergency_content, removed_images = remove_added_image_references(
                                text, emergency_content
                            )
                            if removed_images:
                                print(
                                    f"    Corrected {removed_images} model-added image "
                                    "reference(s), preserving their alt text"
                                )
                            images_are_valid, image_error = validate_image_references(
                                text, emergency_content
                            )
                            if not images_are_valid:
                                print(
                                    "    Emergency extraction rejected because "
                                    f"{image_error}"
                                )
                                continue
                            code_is_valid, code_error = validate_code_blocks(text, emergency_content)
                            if code_is_valid:
                                print(f"    Emergency extraction successful")
                                return emergency_content
                            print(f"    Emergency extraction rejected because {code_error}")

                continue

        except Exception as e:
            print(f"    Attempt {attempt + 1}: Error calling DeepSeek API: {e}")
            continue

    print(f"    Translation failed after {max_retries} attempts, skipping file")
    return None


def _surrounding_whitespace(text):
    """Return leading whitespace, body, and trailing whitespace."""
    leading_match = re.match(r"\s*", text)
    leading = leading_match.group(0)
    remainder = text[len(leading):]
    if not remainder:
        return text, "", ""

    trailing_match = re.search(r"\s*$", remainder)
    trailing = trailing_match.group(0)
    body = remainder[:-len(trailing)] if trailing else remainder
    return leading, body, trailing


def translate_with_deepseek(text, output_lang, custom_prompt=None, max_retries=3):
    """Translate prose while restoring every source code block exactly."""
    text, code_block_count = fence_unmarked_code_blocks(text)
    if code_block_count:
        print(f"    Protected {code_block_count} unmarked code block(s)")

    text, removed_source_anchors = remove_internal_anchor_artifacts(text)
    if removed_source_anchors:
        print(f"    Removed {removed_source_anchors} internal anchor(s) before translation")

    segments = partition_fenced_code_blocks(text)
    source_code_count = sum(is_code for is_code, _ in segments)
    prose_count = sum(
        not is_code and bool(segment.strip()) for is_code, segment in segments
    )
    if source_code_count:
        print(
            f"    Preserving {source_code_count} source code block(s); "
            f"translating {prose_count} prose segment(s)"
        )

    translated_segments = []
    prose_number = 0
    for is_code, segment in segments:
        if is_code or not segment.strip():
            translated_segments.append(segment)
            continue

        prose_number += 1
        if prose_count > 1:
            print(f"    Translating prose segment {prose_number}/{prose_count}")
        leading, body, trailing = _surrounding_whitespace(segment)
        translated = _translate_prose_with_deepseek(
            body, output_lang, custom_prompt, max_retries
        )
        if translated is None:
            return None
        translated_segments.append(leading + translated + trailing)

    translated_text = "".join(translated_segments)
    images_are_valid, image_error = validate_image_references(text, translated_text)
    if not images_are_valid:
        print(f"    Translation rejected after code restoration because {image_error}")
        return None
    code_is_valid, code_error = validate_code_blocks(text, translated_text)
    if not code_is_valid:
        print(f"    Translation rejected after code restoration because {code_error}")
        return None
    return translated_text


def translate_markdown_files(temp_dir, output_lang, custom_prompt=None):
    """Translate all markdown files in temp directory"""
    print(f"Translating markdown files to {output_lang}...")
    if custom_prompt:
        print(f"Using custom prompt: {custom_prompt[:100]}...")

    md_files = glob.glob(os.path.join(temp_dir, 'page*.md'))
    md_files.sort()

    if not md_files:
        print("Error: No markdown files found. Run 02_split_to_md.py first.")
        sys.exit(1)

    total_files = len(md_files)
    translated_count = 0
    skipped_count = 0
    failed_count = 0

    for i, md_file in enumerate(md_files, 1):
        filename = os.path.basename(md_file)
        output_filename = f"output_{filename}"
        output_path = os.path.join(temp_dir, output_filename)

        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
            content, code_block_count = fence_unmarked_code_blocks(content)
            if code_block_count:
                with open(md_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(
                    f"  [{i}/{total_files}] Protected {code_block_count} "
                    f"code block(s) in {filename}"
                )
            content, removed_source_anchors = remove_internal_anchor_artifacts(content)
            if removed_source_anchors:
                print(
                    f"  [{i}/{total_files}] Removed {removed_source_anchors} "
                    f"internal anchor(s) from {filename}"
                )
        except Exception as e:
            print(f"    Error reading {filename}: {e}")
            failed_count += 1
            continue

        if os.path.exists(output_path):
            try:
                with open(output_path, 'r', encoding='utf-8') as f:
                    existing_translation = f.read()
                existing_translation, removed_anchors = remove_internal_anchor_artifacts(
                    existing_translation
                )
                if removed_anchors:
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(existing_translation)
                    print(
                        f"  [{i}/{total_files}] Removed {removed_anchors} internal "
                        f"anchor(s) from cached {output_filename}"
                    )
                existing_translation, repaired_code, repair_error = (
                    restore_source_code_in_translation(content, existing_translation)
                )
                if repaired_code:
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(existing_translation)
                    print(
                        f"  [{i}/{total_files}] Restored original code blocks in "
                        f"cached {output_filename}"
                    )
                images_are_valid, image_error = validate_image_references(
                    content, existing_translation
                )
                code_is_valid, code_error = validate_code_blocks(
                    content, existing_translation
                )
                if images_are_valid and code_is_valid:
                    print(f"  [{i}/{total_files}] Skipping {filename} (already translated)")
                    skipped_count += 1
                    continue
                reason = image_error if not images_are_valid else code_error
                if repair_error and not code_is_valid:
                    reason = repair_error
                print(f"  [{i}/{total_files}] Re-translating {filename}: {reason}")
            except OSError as exc:
                print(f"  [{i}/{total_files}] Could not validate existing output: {exc}")
        else:
            print(f"  [{i}/{total_files}] Translating {filename}...")

        if len(content.strip()) < 1:
            print(f"    Skipping {filename} (too short)")
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(content)
            skipped_count += 1
            continue

        translated_content = translate_with_deepseek(content, output_lang, custom_prompt)

        if translated_content:
            try:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(translated_content)
                print(f"    Translated and saved to {output_filename}")
                translated_count += 1
            except Exception as e:
                print(f"    Error saving {output_filename}: {e}")
                failed_count += 1
        else:
            print(f"    Failed to translate {filename} after retries, skipping file creation")
            failed_count += 1

        if i < total_files:
            time.sleep(0.5)

    print(f"\nTranslation complete:")
    print(f"  Translated: {translated_count}")
    print(f"  Skipped: {skipped_count}")
    print(f"  Failed: {failed_count}")
    print(f"  Total: {total_files}")
    return failed_count


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Book Translation Tool - Step 3: Translate Markdown using DeepSeek API"
    )

    parser.add_argument(
        '-p', '--prompt',
        default=None,
        help="Additional custom prompt to add to the translation instructions"
    )

    parser.add_argument(
        '--temp-dir',
        required=True,
        help="Temp directory path (required)"
    )

    parser.add_argument(
        '--output-lang',
        default=None,
        help="Override output language from config"
    )

    parser.add_argument(
        '--retry-failed',
        action='store_true',
        help="Retry translating files that failed previously"
    )

    return parser.parse_args()


def main():
    """Main function"""
    print("=== Book Translation Tool - Step 3: Translate Markdown (DeepSeek API) ===")

    args = parse_arguments()

    if not check_api():
        sys.exit(1)

    temp_dir = args.temp_dir
    if not os.path.exists(temp_dir):
        print(f"Error: Specified temp directory not found: {temp_dir}")
        sys.exit(1)

    print(f"Using temp directory: {temp_dir}")

    config = load_config(temp_dir)
    output_lang = args.output_lang or config['output_lang']

    print(f"Target language: {output_lang}")

    if args.prompt:
        print(f"Custom prompt: {args.prompt}")

    if args.retry_failed:
        print("Retry mode: removing potentially incomplete translation files...")
        output_files = glob.glob(os.path.join(temp_dir, 'output_page*.md'))
        for output_file in output_files:
            try:
                if os.path.getsize(output_file) < 50:
                    os.remove(output_file)
                    print(f"  Removed: {os.path.basename(output_file)}")
            except:
                pass

    failed_count = translate_markdown_files(temp_dir, output_lang, args.prompt)

    if failed_count:
        print(f"\nError: {failed_count} markdown file(s) failed to translate.")
        sys.exit(1)

    print("\n=== Step 3 Complete ===")
    print("Next step: Run 04_merge_md.py")


if __name__ == "__main__":
    main()
