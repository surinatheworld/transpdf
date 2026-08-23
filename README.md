# 📄 TransPDF — Dịch PDF Anh → Việt

Ứng dụng dịch file PDF từ tiếng Anh sang tiếng Việt, giữ nguyên bố cục cơ bản.

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Streamlit](https://img.shields.io/badge/Streamlit-1.28+-red.svg)

## ✨ Tính năng

- ⚡ **Dịch cực nhanh** — batch 20 dòng/API call + 10 luồng song song
- 📄 Giữ nguyên bố cục cơ bản (vị trí, font size, màu sắc)
- 🔤 Nhúng font Unicode hỗ trợ tiếng Việt
- 📊 Thanh tiến trình hiển thị trạng thái
- ⚠️ Xử lý lỗi: file rỗng, PDF scan, API lỗi, thiếu font

## 🚀 Cách chạy

### Cách 1: Double-click (đơn giản nhất)

```
1. Cài Python 3.8+ (https://python.org) — chọn "Add to PATH"
2. Double-click file TransPDF.bat
3. Chờ cài thư viện (lần đầu) → trình duyệt tự mở
```

### Cách 2: Dùng file EXE

```
1. Cài Python 3.8+
2. Double-click build_exe.bat → tạo file dist/TransPDF.exe
3. Copy TransPDF.exe + app.py + requirements.txt vào 1 thư mục
4. Double-click TransPDF.exe để chạy
```

### Cách 3: Command line

```bash
git clone https://github.com/surinatheworld/transpdf.git
cd transpdf
pip install -r requirements.txt
streamlit run app.py
```

## 📁 Cấu trúc file

| File | Mô tả |
|---|---|
| `app.py` | Source code chính (Streamlit app) |
| `requirements.txt` | Thư viện cần cài |
| `TransPDF.bat` | 🖱️ Double-click để chạy (Windows) |
| `launcher.py` | Source code launcher (build thành EXE) |
| `build_exe.bat` | 🔨 Script build file EXE |

## ⚡ Tốc độ

| Phiên bản | Cách dịch | 200 dòng |
|---|---|---|
| v1 | 1 block → 1 API call (tuần tự) | ~3 phút |
| v2 | 1 dòng → 1 API call (5 luồng) | ~30 giây |
| **v3** | **20 dòng → 1 API call (10 luồng)** | **~3–5 giây** |

## 🛠️ Thư viện

| Thư viện | Mục đích |
|---|---|
| `streamlit` | Giao diện web |
| `PyMuPDF` | Đọc/ghi PDF |
| `deep-translator` | Google Translate (miễn phí) |

## ⚠️ Lưu ý

- Chỉ hỗ trợ PDF có text (không hỗ trợ ảnh scan)
- Cần kết nối Internet (Google Translate API miễn phí)
- Cần cài Python 3.8+ trên máy

## 📄 License

MIT License
