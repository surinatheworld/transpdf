"""
TransPDF v3.0 — Dịch PDF Anh → Việt (Maximum Speed).

Tối ưu tốc độ:
    v1: 1 block  → 1 API call (tuần tự)       → ~3 phút / 100 blocks
    v2: 1 dòng   → 1 API call (5 luồng)       → ~30 giây / 100 dòng
    v3: 20 dòng  → 1 API call (10 luồng)      → ~3–5 giây / 200 dòng

Cách hoạt động:
    - Gộp 20 dòng thành 1 chuỗi (nối bằng \\n) → 1 lần gọi API
    - 10 luồng song song xử lý nhiều batch cùng lúc
    - Nếu batch lỗi → tự chia nhỏ và thử lại (recursive fallback)
    - Kết quả: giảm 90–95% số lần gọi API

Chạy:
    pip install -r requirements.txt
    streamlit run app.py
"""

import os
import sys
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# =====================================================================
# FIX PATH
# =====================================================================
_site_pkg = os.path.join(os.path.dirname(sys.executable), "Lib", "site-packages")
if os.path.isdir(_site_pkg) and _site_pkg not in sys.path:
    sys.path.insert(0, _site_pkg)

import pymupdf as fitz
import streamlit as st
from deep_translator import GoogleTranslator


# =====================================================================
# HẰNG SỐ TỐI ƯU
# =====================================================================

BATCH_SIZE = 20       # Số dòng gộp trong 1 API call (↑ = ít call hơn = nhanh hơn)
MAX_WORKERS = 10      # Số luồng dịch song song
MAX_CHARS = 4500      # Giới hạn ký tự Google Translate
FONT_INTERNAL = "vn"  # Tên nội bộ font nhúng vào PDF


# =====================================================================
# TÌM FONT
# =====================================================================

def find_vietnamese_font():
    """Tìm font TTF hỗ trợ tiếng Việt trên hệ thống."""
    candidates = []
    if sys.platform == "win32":
        d = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        candidates = [os.path.join(d, f) for f in
                      ["tahoma.ttf", "arial.ttf", "segoeui.ttf",
                       "calibri.ttf", "times.ttf", "verdana.ttf"]]
    elif sys.platform == "darwin":
        candidates = ["/Library/Fonts/Arial.ttf",
                      "/Library/Fonts/Tahoma.ttf",
                      "/System/Library/Fonts/Supplemental/Arial.ttf"]
    else:
        candidates = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                      "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                      "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


# =====================================================================
# TIỆN ÍCH
# =====================================================================

def color_to_rgb(c):
    """Integer color → (r, g, b) in [0,1]."""
    if isinstance(c, (list, tuple)):
        return tuple(x if x <= 1.0 else x / 255.0 for x in c)
    return (((c >> 16) & 0xFF) / 255.0,
            ((c >> 8) & 0xFF) / 255.0,
            (c & 0xFF) / 255.0)


def is_translatable(text):
    """Text có cần dịch không? Bỏ qua số, ký hiệu, quá ngắn."""
    t = text.strip()
    return bool(t) and len(t) > 1 and not re.match(r'^[\d\s\W]+$', t)


# =====================================================================
# TRÍCH XUẤT DÒNG (LINE-LEVEL)
# =====================================================================

def extract_lines(page):
    """Trích xuất text ở cấp dòng với tọa độ baseline."""
    lines = []
    for block in page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text, size, color, origin = "", 11, 0, None
            for span in line.get("spans", []):
                st_text = span.get("text", "")
                text += st_text
                if st_text.strip() and origin is None:
                    size = span.get("size", 11)
                    color = span.get("color", 0)
                    origin = span.get("origin")
            text = text.strip()
            if text and origin:
                lines.append({"text": text, "bbox": line["bbox"],
                              "origin": origin, "font_size": size, "color": color})
    return lines


# =====================================================================
# DỊCH BATCH — CỐT LÕI TỐI ƯU TỐC ĐỘ
# =====================================================================

