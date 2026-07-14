#!/bin/bash

# bookread.sh - Archive a book as source markdown into the SSOT vault
#
# Converts a book (PDF/DOCX/EPUB) to markdown using the existing conversion
# scripts, then copies the untranslated source (config.txt + input.md) into:
#   /Users/bruce/git/sotvault/ssot/books/YYYY.MM/<original_title>/
#
# The destination folder is named after `original_title` from config.txt
# (sanitized for the filesystem). If it is empty, the input filename is used.
#
# Usage: ./bookread.sh [options] input_file
# Example: ./bookread.sh 7powers.epub
#          ./bookread.sh --ocr scanned_book.pdf

set -e  # Exit on any error

# Script information
SCRIPT_NAME="bookread.sh"
VERSION="1.0.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Output base directory (SSOT vault)
OUTPUT_BASE="/Users/bruce/git/sotvault/ssot/books"

# Default values
INPUT_FILE=""
INPUT_LANG="auto"
OUTPUT_LANG="zh"
OCR_MODE=false
CLEAN_TEMP=false
VERBOSE=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info()    { echo -e "${CYAN}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

show_help() {
    cat << EOF
${SCRIPT_NAME} v${VERSION} - Archive a book as source markdown into the SSOT vault

USAGE:
    ${SCRIPT_NAME} [OPTIONS] INPUT_FILE

DESCRIPTION:
    1. Converts INPUT_FILE to a temp directory (config.txt + input.md) using the
       existing conversion scripts (Calibre HTMLZ, or OCR for scanned PDFs).
    2. Reads original_title from config.txt (falls back to the input filename
       if empty), and sanitizes it into a valid directory name.
    3. Creates ${OUTPUT_BASE}/YYYY.MM/<original_title>/ and copies config.txt
       into it, plus input.md renamed to book.md.

OPTIONS:
    -l, --ilang LANG   Input language (default: auto)
    --olang LANG       Output language for conversion metadata (default: zh)
    --ocr              Use OCR mode for scanned PDF (each page is an image)
    --clean            Remove the temp directory before converting
    -v, --verbose      Enable verbose output
    -h, --help         Show this help message

EXAMPLES:
    ${SCRIPT_NAME} 7powers.epub
    ${SCRIPT_NAME} --ocr scanned_book.pdf
    ${SCRIPT_NAME} --clean book.docx
EOF
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -l|--ilang) INPUT_LANG="$2"; shift 2 ;;
            --olang)    OUTPUT_LANG="$2"; shift 2 ;;
            --ocr)      OCR_MODE=true; shift ;;
            --clean)    CLEAN_TEMP=true; shift ;;
            -v|--verbose) VERBOSE=true; shift ;;
            -h|--help)  show_help; exit 0 ;;
            -*)
                log_error "Unknown option: $1"
                echo "Use -h or --help for usage information"
                exit 2
                ;;
            *)
                if [[ -z "$INPUT_FILE" ]]; then
                    INPUT_FILE="$1"
                else
                    log_error "Multiple input files specified"
                    exit 2
                fi
                shift
                ;;
        esac
    done

    if [[ -z "$INPUT_FILE" ]]; then
        log_error "Input file is required"
        echo "Use -h or --help for usage information"
        exit 2
    fi

    if [[ ! -f "$INPUT_FILE" ]]; then
        log_error "Input file not found: $INPUT_FILE"
        exit 5
    fi
}

# Setup / activate the Python virtual environment (shared with translatebook.sh)
setup_venv() {
    local venv_dir="${SCRIPT_DIR}/venv"
    if [[ ! -d "$venv_dir" ]]; then
        log_info "Creating Python virtual environment..."
        python3 -m venv "$venv_dir"
        source "$venv_dir/bin/activate"
        local requirements_file="${SCRIPT_DIR}/requirements.txt"
        log_info "Installing required Python packages..."
        if [[ -f "$requirements_file" ]]; then
            pip install -r "$requirements_file"
        else
            pip install python-docx PyMuPDF ebooklib beautifulsoup4 lxml markdown Pillow pdf2image pypandoc
        fi
        touch "$venv_dir/.packages_installed"
    else
        source "$venv_dir/bin/activate"
    fi
}

# Sanitize a string into a filesystem-safe directory name
sanitize_dirname() {
    local name="$1"
    # Replace characters forbidden on common filesystems (/ \ : * ? " < > |)
    name=$(printf '%s' "$name" | tr '/\\:*?"<>|' '_________')
    # Strip control characters
    name=$(printf '%s' "$name" | tr -d '\000-\037')
    # Collapse runs of whitespace into a single space
    name=$(printf '%s' "$name" | sed -E 's/[[:space:]]+/ /g')
    # Trim leading/trailing spaces and dots (dots are problematic on Windows)
    name=$(printf '%s' "$name" | sed -E 's/^[ .]+//; s/[ .]+$//')
    # Limit length to stay well under filesystem limits
    name=$(printf '%s' "$name" | cut -c1-200)
    printf '%s' "$name"
}

