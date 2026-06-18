@echo off
rem Build all state traffic datasets directly into the TIA repo on G:.
rem Requires Python 3.10+ on PATH. Stdlib only - no pip installs needed.
set "TIA_REPO_ROOT=G:\Shared drives\Crompton Apps\Crompton Labs\APPS\Cromton-Traffic-Impact-Asssessment"
python "%~dp0build_all_states.py" %*
pause
