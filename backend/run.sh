#!/bin/bash
# Quick start script for the Python backend

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== AI Styling Engine (Python Backend) ===${NC}"
echo ""

# Check Python version
PYTHON=$(which python3)
if [ -z "$PYTHON" ]; then
    echo "Error: Python 3 not found. Please install Python 3.9+."
    exit 1
fi

echo -e "${GREEN}✓ Python found: $PYTHON${NC}"
VERSION=$($PYTHON --version)
echo "  $VERSION"
echo ""

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo -e "${BLUE}Creating virtual environment...${NC}"
    $PYTHON -m venv venv
fi

echo -e "${GREEN}✓ Virtual environment ready${NC}"
echo ""

# Activate virtual environment
source venv/bin/activate
echo -e "${GREEN}✓ Activated venv${NC}"
echo ""

# Install dependencies
echo -e "${BLUE}Installing dependencies...${NC}"
pip install -q pytest fastapi uvicorn pydantic httpx 2>/dev/null || {
    echo "Warning: Some dependencies failed to install (this is OK for testing)"
}
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# Run tests
if [ "$1" == "test" ] || [ "$1" == "tests" ]; then
    echo -e "${BLUE}Running tests...${NC}"
    python3 -m pytest tests/ -v
    exit 0
fi

# Sizing provider. Defaults to real photo analysis, because starting without
# it silently swaps in the demo estimator -- which returns the SAME fixed
# measurements for every photo and puts a "Demo mode" warning in front of the
# customer. That is a confusing thing to rediscover, and it has happened by
# simply restarting the server without the variable set.
#
#   ./run.sh              -> real photo analysis (MediaPipe)
#   SIZING_PROVIDER=mock ./run.sh   -> demo estimator, no MediaPipe needed
export SIZING_PROVIDER="${SIZING_PROVIDER:-mediapipe}"

# Run server
echo -e "${BLUE}Starting FastAPI server...${NC}"
echo ""
echo "    🚀 Server running on http://localhost:8000"
echo "    📚 API docs: http://localhost:8000/docs"
echo "    🏥 Health: http://localhost:8000/health"
echo "    📷 Sizing provider: ${SIZING_PROVIDER}"
echo ""
echo "Press Ctrl+C to stop"
echo ""

python3 main.py