# Read a key from config.txt
read_config_value() {
    local config_file="$1"
    local key="$2"
    grep -E "^${key}=" "$config_file" 2>/dev/null | head -1 | cut -d'=' -f2-
}

# Convert the book into a temp directory containing config.txt and input.md
convert_book() {
    local ext="${INPUT_FILE##*.}"
    ext="$(echo "$ext" | tr '[:upper:]' '[:lower:]')"

    if [[ "$OCR_MODE" == true ]]; then
        if [[ "$ext" != "pdf" ]]; then
            log_error "OCR mode only supports PDF files"
            exit 2
        fi
        if [[ ! -f "${SCRIPT_DIR}/01_ocr_to_md.py" ]]; then
            log_error "OCR converter not found: 01_ocr_to_md.py"
            exit 3
        fi
        log_info "Converting PDF via OCR..."
        python3 "${SCRIPT_DIR}/01_ocr_to_md.py" "$INPUT_FILE" -l "$INPUT_LANG" --olang "$OUTPUT_LANG"
    else
        case "$ext" in
            pdf|docx|epub)
                if [[ ! -f "${SCRIPT_DIR}/01_convert_to_htmlz.py" ]]; then
                    log_error "File converter not found: 01_convert_to_htmlz.py"
                    exit 3
                fi
                log_info "Converting book via Calibre HTMLZ..."
                python3 "${SCRIPT_DIR}/01_convert_to_htmlz.py" "$INPUT_FILE" -l "$INPUT_LANG" --olang "$OUTPUT_LANG"
                ;;
            *)
                log_error "Unsupported file format: .$ext (supported: pdf, docx, epub)"
                exit 2
                ;;
        esac
    fi
}

main() {
    echo -e "${BLUE}================================${NC}"
    echo -e "${BLUE}  Book Reader v${VERSION}${NC}"
    echo -e "${BLUE}================================${NC}"
    echo ""

    parse_args "$@"

    # The converters create "<basename>_temp" in the current working directory,
    # so run everything from the script directory (where temp dirs live).
    cd "$SCRIPT_DIR"

    local base_name
    base_name="$(basename "$INPUT_FILE")"
    base_name="${base_name%.*}"
    local temp_dir="${SCRIPT_DIR}/${base_name}_temp"

    if [[ "$CLEAN_TEMP" == true && -d "$temp_dir" ]]; then
        log_info "Cleaning temp directory: $temp_dir"
        rm -rf "$temp_dir"
    fi

    setup_venv

    # Step 1: convert the book to a temp directory
    convert_book

    local config_file="${temp_dir}/config.txt"
    local input_md="${temp_dir}/input.md"

    if [[ ! -f "$config_file" ]]; then
        log_error "Expected config.txt not found: $config_file"
        exit 1
    fi
    if [[ ! -f "$input_md" ]]; then
        log_error "Expected input.md not found: $input_md"
        exit 1
    fi

    # Step 2: determine the destination folder name from original_title
    local original_title
    original_title="$(read_config_value "$config_file" "original_title")"

    if [[ -z "$original_title" ]]; then
        log_warning "original_title is empty in config.txt; using input filename instead"
        original_title="$base_name"
    fi

    local dir_name
    dir_name="$(sanitize_dirname "$original_title")"

    if [[ -z "$dir_name" ]]; then
        log_warning "original_title sanitized to an empty string; using input filename instead"
        dir_name="$(sanitize_dirname "$base_name")"
    fi
    if [[ -z "$dir_name" ]]; then
        log_error "Could not derive a valid directory name"
        exit 1
    fi

    # Step 3: create the output directory and copy the source files
    local month
    month="$(date +%Y.%m)"
    local dest_dir="${OUTPUT_BASE}/${month}/${dir_name}"

    log_info "Original title : $original_title"
    log_info "Directory name : $dir_name"
    log_info "Destination    : $dest_dir"

    mkdir -p "$dest_dir"
    cp "$config_file" "${dest_dir}/config.txt"
    cp "$input_md" "${dest_dir}/book.md"

    # Copy the images directory (referenced by book.md) if present
    local images_dir="${temp_dir}/images"
    local images_copied=false
    if [[ -d "$images_dir" ]]; then
        rm -rf "${dest_dir}/images"
        cp -R "$images_dir" "${dest_dir}/images"
        images_copied=true
    else
        log_warning "No images directory found in temp dir; skipping image copy"
    fi

    echo ""
    echo -e "${GREEN}================================${NC}"
    echo -e "${GREEN}  Book Archived!${NC}"
    echo -e "${GREEN}================================${NC}"
    echo -e "${GREEN}✓ config.txt:${NC} ${dest_dir}/config.txt"
    echo -e "${GREEN}✓ book.md:${NC}    ${dest_dir}/book.md"
    if [[ "$images_copied" == true ]]; then
        echo -e "${GREEN}✓ images:${NC}     ${dest_dir}/images/ ($(ls "${dest_dir}/images" | wc -l | tr -d ' ') files)"
    fi
    echo ""
    log_success "Done."
}

trap 'log_error "Script interrupted"; exit 1' INT TERM

main "$@"
