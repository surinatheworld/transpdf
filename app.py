"""
TransPDF — Ứng dụng dịch file PDF từ tiếng Anh sang tiếng Việt.

Luồng hoạt động:
    1. Người dùng upload file PDF tiếng Anh.
    2. Hệ thống trích xuất text + tọa độ từ PDF (PyMuPDF).
    3. Dịch text Anh → Việt (Google Translate, miễn phí).
    4. Tạo PDF mới: xóa text gốc, chèn text tiếng Việt ở vị trí tương ứng.
    5. Người dùng tải xuống PDF tiếng Việt.

Cài đặt:
    pip install -r requirements.txt

Chạy:
    streamlit run app.py
"""

import os
import sys
import io
import re
import time

# Đảm bảo site-packages được nhận diện
# (Cần thiết khi Python cài ở thư mục tùy chỉnh)
_site_pkg = os.path.join(os.path.dirname(sys.executable), "Lib", "site-packages")
if os.path.isdir(_site_pkg) and _site_pkg not in sys.path:
    sys.path.insert(0, _site_pkg)

import pymupdf as fitz  # PyMuPDF (modern import)
import streamlit as st
from deep_translator import GoogleTranslator


# =====================================================================
# HẰNG SỐ CẤU HÌNH
# =====================================================================

# Hệ số giảm font mặc định (tiếng Việt thường dài hơn tiếng Anh)
DEFAULT_FONT_SCALE = 0.85

# Font size tối thiểu (dưới mức này chữ quá nhỏ, không đọc được)
MIN_FONT_SIZE = 4

# Giới hạn ký tự mỗi lần gọi Google Translate (API miễn phí giới hạn ~5000)
MAX_TRANSLATE_CHARS = 4500

# Delay giữa các request dịch (giây) — tránh bị rate-limit
TRANSLATE_DELAY = 0.15


# =====================================================================
# HÀM TÌM FONT HỖ TRỢ TIẾNG VIỆT
# =====================================================================

def find_vietnamese_font():
    """
    Tìm file font TTF hỗ trợ Unicode/Vietnamese trên hệ thống.

    Ưu tiên: Arial > Tahoma > Calibri > Segoe UI > Times New Roman
    (Windows), DejaVu Sans > Liberation Sans > FreeSans (Linux),
    Arial > Times New Roman (macOS).

    Returns:
        str | None: Đường dẫn đến file font, hoặc None nếu không tìm thấy.
    """
    font_paths = []

    if sys.platform == "win32":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        fonts_dir = os.path.join(windir, "Fonts")
        font_paths = [
            os.path.join(fonts_dir, "arial.ttf"),
            os.path.join(fonts_dir, "tahoma.ttf"),
            os.path.join(fonts_dir, "calibri.ttf"),
            os.path.join(fonts_dir, "segoeui.ttf"),
            os.path.join(fonts_dir, "times.ttf"),
            os.path.join(fonts_dir, "verdana.ttf"),
        ]
    elif sys.platform == "darwin":
        font_paths = [
            "/Library/Fonts/Arial.ttf",
            "/Library/Fonts/Times New Roman.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
    else:  # Linux / WSL
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        ]

    for path in font_paths:
        if os.path.isfile(path):
            return path

    return None


# =====================================================================
# HÀM TIỆN ÍCH
# =====================================================================

def color_int_to_rgb(color_int):
    """
    Chuyển đổi màu dạng integer (0xRRGGBB) sang tuple (r, g, b)
    với giá trị trong khoảng [0.0, 1.0] — định dạng PyMuPDF yêu cầu.

    Args:
        color_int: Màu dạng integer hoặc tuple.

    Returns:
        tuple: (r, g, b) trong khoảng [0, 1].
    """
    if isinstance(color_int, (list, tuple)):
        return tuple(c if c <= 1.0 else c / 255.0 for c in color_int)
    r = ((color_int >> 16) & 0xFF) / 255.0
    g = ((color_int >> 8) & 0xFF) / 255.0
    b = (color_int & 0xFF) / 255.0
    return (r, g, b)


def is_translatable(text):
    """
    Kiểm tra xem đoạn text có cần dịch hay không.

    Bỏ qua: text rỗng, text chỉ có 1 ký tự, text chỉ chứa số/ký hiệu.

    Args:
        text: Chuỗi cần kiểm tra.

    Returns:
        bool: True nếu text cần được dịch.
    """
    text = text.strip()
    if not text or len(text) <= 1:
        return False
    # Bỏ qua nếu chỉ chứa số, khoảng trắng, ký tự đặc biệt
    if re.match(r'^[\d\s\W]+$', text):
        return False
    return True


