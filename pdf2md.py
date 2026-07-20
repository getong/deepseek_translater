#!/usr/bin/env python3
"""
pdf2md.py - 快速将 PDF 转换为 Markdown，保持链接和标题级别
用法: python pdf2md.py input.pdf [output.md]
"""

import sys
import os
import re
import io
from collections import defaultdict
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("请先安装 PyMuPDF: pip install PyMuPDF")
    sys.exit(1)


PDF_TEXT_FLAGS = fitz.TEXTFLAGS_DICT | fitz.TEXT_PRESERVE_WHITESPACE
PDF_IMAGE_CACHE_MARKER = ".pdf_images_v1"


def extract_links_from_page(page):
    """提取页面中的所有链接"""
    links = {}
    for link in page.get_links():
        if link.get("uri"):  # 外部链接
            rect = link["from"]
            links[tuple(rect)] = link["uri"]
    return links


def analyze_font_sizes(doc):
    """分析整个文档的字体大小分布，确定标题阈值"""
    font_sizes = defaultdict(int)
    
    for page in doc:
        blocks = page.get_text("dict", flags=PDF_TEXT_FLAGS)["blocks"]
        for block in blocks:
            if block["type"] != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = round(span["size"], 1)
                    text = span["text"].strip()
                    if text:
                        font_sizes[size] += len(text)
    
    if not font_sizes:
        return 12, {}  # 默认值
    
    # 找出最常用的字体大小（正文大小）
    body_size = max(font_sizes, key=font_sizes.get)
    
    # 按字体大小排序，确定标题级别
    sorted_sizes = sorted(font_sizes.keys(), reverse=True)
    
    # 建立字体大小到标题级别的映射
    heading_map = {}
    heading_level = 1
    
    for size in sorted_sizes:
        if size > body_size * 1.15:  # 比正文大15%以上才算标题
            if heading_level <= 6:
                heading_map[size] = heading_level
                heading_level += 1
        else:
            break
    
    return body_size, heading_map


