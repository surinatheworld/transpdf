"""
TransPDF Launcher — Khởi động ứng dụng dịch PDF.

Khi chạy (hoặc khi build thành EXE):
    1. Tự động cài đặt thư viện cần thiết (nếu chưa có)
    2. Khởi động Streamlit server
    3. Mở trình duyệt tại http://localhost:8501

Build EXE:
    pip install pyinstaller
    pyinstaller --onefile --name TransPDF --icon=icon.ico --console launcher.py
"""

import sys
import os
import subprocess
import webbrowser
import threading
import time


def get_app_dir():
    """Lấy thư mục chứa app.py (hỗ trợ cả script lẫn EXE đã build)."""
    if getattr(sys, 'frozen', False):
        # Đang chạy từ EXE (PyInstaller)
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_python():
    """Tìm Python executable."""
    if getattr(sys, 'frozen', False):
        # Chạy từ EXE → tìm Python trên hệ thống
        for cmd in ["python", "py", "python3"]:
            try:
                r = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True, text=True, timeout=5
                )
                if r.returncode == 0:
                    return cmd
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        return None
    else:
        return sys.executable


def install_deps(python, app_dir):
    """Cài đặt thư viện từ requirements.txt nếu chưa có."""
    req_file = os.path.join(app_dir, "requirements.txt")
    if not os.path.exists(req_file):
        print("[CẢNH BÁO] Không tìm thấy requirements.txt")
        return True

    # Kiểm tra xem đã cài đủ chưa
    check_imports = (
        "import pymupdf; "
        "from deep_translator import GoogleTranslator; "
        "import streamlit; "
        "print('OK')"
    )
    try:
        r = subprocess.run(
            [python, "-c", check_imports],
            capture_output=True, text=True, timeout=15
        )
        if "OK" in r.stdout:
            print("[✓] Thư viện đã được cài đặt.")
            return True
    except Exception:
        pass

    # Chưa cài → cài đặt
    print("[...] Đang cài đặt thư viện (lần đầu, chỉ cần 1 lần)...")
    try:
        r = subprocess.run(
            [python, "-m", "pip", "install", "-r", req_file, "-q"],
            cwd=app_dir, timeout=300
        )
        if r.returncode == 0:
            print("[✓] Cài đặt thành công!")
            return True
        else:
            print("[✗] Lỗi cài đặt. Thử chạy thủ công:")
            print(f"    {python} -m pip install -r {req_file}")
            return False
    except subprocess.TimeoutExpired:
        print("[✗] Cài đặt quá lâu (timeout). Kiểm tra mạng Internet.")
        return False


def open_browser_delayed():
    """Mở trình duyệt sau 3 giây (chờ server khởi động)."""
    time.sleep(3)
    webbrowser.open("http://localhost:8501")


def main():
    app_dir = get_app_dir()
    app_py = os.path.join(app_dir, "app.py")

    print()
    print("=" * 54)
    print("   📄 TransPDF — Dịch PDF tiếng Anh → tiếng Việt")
    print("=" * 54)
    print()

    # Kiểm tra app.py
    if not os.path.exists(app_py):
        print(f"[LỖI] Không tìm thấy app.py tại:")
        print(f"       {app_dir}")
        print()
        print("Hãy đặt file TransPDF.exe cùng thư mục với app.py")
        input("\nNhấn Enter để thoát...")
        return

    # Tìm Python
    python = get_python()
    if python is None:
        print("[LỖI] Không tìm thấy Python!")
        print()
        print("Tải Python tại: https://www.python.org/downloads/")
        print("Khi cài, nhớ chọn 'Add Python to PATH'.")
        input("\nNhấn Enter để thoát...")
        return

    print(f"[✓] Python: {python}")
    print(f"[✓] App:    {app_py}")
    print()

    # Cài thư viện
    if not install_deps(python, app_dir):
        input("\nNhấn Enter để thoát...")
        return

    print()
    print("🚀 Đang khởi động TransPDF...")
    print("🌐 Trình duyệt sẽ mở tại: http://localhost:8501")
    print()
    print("─" * 54)
    print("   Nhấn Ctrl+C để dừng server")
    print("─" * 54)
    print()

    # Mở browser sau 3 giây
    threading.Thread(target=open_browser_delayed, daemon=True).start()

    # Chạy Streamlit
    try:
        subprocess.run(
            [python, "-m", "streamlit", "run", app_py,
             "--server.headless", "true",
             "--browser.gatherUsageStats", "false"],
            cwd=app_dir
        )
    except KeyboardInterrupt:
        print("\n\n[✓] Đã dừng TransPDF. Tạm biệt!")
    except Exception as e:
        print(f"\n[LỖI] {e}")
        input("\nNhấn Enter để thoát...")


if __name__ == "__main__":
    main()