# =====================================================================
# HÀM DỊCH THUẬT
# =====================================================================

def translate_text(text, translator):
    """
    Dịch một đoạn text từ tiếng Anh sang tiếng Việt.

    - Bỏ qua text không cần dịch (số, ký hiệu, quá ngắn).
    - Tự động chia nhỏ text dài vượt giới hạn API.
    - Trả về text gốc nếu dịch thất bại (fail-safe).

    Args:
        text: Đoạn text tiếng Anh cần dịch.
        translator: Instance của GoogleTranslator.

    Returns:
        str: Text đã dịch (hoặc text gốc nếu lỗi).
    """
    if not is_translatable(text):
        return text

    try:
        # Text ngắn: dịch trực tiếp
        if len(text) <= MAX_TRANSLATE_CHARS:
            result = translator.translate(text)
            return result if result else text

        # Text dài: chia thành các phần nhỏ theo câu
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current_chunk = ""

        for sentence in sentences:
            # Nếu thêm câu mới vượt giới hạn → lưu chunk hiện tại
            if len(current_chunk) + len(sentence) + 1 > MAX_TRANSLATE_CHARS:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = sentence
            else:
                current_chunk = f"{current_chunk} {sentence}".strip()

        if current_chunk:
            chunks.append(current_chunk)

        # Dịch từng chunk
        translated_parts = []
        for chunk in chunks:
            result = translator.translate(chunk)
            translated_parts.append(result if result else chunk)
            time.sleep(TRANSLATE_DELAY)

        return " ".join(translated_parts)

    except Exception as e:
        # Fail-safe: trả về text gốc, không crash
        return text


# =====================================================================
# HÀM TRÍCH XUẤT TEXT TỪ PDF
# =====================================================================

def extract_text_blocks(page):
    """
    Trích xuất tất cả text blocks từ một trang PDF, kèm theo
    thông tin vị trí (bbox), font size, và màu sắc.

    Mỗi block tương ứng với một "đoạn văn" trong PDF.

    Args:
        page: Đối tượng fitz.Page.

    Returns:
        list[dict]: Danh sách blocks, mỗi block gồm:
            - text (str): Nội dung text
            - bbox (list): [x0, y0, x1, y1]
            - font_size (float): Font size trung bình
            - color (int): Mã màu integer
    """
    blocks = []
    text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

    for block in text_dict.get("blocks", []):
        # Chỉ xử lý text blocks (type=0), bỏ qua image blocks (type=1)
        if block.get("type") != 0:
            continue

        full_text = ""
        font_sizes = []
        colors = []

        for line in block.get("lines", []):
            line_text = ""
            for span in line.get("spans", []):
                span_text = span.get("text", "")
                line_text += span_text
                if span_text.strip():
                    font_sizes.append(span.get("size", 11))
                    colors.append(span.get("color", 0))
            full_text += line_text.strip() + " "

        full_text = full_text.strip()

        # Bỏ qua blocks rỗng hoặc không có span nào
        if not full_text or not font_sizes:
            continue

        blocks.append({
            "text": full_text,
            "bbox": block["bbox"],
            "font_size": sum(font_sizes) / len(font_sizes),
            "color": colors[0],
        })

    return blocks


# =====================================================================
# HÀM TÌM FONT SIZE PHÙ HỢP
# =====================================================================

def find_best_font_size(rect, text, font_path, original_size, page_width, page_height):
    """
    Tìm font size lớn nhất mà text vừa với bounding box (rect).

    Thử các hệ số giảm dần (0.85, 0.75, 0.65, ...) cho đến khi
    text không bị tràn (overflow) khỏi rect.

    Sử dụng document tạm để test — không ảnh hưởng PDF gốc.

    Args:
        rect: fitz.Rect — vùng chứa text.
        text: Nội dung text đã dịch.
        font_path: Đường dẫn font file.
        original_size: Font size gốc.
        page_width, page_height: Kích thước trang (để tạo test page).

    Returns:
        float: Font size tối ưu.
    """
    scales = [DEFAULT_FONT_SCALE, 0.75, 0.65, 0.55, 0.45, 0.35]
    temp_doc = fitz.open()

    try:
        for scale in scales:
            size = original_size * scale
            if size < MIN_FONT_SIZE:
                return MIN_FONT_SIZE

            # Tạo trang tạm để test chèn text
            test_page = temp_doc.new_page(width=page_width, height=page_height)
            rc = test_page.insert_textbox(
                rect,
                text,
                fontname="test",
                fontfile=font_path,
                fontsize=size,
            )
            temp_doc.delete_page(-1)  # Xóa trang test

            if rc >= 0:  # rc >= 0 nghĩa là text vừa khung
                return size

        # Fallback: dùng scale nhỏ nhất
        return max(original_size * scales[-1], MIN_FONT_SIZE)

    finally:
        temp_doc.close()


