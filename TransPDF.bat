@echo off
chcp 65001 >nul 2>&1
title TransPDF — Dich PDF Anh sang Viet

echo.
echo ======================================================
echo    TransPDF — Dich PDF tieng Anh sang tieng Viet
echo ======================================================
echo.

:: === Tim Python ===
where python >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON=python
    goto :found
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON=py
    goto :found
)

echo [LOI] Khong tim thay Python!
echo.
echo Tai Python tai: https://www.python.org/downloads/
echo Khi cai, nho chon "Add Python to PATH".
echo.
pause
exit /b 1

:found
echo [OK] Python: %PYTHON%

:: === Cai thu vien (neu chua co) ===
%PYTHON% -c "import pymupdf; from deep_translator import GoogleTranslator; import streamlit" >nul 2>&1
if %errorlevel% neq 0 (
    echo [...] Dang cai dat thu vien (lan dau, chi can 1 lan)...
    %PYTHON% -m pip install -r requirements.txt -q
    if %errorlevel% neq 0 (
        echo [LOI] Cai dat that bai. Kiem tra ket noi mang.
        pause
        exit /b 1
    )
    echo [OK] Cai dat thanh cong!
)

echo.
echo Dang khoi dong TransPDF...
echo Trinh duyet se tu mo tai: http://localhost:8501
echo Nhan Ctrl+C de dung.
echo.

:: === Chay Streamlit ===
start "" http://localhost:8501
timeout /t 2 /nobreak >nul
%PYTHON% -m streamlit run app.py --server.headless true --browser.gatherUsageStats false

pause
