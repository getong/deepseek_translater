#!/usr/bin/env python3
"""
pdf2md.py - 快速将 PDF 转换为 Markdown，保持链接和标题级别
用法: python pdf2md.py input.pdf [output.md]
"""

import sys
import os
import re
from collections import defaultdict

try:
    import fitz  # PyMuPDF
except ImportError:
    print("请先安装 PyMuPDF: pip install PyMuPDF")
    sys.exit(1)


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
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
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


def get_text_with_links_and_headings(page, page_links, body_size, heading_map):
    """提取页面文本，嵌入链接并识别标题"""
    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
    
    result_lines = []
    
    for block in blocks:
        if block["type"] != 0:  # 跳过图片块
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
    
    doc = fitz.open(pdf_path)
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
    
    # 第二遍：提取内容
    print("提取内容...")
    for page_num in range(total_pages):
        page = doc[page_num]
        
        # 获取页面链接
        page_links = extract_links_from_page(page)
        
        # 提取带链接和标题的文本
        page_content = get_text_with_links_and_headings(page, page_links, body_size, heading_map)
        
        if page_content.strip():
            all_content.append(page_content)
        
        # 进度显示
        if (page_num + 1) % 10 == 0 or page_num == total_pages - 1:
            print(f"  处理进度: {page_num + 1}/{total_pages}")
    
    doc.close()
    
    # 合并内容
    markdown_content = "\n\n".join(all_content)
    
    # 清理多余空行
    markdown_content = re.sub(r'\n{3,}', '\n\n', markdown_content)
    
    # 写入文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(markdown_content)
    
    file_size = os.path.getsize(output_path)
    print(f"✓ 转换完成: {output_path} ({file_size:,} 字节)")
    
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