# =====================================================================
# HÀM XỬ LÝ CHÍNH — DỊCH TOÀN BỘ PDF
# =====================================================================

def process_pdf(pdf_bytes, progress_bar, status_text):
    """
    Xử lý dịch toàn bộ file PDF từ tiếng Anh sang tiếng Việt.

    Quy trình:
        1. Mở PDF, tìm font hỗ trợ tiếng Việt.
        2. Trích xuất text blocks từ mỗi trang.
        3. Dịch từng block (hiển thị progress).
        4. Xóa text gốc bằng redaction (tô trắng).
        5. Chèn text tiếng Việt vào vị trí tương ứng.
        6. Lưu ra PDF mới.

    Args:
        pdf_bytes: Bytes của file PDF gốc.
        progress_bar: Streamlit progress bar widget.
        status_text: Streamlit empty widget để hiển thị status.

    Returns:
        bytes: Nội dung file PDF đã dịch.

    Raises:
        ValueError: File rỗng hoặc không trích xuất được text.
        FileNotFoundError: Không tìm thấy font Unicode.
    """
    # --- Mở PDF ---
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)

    if total_pages == 0:
        doc.close()
        raise ValueError("File PDF rỗng (0 trang). Vui lòng chọn file khác.")

    # --- Tìm font ---
    font_path = find_vietnamese_font()
    if font_path is None:
        doc.close()
        raise FileNotFoundError(
            "Không tìm thấy font Unicode hỗ trợ tiếng Việt trên hệ thống.\n"
            "Vui lòng cài đặt một trong các font: Arial, Tahoma, DejaVu Sans, "
            "Liberation Sans."
        )

    status_text.text(f"🔤 Sử dụng font: {os.path.basename(font_path)}")
    time.sleep(0.5)

    # --- Khởi tạo translator ---
    try:
        translator = GoogleTranslator(source='en', target='vi')
        # Test nhanh translator có hoạt động không
        test_result = translator.translate("Hello")
        if not test_result:
            raise ConnectionError("Translator trả về kết quả rỗng.")
    except Exception as e:
        doc.close()
        raise ConnectionError(
            f"Không thể kết nối Google Translate: {e}\n"
            "Vui lòng kiểm tra kết nối Internet."
        )

    # --- Phase 1: Trích xuất text blocks từ tất cả các trang ---
    status_text.text("📖 Đang trích xuất văn bản từ PDF...")
    all_page_blocks = []
    for page_idx in range(total_pages):
        blocks = extract_text_blocks(doc[page_idx])
        all_page_blocks.append(blocks)

    total_blocks = sum(len(blocks) for blocks in all_page_blocks)

    if total_blocks == 0:
        doc.close()
        raise ValueError(
            "Không trích xuất được văn bản nào từ file PDF.\n"
            "File có thể là PDF dạng ảnh scan (image-based). "
            "Ứng dụng chỉ hỗ trợ PDF có text."
        )

    status_text.text(
        f"📊 Tìm thấy {total_blocks} khối văn bản trên {total_pages} trang."
    )
    time.sleep(0.5)

    # --- Phase 2: Dịch + thay thế cho từng trang ---
    processed_blocks = 0

    for page_idx in range(total_pages):
        page = doc[page_idx]
        blocks = all_page_blocks[page_idx]

        # Bỏ qua trang không có text
        if not blocks:
            continue

        status_text.text(
            f"📄 Đang xử lý trang {page_idx + 1}/{total_pages} "
            f"({len(blocks)} khối văn bản)..."
        )

        # ---- Bước 2a: Dịch tất cả blocks của trang ----
        translations = []
        for block in blocks:
            translated = translate_text(block["text"], translator)
            translations.append(translated)

            processed_blocks += 1
            progress_bar.progress(
                min(processed_blocks / total_blocks, 0.99),
                text=f"Đang dịch... {processed_blocks}/{total_blocks} khối"
            )
            time.sleep(TRANSLATE_DELAY)

        # ---- Bước 2b: Xóa text gốc bằng redaction ----
        for block in blocks:
            rect = fitz.Rect(block["bbox"])
            # Tạo annotation redaction với fill trắng
            page.add_redact_annot(rect, fill=(1, 1, 1))

        # Áp dụng redaction — xóa text nhưng giữ nguyên hình ảnh
        try:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        except Exception:
            # Fallback cho PyMuPDF cũ hơn không hỗ trợ tham số images
            page.apply_redactions()

        # ---- Bước 2c: Chèn text tiếng Việt ----
        for block, translated in zip(blocks, translations):
            rect = fitz.Rect(block["bbox"])
            color = color_int_to_rgb(block["color"])

            # Tìm font size phù hợp (tránh tràn bbox)
            best_size = find_best_font_size(
                rect, translated, font_path,
                block["font_size"],
                page.rect.width, page.rect.height,
            )

            # Chèn text vào PDF — fontname="vn" là tên nội bộ, fontfile trỏ đến TTF thật
            page.insert_textbox(
                rect,
                translated,
                fontname="vn",
                fontfile=font_path,
                fontsize=best_size,
                color=color,
                align=fitz.TEXT_ALIGN_LEFT,
            )

    # --- Phase 3: Lưu kết quả ---
    status_text.text("💾 Đang tạo file PDF kết quả...")
    output_buffer = io.BytesIO()
    doc.save(output_buffer, garbage=4, deflate=True)  # Tối ưu kích thước
    doc.close()

    progress_bar.progress(1.0, text="✅ Hoàn tất!")
    return output_buffer.getvalue()


