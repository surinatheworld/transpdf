@echo off
chcp 65001 >nul 2>&1
title Build TransPDF EXE

echo.
echo ======================================================
echo    Build TransPDF.exe
echo ======================================================
echo.

:: Tim Python
where python >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON=python
) else (
    where py >nul 2>&1
    if %errorlevel% equ 0 (
        set PYTHON=py
    ) else (
        echo [LOI] Khong tim thay Python!
        pause
        exit /b 1
    )
)

echo [1/3] Cai dat PyInstaller...
%PYTHON% -m pip install pyinstaller -q

echo [2/3] Dang build EXE (mat 1-2 phut)...
%PYTHON% -m PyInstaller --onefile --name TransPDF --console launcher.py

echo [3/3] Don dep...
rmdir /s /q build 2>nul
del /f TransPDF.spec 2>nul

echo.
echo ======================================================
echo    XONG! File EXE tai: dist\TransPDF.exe
echo ======================================================
echo.
echo Huong dan su dung:
echo   1. Copy TOAN BO thu muc nay (hoac copy cac file sau):
echo      - dist\TransPDF.exe
echo      - app.py
echo      - requirements.txt
echo   2. Dat chung vao 1 thu muc
echo   3. Double-click TransPDF.exe de chay
echo.
echo Luu y: May tinh can cai Python 3.8+ va co ket noi Internet.
echo.
pause
