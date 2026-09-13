"""Loads .env before any test runs, so tests exercise the real Groq
judge layer if a key is present (and fall back to heuristic-only
behavior identically to production if it's not)."""

from dotenv import load_dotenv

load_dotenv()