def save_image_block(block, images_dir, page_num, image_num):
    """将 PyMuPDF 图片块保存为 HTML/PDF 转换器普遍支持的格式。"""
    image_data = block.get("image")
    if not image_data:
        raise ValueError("图片块不包含图像数据")

    source_ext = block.get("ext", "").lower()
    images_dir = Path(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    filename_base = f"image_p{page_num:04d}_{image_num}"

    # PyMuPDF may return JPEG 2000 (jpx). Browsers do not reliably render it,
    # even when it is renamed to .jpg, so transcode unsupported formats.
    if source_ext == "png":
        filename = f"{filename_base}.png"
        (images_dir / filename).write_bytes(image_data)
    elif source_ext in {"jpg", "jpeg"}:
        filename = f"{filename_base}.jpg"
        (images_dir / filename).write_bytes(image_data)
    else:
        try:
            from PIL import Image

            with Image.open(io.BytesIO(image_data)) as image:
                has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
                if has_alpha:
                    filename = f"{filename_base}.png"
                    image.save(images_dir / filename, format="PNG", optimize=True)
                else:
                    filename = f"{filename_base}.jpg"
                    if image.mode not in {"RGB", "L"}:
                        image = image.convert("RGB")
                    image.save(
                        images_dir / filename,
                        format="JPEG",
                        quality=92,
                        optimize=True,
                    )
        except Exception as exc:
            raise ValueError(
                f"无法转换第 {page_num + 1} 页的第 {image_num + 1} 张图片"
            ) from exc

    return (Path("images") / filename).as_posix()


def save_rect_as_image(page, rect, images_dir, page_num, image_num):
    """将 PyMuPDF 矩形区域渲染为图片并保存"""
    images_dir = Path(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    filename = f"image_p{page_num:04d}_{image_num}.png"
    pix = page.get_pixmap(clip=rect, dpi=200)
    pix.save(images_dir / filename)
    return (Path("images") / filename).as_posix()


def get_figure_rects(page, blocks, expand=20):
    page_w = page.rect.width
    page_h = page.rect.height

    drawings = page.get_drawings()
    rects = []
    for d in drawings:
        r = d["rect"]
        if r.width > page_w * 0.9 and r.height > page_h * 0.9:
            continue
        rects.append(r)

    rects.extend([fitz.Rect(b["bbox"]) for b in blocks if b["type"] == 1])
    
    if not rects:
        return []
    
    merged = []
    for r in rects:
        expanded_r = r + (-expand, -expand, expand, expand)
        intersected = []
        for i, mr in enumerate(merged):
            if (mr + (-expand, -expand, expand, expand)).intersects(expanded_r):
                intersected.append(i)
                
        if not intersected:
            merged.append(r)
        else:
            new_r = r
            for i in sorted(intersected, reverse=True):
                new_r = new_r | merged[i]
                del merged[i]
            merged.append(new_r)
            
    final_rects = [mr for mr in merged if mr.width > 20 and mr.height > 20]
    return final_rects


def get_text_with_links_and_headings(
    page,
    page_links,
    body_size,
    heading_map,
    images_dir=None,
    page_num=0,
):
    """提取页面文本和图片，嵌入链接并识别标题。"""
    # PDF content streams are not necessarily in visual order. Sorting keeps a
    # figure between its introducing paragraph and caption instead of moving it
    # into a later translation chunk.
    blocks = page.get_text("dict", flags=PDF_TEXT_FLAGS, sort=True)["blocks"]
    
    figure_rects = get_figure_rects(page, blocks, expand=20)
    yielded_figures = set()
    result_lines = []
    
    for block in blocks:
        b_rect = fitz.Rect(block["bbox"])
        b_area = b_rect.get_area()
        overlapping_fig_idx = None

        for i, r in enumerate(figure_rects):
            intersect = r & b_rect
            intersect_area = intersect.get_area()
            if (b_area > 0 and intersect_area > 0.6 * b_area) or (block["type"] == 1 and intersect_area > 0):
                overlapping_fig_idx = i
                break

        if overlapping_fig_idx is not None:
            if overlapping_fig_idx not in yielded_figures:
                if images_dir is not None:
                    image_path = save_rect_as_image(page, figure_rects[overlapping_fig_idx], images_dir, page_num, overlapping_fig_idx)
                    result_lines.append(f"\n![]({image_path})\n")
                yielded_figures.add(overlapping_fig_idx)
            continue
            
        if block["type"] == 1:
            # 回退：如果图片块由于某种原因不在 figure_rects 中
            if images_dir is not None:
                fallback_idx = overlapping_fig_idx or (len(figure_rects) + 999)
                image_path = save_image_block(block, images_dir, page_num, fallback_idx)
                result_lines.append(f"\n![]({image_path})\n")
            continue

        if block["type"] != 0:
            continue
            
        for line in block.get("lines", []):
            line_text = ""
            line_font_sizes = []
            is_bold = False
            
            for span in line.get("spans", []):
                text = span["text"]
                font_size = round(span["size"], 1)
                font_flags = span.get("flags", 0)
                span_rect = fitz.Rect(span["bbox"])
                
                # 检测粗体 (flags & 2^4 = 16 表示粗体)
                if font_flags & 16:
                    is_bold = True
                
                line_font_sizes.append(font_size)
                
                # 检查这个文本是否有链接
                link_url = None
                for rect_tuple, url in page_links.items():
                    link_rect = fitz.Rect(rect_tuple)
                    if span_rect.intersects(link_rect):
                        link_url = url
                        break
                
                if link_url and text.strip():
                    line_text += f"[{text}]({link_url})"
                else:
                    line_text += text
            
            if line_text.strip():
                # 判断是否为标题
                if line_font_sizes:
                    max_font_size = max(line_font_sizes)
                    
                    # 检查是否匹配标题字体大小
                    heading_level = heading_map.get(max_font_size)
                    
                    # 额外条件：短文本 + 大字体/粗体 更可能是标题
                    text_stripped = line_text.strip()
                    is_short = len(text_stripped) < 100
                    
                    if heading_level and is_short:
                        prefix = "#" * heading_level + " "
                        line_text = prefix + text_stripped
                    elif is_bold and max_font_size >= body_size * 1.1 and is_short:
                        # 粗体且稍大的短文本，作为次级标题
                        line_text = "### " + text_stripped
                
                result_lines.append(line_text)
    
    # 确保没有被块覆盖的纯矢量图也输出
    for i, r in enumerate(figure_rects):
        if i not in yielded_figures:
            if images_dir is not None:
                image_path = save_rect_as_image(page, r, images_dir, page_num, i)
                result_lines.append(f"\n![]({image_path})\n")
    
    return "\n".join(result_lines)


def pdf_to_markdown(pdf_path, output_path=None):
    """将 PDF 转换为 Markdown"""
    if not os.path.exists(pdf_path):
        print(f"错误: 文件不存在 - {pdf_path}")
        sys.exit(1)
    
    if output_path is None:
        output_path = os.path.splitext(pdf_path)[0] + ".md"
    
    print(f"正在转换: {pdf_path}")
    print(f"输出文件: {output_path}")
    
    output_path = os.path.abspath(output_path)
    images_dir = Path(output_path).parent / "images"
    doc = fitz.open(pdf_path)
    try:
        total_pages = len(doc)
        print(f"总页数: {total_pages}")

        # 第一遍：分析字体大小分布
        print("分析文档结构...")
        body_size, heading_map = analyze_font_sizes(doc)
        print(f"  正文字体大小: {body_size}")
        if heading_map:
            print(f"  检测到标题级别: {len(heading_map)} 种")
            for size, level in sorted(heading_map.items(), reverse=True):
                print(f"    H{level}: {size}pt")

        all_content = []

        # 第二遍：按页面内容顺序提取文本和图片
        print("提取内容和图片...")
        for page_num in range(total_pages):
            page = doc[page_num]
            page_links = extract_links_from_page(page)
            page_content = get_text_with_links_and_headings(
                page,
                page_links,
                body_size,
                heading_map,
                images_dir=images_dir,
                page_num=page_num,
            )

            if page_content.strip():
                all_content.append(page_content)

            if (page_num + 1) % 10 == 0 or page_num == total_pages - 1:
                print(f"  处理进度: {page_num + 1}/{total_pages}")
    finally:
        doc.close()
    
    # 合并内容
    markdown_content = "\n\n".join(all_content)
    
    # 清理多余空行
    markdown_content = re.sub(r'\n{3,}', '\n\n', markdown_content)
    
    # 写入文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(markdown_content)

    (Path(output_path).parent / PDF_IMAGE_CACHE_MARKER).write_text(
        "PDF images extracted with web-compatible encoding.\n",
        encoding="utf-8",
    )
    
    file_size = os.path.getsize(output_path)
    print(f"✓ 转换完成: {output_path} ({file_size:,} 字节)")
    image_count = len(list(images_dir.glob("image_*"))) if images_dir.exists() else 0
    print(f"✓ 提取图片: {image_count} 张 -> {images_dir}")
    
    return output_path


def main():
    if len(sys.argv) < 2:
        print("用法: python pdf2md.py <input.pdf> [output.md]")
        print("示例: python pdf2md.py book.pdf")
        print("      python pdf2md.py book.pdf book_output.md")
        sys.exit(1)
    
    input_pdf = sys.argv[1]
    output_md = sys.argv[2] if len(sys.argv) > 2 else None
    
    pdf_to_markdown(input_pdf, output_md)


if __name__ == "__main__":
    main()