# =====================================================================
# GIAO DIỆN STREAMLIT
# =====================================================================

# --- Cấu hình trang ---
st.set_page_config(
    page_title="TransPDF — Dịch PDF Anh→Việt",
    page_icon="📄",
    layout="centered",
)

# --- Custom CSS ---
st.markdown("""
<style>
    /* Container chính */
    .block-container {
        max-width: 760px;
        padding-top: 2rem;
    }

    /* Header */
    .app-header {
        text-align: center;
        padding: 1.5rem 0 0.5rem 0;
    }
    .app-header h1 {
        font-size: 2.2rem;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.3rem;
    }
    .app-header p {
        color: #888;
        font-size: 1rem;
        margin-top: 0;
    }

    /* Info cards */
    .info-card {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        border-radius: 12px;
        padding: 1rem 1.2rem;
        margin: 0.5rem 0;
    }

    /* Download button styling */
    .stDownloadButton > button {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%) !important;
        color: white !important;
        border: none !important;
        font-weight: 600 !important;
        font-size: 1.05rem !important;
        padding: 0.7rem 1.5rem !important;
        border-radius: 8px !important;
        transition: transform 0.2s, box-shadow 0.2s !important;
    }
    .stDownloadButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 6px 20px rgba(17, 153, 142, 0.35) !important;
    }

    /* Primary button */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        border: none !important;
        font-weight: 600 !important;
        font-size: 1.05rem !important;
        border-radius: 8px !important;
        transition: transform 0.2s, box-shadow 0.2s !important;
    }
    .stButton > button[kind="primary"]:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 6px 20px rgba(102, 126, 234, 0.35) !important;
    }

    /* Uploader styling */
    [data-testid="stFileUploader"] {
        border-radius: 12px;
    }

    /* Footer */
    .app-footer {
        text-align: center;
        color: #aaa;
        font-size: 0.8rem;
        padding: 0.5rem 0;
    }

    /* Metrics */
    [data-testid="stMetric"] {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 0.8rem;
        border: 1px solid #e9ecef;
    }

    /* Steps list */
    .steps-list {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        border-left: 4px solid #667eea;
        margin: 0.5rem 0 1rem 0;
    }
    .steps-list p {
        margin: 0.3rem 0;
        font-size: 0.92rem;
        color: #555;
    }
</style>
""", unsafe_allow_html=True)

