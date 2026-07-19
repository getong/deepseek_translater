#!/usr/bin/env python3
"""
01_ocr_to_md.py - Convert scanned PDF/images to Markdown using OCR API
For books that are OCR-scanned (each page is an image)
"""

import os
import sys
import argparse
import requests
import glob
import tempfile
import shutil

# OCR API endpoint
#OCR_API_URL = "http://hemory.net:8092/ocr"
OCR_API_URL = "http://10.17.0.123:8092/ocr"

def convert_pdf_to_images(pdf_file, output_dir):
    """Convert PDF pages to images using PyMuPDF"""
    try:
        import fitz  # PyMuPDF

        print(f"Converting PDF to images: {pdf_file}")

        doc = fitz.open(pdf_file)
        total_pages = len(doc)
        print(f"Total pages: {total_pages}")

        image_files = []
        for page_num in range(total_pages):
            page = doc[page_num]
            # Render page to image with higher resolution for better OCR
            mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better quality
            pix = page.get_pixmap(matrix=mat)

            image_path = os.path.join(output_dir, f"page_{page_num + 1:04d}.png")
            pix.save(image_path)
            image_files.append(image_path)

            print(f"  Converted page {page_num + 1}/{total_pages}")

        doc.close()
        print(f"✓ Converted {total_pages} pages to images")
        return image_files

    except ImportError:
        print("✗ PyMuPDF (fitz) not found. Install with: pip install PyMuPDF")
        return None
    except Exception as e:
        print(f"✗ Error converting PDF to images: {e}")
        return None


def ocr_image(image_path):
    """Send image to OCR API and get markdown result"""
    try:
        print(f"  OCR processing: {os.path.basename(image_path)}")

        with open(image_path, 'rb') as f:
            files = {'file': (os.path.basename(image_path), f, 'image/png')}
            response = requests.post(OCR_API_URL, files=files, timeout=120)

        if response.status_code == 200:
            # API returns JSON: {"success": true, "content": "markdown..."}
            result = response.json()
            if result.get('success') == True:
                return result.get('content', '')
            else:
                print(f"  ✗ OCR API returned failure: {result}")
                return None
        else:
            print(f"  ✗ OCR API error: {response.status_code} - {response.text}")
            return None

    except requests.exceptions.Timeout:
        print(f"  ✗ OCR API timeout for {image_path}")
        return None
    except Exception as e:
        print(f"  ✗ OCR error: {e}")
        return None


def process_images_to_markdown(image_files, temp_dir):
    """Process each image through OCR and save as page_xxxx.md"""
    print(f"\nProcessing {len(image_files)} images through OCR...")

    page_md_files = []
    failed_pages = []

    for i, image_path in enumerate(image_files, 1):
        page_num = i
        md_file = os.path.join(temp_dir, f"page{page_num:04d}.md")

        # Skip if already exists
        if os.path.exists(md_file):
            print(f"  Skipping page {page_num} - already exists")
            page_md_files.append(md_file)
            continue

        markdown_content = ocr_image(image_path)

        if markdown_content:
            with open(md_file, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            page_md_files.append(md_file)
            print(f"  ✓ Page {page_num}/{len(image_files)} saved")
        else:
            failed_pages.append(page_num)
            print(f"  ✗ Page {page_num}/{len(image_files)} failed")

    if failed_pages:
        print(f"\n⚠️ Warning: {len(failed_pages)} pages failed OCR: {failed_pages}")

    print(f"✓ OCR completed: {len(page_md_files)} pages processed")
    return page_md_files


def merge_markdown_files(page_md_files, output_file):
    """Merge all page markdown files into input.md"""
    print(f"\nMerging {len(page_md_files)} markdown files...")

    # Sort files by page number
    page_md_files.sort()

    with open(output_file, 'w', encoding='utf-8') as outf:
        for i, md_file in enumerate(page_md_files):
            with open(md_file, 'r', encoding='utf-8') as inf:
                content = inf.read()

            if i > 0:
                outf.write('\n\n')  # Add separator between pages

            outf.write(content)

    file_size = os.path.getsize(output_file)
    print(f"✓ Merged to {output_file} ({file_size} bytes)")
    return True


def create_config_file(temp_dir, input_file, input_lang, output_lang):
    """Create config.txt file for the pipeline"""
    config_file = os.path.join(temp_dir, "config.txt")

    config_content = f"""# Translation Configuration
input_file={input_file}
input_lang={input_lang}
output_lang={output_lang}
conversion_method=ocr
"""

    with open(config_file, 'w', encoding='utf-8') as f:
        f.write(config_content)

    print(f"✓ Created config file: {config_file}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Convert scanned PDF to markdown using OCR API"
    )
    parser.add_argument("input_file", help="Input PDF file (scanned/OCR type)")
    parser.add_argument("--temp-dir", help="Output temp directory (default: current directory/input-name_temp)")
    parser.add_argument("-l", "--ilang", default="auto", help="Input language (default: auto)")
    parser.add_argument("--olang", default="zh", help="Output language (default: zh)")

    args = parser.parse_args()

    input_file = args.input_file

    if not os.path.exists(input_file):
        print(f"Error: Input file not found: {input_file}")
        sys.exit(1)

    # Check file extension
    file_ext = os.path.splitext(input_file)[1].lower()
    if file_ext != '.pdf':
        print(f"Error: Only PDF files are supported for OCR mode")
        print(f"Got: {file_ext}")
        sys.exit(1)

    print("=== OCR-based PDF to Markdown Conversion ===")
    print(f"Input file: {input_file}")
    print(f"OCR API: {OCR_API_URL}")
    print()

    # Create temp directory
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    temp_dir = args.temp_dir or f"{base_name}_temp"
    os.makedirs(temp_dir, exist_ok=True)

    # Create images subdirectory for PDF page images
    images_dir = os.path.join(temp_dir, "ocr_images")
    os.makedirs(images_dir, exist_ok=True)

    try:
        # Step 1: Convert PDF to images
        image_files = convert_pdf_to_images(input_file, images_dir)
        if not image_files:
            sys.exit(1)

        # Step 2: OCR each image to markdown
        page_md_files = process_images_to_markdown(image_files, temp_dir)
        if not page_md_files:
            print("Error: No pages were successfully processed")
            sys.exit(1)

        # Step 3: Merge all page markdown files into input.md
        input_md = os.path.join(temp_dir, "input.md")
        if not merge_markdown_files(page_md_files, input_md):
            sys.exit(1)

        # Step 4: Create config file
        create_config_file(temp_dir, input_file, args.ilang, args.olang)

        print("\n" + "=" * 50)
        print("✓ OCR conversion completed successfully!")
        print(f"✓ Temp directory: {temp_dir}")
        print(f"✓ Page files: {len(page_md_files)} files")
        print(f"✓ Input markdown: {input_md}")
        print("✓ Ready for translation pipeline")

    except KeyboardInterrupt:
        print("\nConversion interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
