import express from "express";
import cors from "cors";
import helmet from "helmet";
import morgan from "morgan";
import rateLimit from "express-rate-limit";
import mongoose from "mongoose";
import dotenv from "dotenv";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";
import axios from "axios";
import apiRouter from "./routes/api.js";

dotenv.config({ path: "../.env" });

const __filename  = fileURLToPath(import.meta.url);
const __dirname   = path.dirname(__filename);
const app         = express();
const PORT        = process.env.EXPRESS_PORT || 5000;
const FASTAPI_URL = process.env.FASTAPI_URL || "http://localhost:8000";
const MONGO_URI   = process.env.MONGODB_URI;

// ── Env validation ────────────────────────────────────────────────────────
function validateEnv() {
  const required = { MONGODB_URI: true, FASTAPI_URL: false };
  const missing  = Object.entries(required)
    .filter(([k, req]) => req && !process.env[k])
    .map(([k]) => k);
  if (missing.length) {
    console.error(`❌ Missing env vars: ${missing.join(", ")}`);
    process.exit(1);
  }
}

// ── Mongoose session model (MERN requirement) ─────────────────────────────
const messageSchema = new mongoose.Schema({
  role:      { type: String, enum: ["user", "assistant"] },
  content:   mongoose.Schema.Types.Mixed,
  timestamp: { type: Date, default: Date.now },
});

const sessionSchema = new mongoose.Schema({
  session_id:      { type: String, required: true, unique: true, index: true },
  user_id:         { type: String, index: true },
  patient_name:    String,
  disease:         { type: String, required: true },
  location:        String,
  messages:        [messageSchema],
  context_summary: String,
  created_at:      { type: Date, default: Date.now },
  updated_at:      { type: Date, default: Date.now },
});

export const Session = mongoose.model("Session", sessionSchema);

// ── MongoDB connection ────────────────────────────────────────────────────
async function connectMongo() {
  if (!MONGO_URI) return;
  try {
    await mongoose.connect(MONGO_URI, { serverSelectionTimeoutMS: 5000 });
    console.log("✅ Mongoose connected to MongoDB");
  } catch (err) {
    console.error(`⚠️  Mongoose connection failed: ${err.message}`);
  }
}

// ── FastAPI startup health check ──────────────────────────────────────────
async function waitForFastAPI(maxAttempts = 12, delayMs = 5000) {
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const res = await axios.get(`${FASTAPI_URL}/health`, { timeout: 3000 });
      if (res.data.status === "ok") {
        console.log(`✅ FastAPI reachable at ${FASTAPI_URL}`);
        return true;
      }
    } catch {
      console.log(`⏳ Waiting for FastAPI... (attempt ${attempt}/${maxAttempts})`);
      await new Promise(r => setTimeout(r, delayMs));
    }
  }
  console.warn(`⚠️  FastAPI not reachable after ${maxAttempts} attempts — requests will be proxied anyway`);
  return false;
}

// ── Trust proxy ───────────────────────────────────────────────────────────
// BUG FIX 1: Without this, express-rate-limit throws ERR_ERL_UNEXPECTED_X_FORWARDED_FOR
app.set("trust proxy", process.env.NODE_ENV === "production" ? 1 : false);

// ── Security + logging ────────────────────────────────────────────────────
app.use(helmet({ contentSecurityPolicy: false }));
app.use(morgan("dev"));
app.use(cors({
  origin: [
    "http://localhost:3000",
    "http://localhost:5000",
    process.env.RENDER_EXTERNAL_URL,
  ].filter(Boolean),
  credentials: true,
}));
app.use(express.json({ limit: "2mb" }));

// ── Rate limiting ─────────────────────────────────────────────────────────
const limiter = rateLimit({
  windowMs:  60 * 1000,
  max:        30,
  message:   { error: "Too many requests — please try again shortly" },
  standardHeaders: true,
  legacyHeaders:   false,
  validate: { xForwardedForHeader: process.env.NODE_ENV === "production" },
});
app.use("/api", limiter);

// ── Routes ────────────────────────────────────────────────────────────────
app.use("/api", apiRouter);

// ── Serve React build (production only) ──────────────────────────────────
// BUG FIX 2: Original code crashed with ENOENT if client/build didn't exist
const clientBuild = path.join(__dirname, "../client/build");
const buildExists = fs.existsSync(path.join(clientBuild, "index.html"));

if (buildExists) {
  app.use(express.static(clientBuild));
  app.get("*", (req, res) => res.sendFile(path.join(clientBuild, "index.html")));
  console.log("📦 Serving React build from /client/build");
} else {
  console.log("ℹ️  No React build — dev mode. Run React on http://localhost:3000");
  app.get("/", (req, res) => res.json({
    status: "ok", mode: "api-only",
    frontend: "http://localhost:3000",
    docs: (process.env.FASTAPI_URL || "http://localhost:8000") + "/docs",
  }));
}

// ── Health ────────────────────────────────────────────────────────────────
app.get("/health", (req, res) => res.json({
  status:  "ok",
  service: "curalink-express",
  mongo:   mongoose.connection.readyState === 1 ? "connected" : "disconnected",
}));

// ── Global error handler ──────────────────────────────────────────────────
app.use((err, req, res, next) => {
  console.error(`[Express Error] ${err.message}`);
  res.status(err.status || 500).json({ error: err.message || "Internal server error" });
});

// ── Start ─────────────────────────────────────────────────────────────────
async function start() {
  validateEnv();
  await connectMongo();
  await waitForFastAPI();

  app.listen(PORT, () => {
    console.log(`✅ Curalink Express running → http://localhost:${PORT}`);
    console.log(`📡 Proxying AI requests  → ${FASTAPI_URL}`);
    console.log(`📖 Swagger UI            → ${FASTAPI_URL}/docs`);
  });
}

start();