def _translate_batch_recursive(texts, translator):
    """
    Dịch một batch bằng 1 API call duy nhất.

    Chiến lược:
        1. Nối tất cả text bằng \\n → gửi 1 lần
        2. Tách kết quả bằng \\n → map ngược lại
        3. Nếu số dòng không khớp → chia đôi batch, thử lại (recursive)
        4. Base case: 1 text → dịch đơn lẻ

    Hiệu quả: 20 dòng → 1 API call thay vì 20 calls.
    """
    if not texts:
        return []
    if len(texts) == 1:
        try:
            r = translator.translate(texts[0])
            return [r if r else texts[0]]
        except Exception:
            return texts

    combined = "\n".join(texts)

    # Nếu vượt giới hạn ký tự → chia đôi
    if len(combined) > MAX_CHARS:
        mid = len(texts) // 2
        return (_translate_batch_recursive(texts[:mid], translator) +
                _translate_batch_recursive(texts[mid:], translator))

    try:
        result = translator.translate(combined)
        parts = result.split("\n")

        # Số dòng khớp → thành công!
        if len(parts) == len(texts):
            return [p.strip() for p in parts]

        # Không khớp → chia đôi và thử lại
        mid = len(texts) // 2
        return (_translate_batch_recursive(texts[:mid], translator) +
                _translate_batch_recursive(texts[mid:], translator))

    except Exception:
        # Lỗi network → chia nhỏ hơn nữa
        if len(texts) > 2:
            mid = len(texts) // 2
            return (_translate_batch_recursive(texts[:mid], translator) +
                    _translate_batch_recursive(texts[mid:], translator))
        return texts  # Giữ nguyên gốc


def translate_all_fast(texts, progress_bar, status_text):
    """
    Dịch TOÀN BỘ danh sách texts với tốc độ tối đa.

    Pipeline:
        1. Lọc text cần dịch (bỏ số, ký hiệu)
        2. Gộp thành batches (mỗi batch ~20 dòng)
        3. Gửi batches song song (10 luồng)
        4. Mỗi batch = 1 API call (thay vì 20)

    200 dòng → 10 batches × 10 luồng = ~1–2 API rounds = 1–3 giây.
    """
    results = list(texts)

    # Lọc: chỉ dịch text thực sự cần dịch
    translatable = [(i, texts[i]) for i in range(len(texts)) if is_translatable(texts[i])]

    if not translatable:
        return results

    # Tạo batches
    batches = []
    for start in range(0, len(translatable), BATCH_SIZE):
        batches.append(translatable[start:start + BATCH_SIZE])

    total_batches = len(batches)
    completed = [0]  # Dùng list để mutate trong closure

    status_text.text(
        f"🌐 Dịch {len(translatable)} dòng "
        f"({total_batches} batch × {MAX_WORKERS} luồng)..."
    )

    def process_one_batch(batch):
        """Xử lý 1 batch: gộp texts → 1 API call → tách kết quả."""
        translator = GoogleTranslator(source='en', target='vi')
        indices = [i for i, _ in batch]
        batch_texts = [t for _, t in batch]
        translated = _translate_batch_recursive(batch_texts, translator)
        return list(zip(indices, translated))

    # Chạy song song
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_one_batch, b): b for b in batches}

        for future in as_completed(futures):
            try:
                for idx, translated in future.result():
                    results[idx] = translated
            except Exception:
                pass  # Giữ text gốc nếu batch lỗi hoàn toàn

            completed[0] += 1
            progress_bar.progress(
                min(completed[0] / total_batches, 0.99),
                text=f"Đang dịch... {completed[0]}/{total_batches} batch"
            )

    return results


# =====================================================================
# XỬ LÝ PDF
# =====================================================================

