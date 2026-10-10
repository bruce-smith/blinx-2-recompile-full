@echo off
rem Build blipks-unpack / blipks-pack with MSVC (VS 2022, x64)
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
cd /d E:\Blinx2project\assets\tools\blipks || exit /b 1
if not exist bin mkdir bin
cl /nologo /std:c++17 /O2 /EHsc /W3 /Fobin\ /Febin\blipks-unpack.exe blipks-unpack.cpp unlzss.cpp || exit /b 1
cl /nologo /std:c++17 /O2 /EHsc /W3 /Fobin\ /Febin\blipks-pack.exe blipks-pack.cpp lzss.cpp || exit /b 1
