@echo off
chcp 936 >nul
title 交付包 · 改路径
cd /d "%~dp0"
echo ==================================================
echo    助手交付包 · 路径修改工具
echo ==================================================
echo.
echo  这个包里的脚本原本写死了固定的安装目录。
echo  如果你的盘符或目录不同，需要先跑这个工具改掉。
echo.
echo  用法提示：
echo    直接回车 = 不改
echo    输入新路径，例如：  D:\本地ai
echo.
echo  注意：包里三种编码混用（.bat 是 GBK、.ps1 带 BOM），
echo        必须用本工具改，手工批量替换会把文件写坏。
echo.
where python >nul 2>&1
if errorlevel 1 (
    echo  [错误] 没找到 python，请先安装 Python 3.8+
    echo.
    pause
    exit /b 1
)
python "%~dp0setup_paths.py"
echo.
pause
