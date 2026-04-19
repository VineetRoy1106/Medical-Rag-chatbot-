import express from "express";
import axios from "axios";
import dotenv from "dotenv";
dotenv.config({ path: "../.env" });

const router     = express.Router();
const FASTAPI_URL = process.env.FASTAPI_URL || "http://localhost:8000";

// ── POST /api/query → FastAPI /api/query ────────────────────────────────
router.post("/query", async (req, res) => {
  try {
    const response = await axios.post(`${FASTAPI_URL}/api/query`, req.body, {
      timeout: 120000,
      headers: { "Content-Type": "application/json" },
    });
    res.json(response.data);
  } catch (err) {
    const status  = err.response?.status || 500;
    const message = err.response?.data?.detail || err.message || "Pipeline error";
    console.error(`[Express] /api/query error: ${message}`);
    res.status(status).json({ error: message });
  }
});

// ── GET /api/health ─────────────────────────────────────────────────────
router.get("/health", async (req, res) => {
  try {
    const r = await axios.get(`${FASTAPI_URL}/health`, { timeout: 5000 });
    res.json({ express: "ok", fastapi: r.data });
  } catch {
    res.status(503).json({ express: "ok", fastapi: "unreachable" });
  }
});

export default router;
