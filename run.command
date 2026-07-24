#!/bin/bash
# WisprTool launcher for macOS
# Make this file executable: chmod +x run.command

cd "$(dirname "$0")"

# Check for Python
if ! command -v python3 &>/dev/null; then
    osascript -e 'display alert "Python 3 not found" message "Please install Python 3 from python.org or via Homebrew:\n  brew install python3"'
    exit 1
fi

# Check for dependencies
python3 -c "import faster_whisper" 2>/dev/null || {
    echo "Installing dependencies..."
    pip3 install -r requirements.txt
}

# Point Python's SSL at certifi's CA bundle. python.org Python ships no
# system CA certificates, which makes the Gemini/OpenAI/Claude HTTPS calls
# fail with CERTIFICATE_VERIFY_FAILED. This fixes AI rewriting.
export SSL_CERT_FILE="$(python3 -c 'import certifi; print(certifi.where())' 2>/dev/null)"

python3 main.py
