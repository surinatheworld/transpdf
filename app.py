"""
TransPDF v2.0 — Dịch file PDF từ tiếng Anh sang tiếng Việt (Optimized).

Cải tiến so với v1:
    - Dịch song song (ThreadPoolExecutor) → nhanh gấp 5 lần.
    - Trích xuất ở cấp DÒNG (line) thay vì block → giữ đúng vị trí.
    - Dùng insert_text() tại tọa độ gốc → chữ rõ ràng, không bị co méo.
    - Font size giữ nguyên bản → dễ đọc.

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
from concurrent.futures import ThreadPoolExecutor, as_completed

# =====================================================================
# FIX PATH — Đảm bảo Python tìm được site-packages
# =====================================================================
_site_pkg = os.path.join(os.path.dirname(sys.executable), "Lib", "site-packages")
if os.path.isdir(_site_pkg) and _site_pkg not in sys.path:
    sys.path.insert(0, _site_pkg)

import pymupdf as fitz  # PyMuPDF (modern import, không dùng 'import fitz' đã deprecated)
import streamlit as st
from deep_translator import GoogleTranslator


# =====================================================================
# HẰNG SỐ
# =====================================================================

# Số luồng dịch song song (tăng = nhanh hơn nhưng dễ bị rate-limit)
MAX_WORKERS = 5

# Giới hạn ký tự mỗi lần gọi Google Translate
MAX_CHARS = 4500


# =====================================================================
# TÌM FONT HỖ TRỢ TIẾNG VIỆT
# =====================================================================

def find_vietnamese_font():
    """
    Tìm font TTF hỗ trợ tiếng Việt (Unicode) trên hệ thống.

    Ưu tiên các font có Vietnamese glyph tốt:
    Tahoma > Arial > Segoe UI > Calibri > Times New Roman (Windows)
    DejaVu Sans > Liberation Sans > Noto Sans (Linux)
    """
    candidates = []

    if sys.platform == "win32":
        fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        candidates = [
            os.path.join(fonts_dir, f)
            for f in [
                "tahoma.ttf",    # Tốt nhất cho tiếng Việt trên Windows
                "arial.ttf",
                "segoeui.ttf",
                "calibri.ttf",
                "times.ttf",
                "verdana.ttf",
            ]
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/Library/Fonts/Arial.ttf",
            "/Library/Fonts/Tahoma.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Times New Roman.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
        ]

    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


# =====================================================================
# HÀM TIỆN ÍCH
# =====================================================================

def color_int_to_rgb(color_int):
    """Chuyển integer color (0xRRGGBB) → tuple (r, g, b) trong [0, 1]."""
    if isinstance(color_int, (list, tuple)):
        return tuple(c if c <= 1.0 else c / 255.0 for c in color_int)
    r = ((color_int >> 16) & 0xFF) / 255.0
    g = ((color_int >> 8) & 0xFF) / 255.0
    b = (color_int & 0xFF) / 255.0
    return (r, g, b)


def is_translatable(text):
    """Kiểm tra text có cần dịch không. Bỏ qua số, ký hiệu, text quá ngắn."""
    text = text.strip()
    if not text or len(text) <= 1:
        return False
    if re.match(r'^[\d\s\W]+$', text):
        return False
    return True


# =====================================================================
# TRÍCH XUẤT TEXT Ở CẤP DÒNG (LINE-LEVEL)
# =====================================================================

def extract_lines(page):
    """
    Trích xuất text ở cấp DÒNG (line) thay vì block.

    Mỗi dòng có:
    - text: nội dung
    - bbox: [x0, y0, x1, y1] bounding box
    - origin: (x, y) tọa độ baseline — dùng cho insert_text()
    - font_size: kích thước font gốc
    - color: mã màu

    Ưu điểm so với block-level:
    - Giữ đúng vị trí dọc (y) cho mỗi dòng
    - Font size chính xác hơn
    - Không cần text wrapping → chữ rõ ràng hơn
    """
    lines = []
    text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:  # Chỉ text blocks
            continue

        for line in block.get("lines", []):
            full_text = ""
            font_size = 11
            color = 0
            origin = None

            for span in line.get("spans", []):
                span_text = span.get("text", "")
                full_text += span_text

                # Lấy thông tin từ span đầu tiên có text
                if span_text.strip() and origin is None:
                    font_size = span.get("size", 11)
                    color = span.get("color", 0)
                    origin = span.get("origin", None)

            full_text = full_text.strip()

            if full_text and origin:
                lines.append({
                    "text": full_text,
                    "bbox": line["bbox"],
                    "origin": origin,  # (x, y) baseline
                    "font_size": font_size,
                    "color": color,
                })

    return lines


# =====================================================================
# DỊCH SONG SONG (CONCURRENT TRANSLATION)
# =====================================================================

def translate_concurrent(texts, progress_bar, status_text):
    """
    Dịch danh sách texts song song bằng ThreadPoolExecutor.

    Nhanh gấp ~5x so với dịch tuần tự nhờ chạy MAX_WORKERS luồng cùng lúc.

    Args:
        texts: list[str] — danh sách text cần dịch
        progress_bar: Streamlit progress bar
        status_text: Streamlit status widget

    Returns:
        list[str] — danh sách text đã dịch (giữ nguyên thứ tự)
    """
    results = list(texts)  # Copy — mặc định giữ nguyên text gốc

    # Chỉ dịch những text thực sự cần dịch
    translatable_indices = [i for i, t in enumerate(texts) if is_translatable(t)]

    if not translatable_indices:
        return results

    total = len(translatable_indices)
    completed = 0

    def translate_one(idx):
        """Dịch một đoạn text. Mỗi thread tạo translator riêng để thread-safe."""
        try:
            translator = GoogleTranslator(source='en', target='vi')
            text = texts[idx]

            # Xử lý text dài: chia thành chunks
            if len(text) > MAX_CHARS:
                sentences = re.split(r'(?<=[.!?])\s+', text)
                chunks, current = [], ""
                for s in sentences:
                    if len(current) + len(s) + 1 > MAX_CHARS:
                        if current:
                            chunks.append(current)
                        current = s
                    else:
                        current = f"{current} {s}".strip()
                if current:
                    chunks.append(current)

                translated_parts = [translator.translate(c) or c for c in chunks]
                return idx, " ".join(translated_parts)
            else:
                result = translator.translate(text)
                return idx, result if result else text
        except Exception:
            return idx, texts[idx]  # Fail-safe: giữ text gốc

    status_text.text(f"🌐 Đang dịch song song ({MAX_WORKERS} luồng)...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit tất cả tasks
        futures = {
            executor.submit(translate_one, i): i
            for i in translatable_indices
        }

        # Thu thập kết quả khi hoàn thành
        for future in as_completed(futures):
            idx, translated = future.result()
            results[idx] = translated

            completed += 1
            progress_bar.progress(
                min(completed / total, 0.99),
                text=f"Đang dịch... {completed}/{total} dòng"
            )

    return results


# =====================================================================
# XỬ LÝ CHÍNH — DỊCH PDF
# =====================================================================

def process_pdf(pdf_bytes, progress_bar, status_text):
    """
    Dịch PDF: trích xuất dòng → dịch song song → xóa text gốc → chèn text Việt.

    Quy trình v2.0:
        1. Trích xuất ở cấp DÒNG (line-level) → giữ đúng vị trí
        2. Dịch song song (ThreadPoolExecutor) → nhanh gấp 5x
        3. Xóa text gốc (redaction)
        4. Chèn text Việt bằng insert_text() tại tọa độ gốc → chữ rõ ràng
    """
    # --- Mở PDF ---
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)

    if total_pages == 0:
        doc.close()
        raise ValueError("File PDF rỗng (0 trang).")

    # --- Tìm font ---
    font_path = find_vietnamese_font()
    if font_path is None:
        doc.close()
        raise FileNotFoundError(
            "Không tìm thấy font Unicode hỗ trợ tiếng Việt.\n"
            "Cần cài một trong: Tahoma, Arial, DejaVu Sans, Liberation Sans."
        )

    font_name = os.path.basename(font_path)
    status_text.text(f"🔤 Font: {font_name}")
    time.sleep(0.3)

    # --- Test translator ---
    try:
        test_translator = GoogleTranslator(source='en', target='vi')
        test_result = test_translator.translate("Hello")
        if not test_result:
            raise ConnectionError("Kết quả rỗng.")
    except Exception as e:
        doc.close()
        raise ConnectionError(
            f"Không thể kết nối Google Translate: {e}\n"
            "Kiểm tra kết nối Internet."
        )

    # --- Phase 1: Trích xuất tất cả dòng ---
    status_text.text("📖 Đang trích xuất văn bản...")
    all_page_lines = []
    all_texts = []

    for page_idx in range(total_pages):
        lines = extract_lines(doc[page_idx])
        all_page_lines.append(lines)
        all_texts.extend(line["text"] for line in lines)

    total_lines = len(all_texts)

    if total_lines == 0:
        doc.close()
        raise ValueError(
            "Không trích xuất được văn bản.\n"
            "File có thể là PDF dạng ảnh scan (không hỗ trợ)."
        )

    translatable_count = sum(1 for t in all_texts if is_translatable(t))
    status_text.text(
        f"📊 {total_lines} dòng ({translatable_count} dòng cần dịch) "
        f"trên {total_pages} trang"
    )
    time.sleep(0.3)

    # --- Phase 2: Dịch song song ---
    translated_texts = translate_concurrent(all_texts, progress_bar, status_text)

    # --- Phase 3: Áp dụng vào PDF ---
    status_text.text("📝 Đang tạo PDF tiếng Việt...")
    text_idx = 0

    for page_idx in range(total_pages):
        page = doc[page_idx]
        lines = all_page_lines[page_idx]

        if not lines:
            continue

        # Bước 3a: Xóa text gốc — redaction từng dòng (chính xác hơn block)
        for line_info in lines:
            rect = fitz.Rect(line_info["bbox"])
            page.add_redact_annot(rect, fill=(1, 1, 1))  # Tô trắng

        try:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        except TypeError:
            page.apply_redactions()  # Fallback PyMuPDF cũ

        # Bước 3b: Chèn text tiếng Việt tại ĐÚNG tọa độ gốc
        for line_info in lines:
            translated = translated_texts[text_idx]
            text_idx += 1

            origin = line_info["origin"]   # (x, y) baseline position
            font_size = line_info["font_size"]  # Font size NGUYÊN BẢN
            color = color_int_to_rgb(line_info["color"])

            try:
                page.insert_text(
                    origin,                # Chèn tại đúng vị trí baseline gốc
                    translated,
                    fontname="vn",         # Tên nội bộ cho font nhúng
                    fontfile=font_path,    # File TTF thực tế
                    fontsize=font_size,    # GIỮ NGUYÊN font size gốc
                    color=color,
                )
            except Exception:
                # Fallback: nếu insert_text lỗi, thử insert_textbox
                try:
                    rect = fitz.Rect(line_info["bbox"])
                    page.insert_textbox(
                        rect, translated,
                        fontname="vn", fontfile=font_path,
                        fontsize=font_size * 0.9,
                        color=color,
                    )
                except Exception:
                    pass  # Bỏ qua dòng lỗi

    # --- Phase 4: Lưu PDF ---
    status_text.text("💾 Đang lưu file...")
    output = io.BytesIO()
    doc.save(output, garbage=4, deflate=True)
    doc.close()

    progress_bar.progress(1.0, text="✅ Hoàn tất!")
    return output.getvalue()


# =====================================================================
# GIAO DIỆN STREAMLIT
# =====================================================================

st.set_page_config(
    page_title="TransPDF — Dịch PDF Anh→Việt",
    page_icon="📄",
    layout="centered",
)

# --- CSS ---
st.markdown("""
<style>
    .block-container { max-width: 760px; padding-top: 2rem; }

    .app-header { text-align: center; padding: 1.5rem 0 0.5rem 0; }
    .app-header h1 {
        font-size: 2.2rem;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .app-header p { color: #888; font-size: 1rem; margin-top: 0; }

    .stDownloadButton > button {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%) !important;
        color: white !important; border: none !important;
        font-weight: 600 !important; font-size: 1.05rem !important;
        border-radius: 8px !important;
    }

    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        border: none !important; font-weight: 600 !important;
        font-size: 1.05rem !important; border-radius: 8px !important;
    }

    [data-testid="stMetric"] {
        background: #f8f9fa; border-radius: 10px;
        padding: 0.8rem; border: 1px solid #e9ecef;
    }

    .app-footer { text-align: center; color: #aaa; font-size: 0.8rem; }

    .steps-list {
        background: #f8f9fa; border-radius: 10px;
        padding: 1rem 1.2rem; border-left: 4px solid #667eea;
    }
    .steps-list p { margin: 0.3rem 0; font-size: 0.92rem; color: #555; }
</style>
""", unsafe_allow_html=True)

# --- Header ---
st.markdown("""
<div class="app-header">
    <h1>📄 TransPDF v2.0</h1>
    <p>Dịch tài liệu PDF Anh → Việt — nhanh hơn, chữ rõ hơn</p>
</div>
""", unsafe_allow_html=True)

# --- Hướng dẫn ---
with st.expander("ℹ️ Hướng dẫn sử dụng", expanded=False):
    st.markdown("""
    <div class="steps-list">
        <p>📁 <strong>Bước 1:</strong> Tải lên file PDF tiếng Anh</p>
        <p>🚀 <strong>Bước 2:</strong> Nhấn "Bắt đầu dịch" và chờ</p>
        <p>⬇️ <strong>Bước 3:</strong> Tải xuống PDF tiếng Việt</p>
    </div>
    """, unsafe_allow_html=True)
    st.info(
        "**Cải tiến v2.0:** Dịch song song (5 luồng) nhanh gấp ~5x. "
        "Chữ được chèn tại đúng tọa độ gốc, font size giữ nguyên → dễ đọc hơn."
    )

st.divider()

# --- Upload ---
uploaded_file = st.file_uploader(
    "📁 Chọn file PDF tiếng Anh",
    type=["pdf"],
    help="Hỗ trợ PDF có text. Không hỗ trợ PDF ảnh scan.",
)

if uploaded_file is not None:
    file_bytes = uploaded_file.getvalue()
    file_size_mb = len(file_bytes) / (1024 * 1024)

    col1, col2 = st.columns(2)
    col1.metric("📄 Tên file", uploaded_file.name)
    col2.metric("📦 Kích thước", f"{file_size_mb:.2f} MB")

    if file_size_mb > 10:
        st.warning("⚠️ File lớn — quá trình dịch có thể mất vài phút.")

    st.divider()

    if st.button("🚀 Bắt đầu dịch", type="primary", use_container_width=True):
        progress_bar = st.progress(0, text="Đang khởi tạo...")
        status_text = st.empty()
        start_time = time.time()

        try:
            result_pdf = process_pdf(file_bytes, progress_bar, status_text)

            elapsed = time.time() - start_time
            status_text.success(
                f"✅ Dịch hoàn tất trong {elapsed:.1f} giây!"
            )

            output_name = uploaded_file.name
            if output_name.lower().endswith(".pdf"):
                output_name = output_name[:-4] + "_vi.pdf"
            else:
                output_name += "_vi.pdf"

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
            st.error(f"❌ **Lỗi font:** {e}")
        except ConnectionError as e:
            st.error(f"❌ **Lỗi kết nối:** {e}")
        except Exception as e:
            st.error(f"❌ **Lỗi:** {e}")
            st.info(
                "💡 Gợi ý: Kiểm tra file PDF không bị hỏng, "
                "kết nối Internet ổn định, thử file khác."
            )
else:
    st.markdown(
        '<p style="text-align:center; color:#bbb; padding:2rem 0; '
        'font-size:1.1rem;">⬆️ Tải lên file PDF để bắt đầu</p>',
        unsafe_allow_html=True,
    )

# --- Footer ---
st.divider()
st.markdown(
    '<p class="app-footer">'
    'TransPDF v2.0 &bull; Dịch song song 5 luồng &bull; '
    'PyMuPDF + Google Translate (miễn phí)'
    '</p>',
    unsafe_allow_html=True,
)
