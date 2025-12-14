@echo off
echo 🚀 NFC Server - Deploy Script
echo =============================

REM Activează mediul virtual
echo 🔧 Activating virtual environment...
call venv\Scripts\activate

REM Instalează dependențele (doar dacă e nevoie)
if exist requirements.txt (
    echo 📦 Installing dependencies...
    pip install -r requirements.txt
)

REM Creează .gitignore dacă nu există
if not exist .gitignore (
    echo 📄 Creating .gitignore...
    echo __pycache__/ > .gitignore
    echo *.pyc >> .gitignore
    echo venv/ >> .gitignore
    echo .env >> .gitignore
    echo *.log >> .gitignore
)

REM Exclude .env din Git (dacă a fost comis din greșeală)
if exist .env (
    git rm --cached .env 2>nul
    echo 🔒 .env removed from Git tracking (kept locally)
)

REM Adaugă fișierele importante
echo 📤 Adding files to Git...
git add server.py requirements.txt .gitignore

REM Commit
echo 💾 Committing changes...
git commit -m "feat: NFC server final - Pydantic v2, no demo, production ready" 2>nul

REM Push pe GitHub
echo 🌐 Pushing to GitHub...
git push origin main

REM Așteaptă ca utilizatorul să vadă rezultatul
echo.
echo ✅ Deploy process finished!
pause