def process_pdf(pdf_bytes, progress_bar, status_text):
    """
    Pipeline chính: Extract → Translate (batch+parallel) → Redact → Insert.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)

    if total_pages == 0:
        doc.close()
        raise ValueError("File PDF rỗng (0 trang).")

    font_path = find_vietnamese_font()
    if font_path is None:
        doc.close()
        raise FileNotFoundError("Không tìm thấy font Unicode (Tahoma/Arial/DejaVu Sans).")

    # Test translator
    try:
        GoogleTranslator(source='en', target='vi').translate("test")
    except Exception as e:
        doc.close()
        raise ConnectionError(f"Lỗi Google Translate: {e}")

    # === Phase 1: Extract (nhanh, ~10ms/trang) ===
    status_text.text("📖 Trích xuất văn bản...")
    all_page_lines = []
    all_texts = []
    for i in range(total_pages):
        lines = extract_lines(doc[i])
        all_page_lines.append(lines)
        all_texts.extend(line["text"] for line in lines)

    if not all_texts:
        doc.close()
        raise ValueError("Không tìm thấy text. File có thể là PDF ảnh scan.")

    n_translatable = sum(1 for t in all_texts if is_translatable(t))
    status_text.text(f"📊 {len(all_texts)} dòng, {n_translatable} cần dịch, {total_pages} trang")

    # === Phase 2: Translate (batch + parallel — CỰC NHANH) ===
    translated = translate_all_fast(all_texts, progress_bar, status_text)

    # === Phase 3: Apply to PDF ===
    status_text.text("📝 Ghi PDF tiếng Việt...")
    idx = 0
    for page_idx in range(total_pages):
        page = doc[page_idx]
        lines = all_page_lines[page_idx]
        if not lines:
            continue

        # Redact (xóa text gốc)
        for ln in lines:
            page.add_redact_annot(fitz.Rect(ln["bbox"]), fill=(1, 1, 1))
        try:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        except TypeError:
            page.apply_redactions()

        # Insert text tiếng Việt tại tọa độ gốc
        for ln in lines:
            try:
                page.insert_text(
                    ln["origin"], translated[idx],
                    fontname=FONT_INTERNAL, fontfile=font_path,
                    fontsize=ln["font_size"], color=color_to_rgb(ln["color"]),
                )
            except Exception:
                try:
                    page.insert_textbox(
                        fitz.Rect(ln["bbox"]), translated[idx],
                        fontname=FONT_INTERNAL, fontfile=font_path,
                        fontsize=ln["font_size"] * 0.9,
                        color=color_to_rgb(ln["color"]),
                    )
                except Exception:
                    pass
            idx += 1

    # === Phase 4: Save ===
    out = io.BytesIO()
    doc.save(out, garbage=4, deflate=True)
    doc.close()
    progress_bar.progress(1.0, text="✅ Xong!")
    return out.getvalue()


# =====================================================================
# STREAMLIT UI
# =====================================================================

st.set_page_config(page_title="TransPDF v3", page_icon="📄", layout="centered")

st.markdown("""
<style>
    .block-container { max-width: 760px; padding-top: 2rem; }
    .app-header { text-align: center; padding: 1rem 0 0.5rem 0; }
    .app-header h1 {
        font-size: 2.2rem;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }
    .app-header p { color: #888; font-size: 1rem; margin-top: 0; }
    .stDownloadButton > button {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%) !important;
        color: white !important; border: none !important;
        font-weight: 600 !important; border-radius: 8px !important;
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        border: none !important; font-weight: 600 !important; border-radius: 8px !important;
    }
    [data-testid="stMetric"] {
        background: #f8f9fa; border-radius: 10px;
        padding: 0.8rem; border: 1px solid #e9ecef;
    }
    .speed-badge {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        color: white; padding: 4px 12px; border-radius: 20px;
        font-size: 0.8rem; font-weight: 600; display: inline-block;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="app-header">
    <h1>📄 TransPDF</h1>
    <p>Dịch PDF Anh → Việt &nbsp;
    <span class="speed-badge">⚡ v3.0 — Batch + Parallel</span></p>
</div>
""", unsafe_allow_html=True)

with st.expander("⚡ Tối ưu tốc độ v3.0", expanded=False):
    st.markdown("""
    | Phiên bản | Cách dịch | 200 dòng |
    |---|---|---|
    | v1 | 1 block → 1 API call (tuần tự) | ~3 phút |
    | v2 | 1 dòng → 1 API call (5 luồng) | ~30 giây |
    | **v3** | **20 dòng → 1 API call (10 luồng)** | **~3–5 giây** |
    """)

st.divider()

uploaded = st.file_uploader("📁 Chọn file PDF tiếng Anh", type=["pdf"],
                            help="PDF có text. Không hỗ trợ ảnh scan.")

if uploaded:
    data = uploaded.getvalue()
    mb = len(data) / (1024 * 1024)
    c1, c2 = st.columns(2)
    c1.metric("📄 File", uploaded.name)
    c2.metric("📦 Size", f"{mb:.2f} MB")
    st.divider()

    if st.button("🚀 Dịch ngay", type="primary", use_container_width=True):
        bar = st.progress(0, text="Khởi tạo...")
        status = st.empty()
        t0 = time.time()

        try:
            pdf_out = process_pdf(data, bar, status)
            elapsed = time.time() - t0
            status.success(f"✅ Hoàn tất trong **{elapsed:.1f}s**!")

            name = uploaded.name
            out_name = (name[:-4] + "_vi.pdf") if name.lower().endswith(".pdf") else name + "_vi.pdf"

            st.download_button("⬇️ Tải PDF tiếng Việt", data=pdf_out,
                               file_name=out_name, mime="application/pdf",
                               use_container_width=True)
        except ValueError as e:
            st.error(f"❌ {e}")
        except FileNotFoundError as e:
            st.error(f"❌ {e}")
        except ConnectionError as e:
            st.error(f"❌ {e}")
        except Exception as e:
            st.error(f"❌ {e}")
            st.info("💡 Kiểm tra file PDF + kết nối Internet.")
else:
    st.markdown('<p style="text-align:center;color:#bbb;padding:2rem 0">'
                '⬆️ Tải PDF để bắt đầu</p>', unsafe_allow_html=True)

st.divider()
st.caption("TransPDF v3.0 • Batch (20 dòng/call) + Parallel (10 luồng) • Google Translate miễn phí")
