#!/bin/bash
# Curalink — Start all services locally
# Usage: ./start.sh

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  ██████╗██╗   ██╗██████╗  █████╗ ██╗     ██╗███╗   ██╗██╗  ██╗"
echo " ██╔════╝██║   ██║██╔══██╗██╔══██╗██║     ██║████╗  ██║██║ ██╔╝"
echo " ██║     ██║   ██║██████╔╝███████║██║     ██║██╔██╗ ██║█████╔╝ "
echo " ██║     ██║   ██║██╔══██╗██╔══██║██║     ██║██║╚██╗██║██╔═██╗ "
echo " ╚██████╗╚██████╔╝██║  ██║██║  ██║███████╗██║██║ ╚████║██║  ██╗"
echo "  ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝"
echo -e "${NC}"
echo -e "${GREEN}AI Medical Research Assistant${NC}"
echo ""

# ── Check .env ────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo -e "${YELLOW}⚠️  .env not found. Copying from .env.example...${NC}"
  cp .env.example .env
  echo -e "${YELLOW}⚠️  Please fill in your API keys in .env then re-run this script.${NC}"
  exit 1
fi

# ── Check uv ─────────────────────────────────────────────────────────
if ! command -v uv &> /dev/null; then
  echo -e "${YELLOW}Installing uv...${NC}"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.cargo/bin:$PATH"
fi

# ── Python setup ──────────────────────────────────────────────────────
echo -e "${GREEN}[1/4] Setting up Python environment...${NC}"
cd server
if [ ! -d ".venv" ]; then
  uv venv .venv
fi
source .venv/bin/activate
uv pip install -r requirements.txt --quiet
cd ..

# ── Node setup ────────────────────────────────────────────────────────
echo -e "${GREEN}[2/4] Installing Node dependencies...${NC}"
cd express-server && npm install --silent && cd ..
cd client && npm install --silent && cd ..

# ── Start all 3 services ─────────────────────────────────────────────
echo -e "${GREEN}[3/4] Starting services...${NC}"
echo ""

# FastAPI
cd server
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
FASTAPI_PID=$!
cd ..

sleep 2

# Express
cd express-server
npm run dev &
EXPRESS_PID=$!
cd ..

sleep 1

# React
cd client
npm start &
REACT_PID=$!
cd ..

echo ""
echo -e "${GREEN}[4/4] All services running:${NC}"
echo ""
echo -e "  🌐 React UI        →  ${CYAN}http://localhost:3000${NC}"
echo -e "  📡 Express gateway →  ${CYAN}http://localhost:5000${NC}"
echo -e "  🔬 FastAPI + Swagger → ${CYAN}http://localhost:8000/docs${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"
echo ""

# ── Trap Ctrl+C to kill all processes ────────────────────────────────
trap "echo ''; echo 'Stopping all services...'; kill $FASTAPI_PID $EXPRESS_PID $REACT_PID 2>/dev/null; exit 0" INT

wait
