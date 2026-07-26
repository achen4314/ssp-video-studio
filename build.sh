#!/bin/bash
# Render build script — installs system dependencies + pip packages
set -e

echo "=== SSP Video Studio Build ==="
echo "Installing system dependencies..."

# ffmpeg for video processing
apt-get update -qq
apt-get install -y -qq ffmpeg

# Minimal LaTeX for Manim (only if manim needs it)
# apt-get install -y -qq texlive-latex-base texlive-fonts-recommended

echo "System deps installed."
echo "Installing Python packages..."

pip install --upgrade pip
pip install -r requirements.txt

echo "=== Build complete ==="