# --- Header ---
st.markdown("""
<div class="app-header">
    <h1>📄 TransPDF</h1>
    <p>Dịch tài liệu PDF từ tiếng Anh sang tiếng Việt — giữ nguyên bố cục cơ bản</p>
</div>
""", unsafe_allow_html=True)

# --- Hướng dẫn nhanh ---
with st.expander("ℹ️ Hướng dẫn sử dụng", expanded=False):
    st.markdown("""
    <div class="steps-list">
        <p>📁 <strong>Bước 1:</strong> Tải lên file PDF tiếng Anh (chỉ hỗ trợ PDF có text, không hỗ trợ ảnh scan)</p>
        <p>🚀 <strong>Bước 2:</strong> Nhấn nút "Bắt đầu dịch" và chờ hệ thống xử lý</p>
        <p>⬇️ <strong>Bước 3:</strong> Tải xuống file PDF tiếng Việt đã dịch</p>
    </div>
    """, unsafe_allow_html=True)
    st.info(
        "**Lưu ý:** Ứng dụng sử dụng Google Translate API miễn phí, "
        "nên tốc độ dịch phụ thuộc vào kết nối Internet và độ dài văn bản. "
        "File PDF lớn có thể mất vài phút."
    )

st.divider()

# --- Upload file ---
uploaded_file = st.file_uploader(
    "📁 Chọn file PDF tiếng Anh",
    type=["pdf"],
    help="Hỗ trợ file PDF có text (text-based). Không hỗ trợ PDF dạng ảnh scan.",
)

if uploaded_file is not None:
    # Hiển thị thông tin file đã upload
    file_bytes = uploaded_file.getvalue()
    file_size_mb = len(file_bytes) / (1024 * 1024)

    col1, col2 = st.columns(2)
    with col1:
        st.metric("📄 Tên file", uploaded_file.name)
    with col2:
        st.metric("📦 Kích thước", f"{file_size_mb:.2f} MB")

    # Cảnh báo file lớn
    if file_size_mb > 10:
        st.warning(
            "⚠️ File khá lớn. Quá trình dịch có thể mất nhiều thời gian. "
            "Hãy kiên nhẫn chờ đợi."
        )

    st.divider()

    # --- Nút bắt đầu dịch ---
    if st.button("🚀 Bắt đầu dịch", type="primary", use_container_width=True):

        # Tạo widgets hiển thị tiến trình
        progress_bar = st.progress(0, text="Đang khởi tạo...")
        status_text = st.empty()

        try:
            # Gọi hàm xử lý chính
            result_pdf = process_pdf(file_bytes, progress_bar, status_text)

            # Thành công!
            status_text.success("✅ Dịch hoàn tất! File PDF tiếng Việt đã sẵn sàng.")

            # Tạo tên file output
            base_name = uploaded_file.name
            if base_name.lower().endswith(".pdf"):
                output_name = base_name[:-4] + "_vi.pdf"
            else:
                output_name = base_name + "_vi.pdf"

            # Nút tải xuống
            st.download_button(
                label="⬇️ Tải xuống PDF tiếng Việt",
                data=result_pdf,
                file_name=output_name,
                mime="application/pdf",
                use_container_width=True,
            )

        except ValueError as e:
            st.error(f"❌ **Lỗi dữ liệu:** {e}")
        except FileNotFoundError as e:
            st.error(f"❌ **Lỗi font chữ:** {e}")
        except ConnectionError as e:
            st.error(f"❌ **Lỗi kết nối:** {e}")
        except Exception as e:
            st.error(f"❌ **Lỗi không mong muốn:** {e}")
            st.info(
                "💡 **Gợi ý khắc phục:**\n"
                "- Kiểm tra file PDF có bị hỏng không\n"
                "- Đảm bảo kết nối Internet ổn định\n"
                "- Thử lại với file PDF khác"
            )

else:
    # Placeholder khi chưa upload file
    st.markdown(
        '<p style="text-align:center; color:#bbb; padding:2rem 0; font-size:1.1rem;">'
        '⬆️ Tải lên file PDF để bắt đầu'
        '</p>',
        unsafe_allow_html=True,
    )

# --- Footer ---
st.divider()
st.markdown(
    '<p class="app-footer">'
    'TransPDF &bull; Powered by PyMuPDF + Google Translate (miễn phí) &bull; '
    'Hỗ trợ PDF có text &bull; Giữ bố cục cơ bản'
    '</p>',
    unsafe_allow_html=True,
)
