@echo off
rem Builds WWHD-PS4-Maker.exe with the C# compiler that comes with Windows (.NET Framework 4), next to this folder.
rem   maker\build-exe.cmd
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
"%CSC%" /nologo /target:winexe /optimize+ /out:"%~dp0..\WWHD-PS4-Maker.exe" /win32icon:"%~dp0wwhd-ps4-maker.ico" ^
    /r:System.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll "%~dp0WWHD-PS4-Maker.cs"
