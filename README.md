# 📄 TransPDF — Dịch PDF Anh → Việt

Ứng dụng web dịch file PDF từ tiếng Anh sang tiếng Việt, giữ nguyên bố cục cơ bản của tài liệu gốc.

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Streamlit](https://img.shields.io/badge/Streamlit-1.28+-red.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## ✨ Tính năng

- 📁 Upload file PDF tiếng Anh
- 🔍 Trích xuất văn bản + tọa độ từ PDF (PyMuPDF)
- 🌐 Dịch tự động Anh → Việt (Google Translate, miễn phí)
- 📄 Tạo PDF mới với text tiếng Việt, giữ nguyên bố cục cơ bản
- 📊 Thanh tiến trình (progress bar) hiển thị trạng thái dịch
- 🔤 Nhúng font Unicode hỗ trợ tiếng Việt (Arial, Tahoma, DejaVu Sans...)
- ⬇️ Tải xuống file PDF tiếng Việt đã dịch
- ⚠️ Xử lý ngoại lệ: file rỗng, PDF scan, lỗi API, thiếu font...

## 🚀 Cài đặt & Chạy

### 1. Clone repo

```bash
git clone https://github.com/surinatheworld/transpdf.git
cd transpdf
```

### 2. Cài đặt dependencies

```bash
pip install -r requirements.txt
```

### 3. Chạy ứng dụng

```bash
streamlit run app.py
```

Ứng dụng sẽ mở tại `http://localhost:8501`.

## 📋 Yêu cầu hệ thống

- **Python** 3.8+
- **Kết nối Internet** (để sử dụng Google Translate API miễn phí)
- **Font Unicode** trên hệ thống (Arial, Tahoma, DejaVu Sans, v.v.)

## 🛠️ Thư viện sử dụng

| Thư viện | Mục đích |
|---|---|
| `streamlit` | Giao diện web |
| `PyMuPDF` | Đọc/ghi PDF, trích xuất text + tọa độ |
| `deep-translator` | Dịch thuật qua Google Translate (miễn phí) |

## 📖 Luồng hoạt động

```
Upload PDF (EN) → Trích xuất text blocks + tọa độ
                        ↓
              Dịch từng block (EN → VI)
                        ↓
              Xóa text gốc (redaction)
                        ↓
              Chèn text tiếng Việt vào vị trí cũ
                        ↓
              Tải xuống PDF (VI)
```

## ⚠️ Lưu ý

- Chỉ hỗ trợ **PDF có text** (text-based). Không hỗ trợ PDF dạng ảnh scan.
- Sử dụng Google Translate API **miễn phí**, nên có thể bị rate-limit nếu dịch quá nhiều.
- Bố cục được giữ ở mức **cơ bản** (vị trí block, font size). Các yếu tố phức tạp (bảng, cột, header/footer) có thể không hoàn hảo.
- Font size của text dịch được tự động giảm để vừa với bounding box gốc (tiếng Việt thường dài hơn tiếng Anh).

## 📄 License

MIT License
