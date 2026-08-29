@echo off
setlocal
set "JARVIS_ROOT=%~dp0.."
set "JARVIS_PYTHONW=%JARVIS_ROOT%\.venv\Scripts\pythonw.exe"

if not exist "%JARVIS_PYTHONW%" (
  echo JARVIS virtual environment was not found.
  echo Expected: %JARVIS_PYTHONW%
  echo Run the installation steps in README.md first.
  pause
  exit /b 1
)

start "JARVIS" "%JARVIS_PYTHONW%" -m jarvis_agent.gui %*

