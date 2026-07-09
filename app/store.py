from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from time import time


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"


def connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS metrics (
              name TEXT NOT NULL,
              key TEXT NOT NULL DEFAULT '',
              value INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (name, key)
            );
            CREATE TABLE IF NOT EXISTS safety_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              conversation_id TEXT,
              scene_id TEXT,
              risk_level INTEGER NOT NULL,
              trigger_text TEXT NOT NULL,
              action_taken TEXT NOT NULL,
              created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedback (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              conversation_id TEXT,
              type TEXT NOT NULL,
              content TEXT NOT NULL,
              created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversation_summaries (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              conversation_id TEXT NOT NULL,
              scene_id TEXT NOT NULL,
              risk_level INTEGER NOT NULL,
              summary TEXT NOT NULL,
              duration_seconds INTEGER NOT NULL,
              created_at REAL NOT NULL
            );
            """
        )


def increment_metric(name: str, key: str | None = None, amount: int = 1):
    with connect() as db:
        db.execute(
            """
            INSERT INTO metrics (name, key, value) VALUES (?, ?, ?)
            ON CONFLICT(name, key) DO UPDATE SET value = value + excluded.value
            """,
            (name, key or "", amount),
        )


def analytics_snapshot() -> dict:
    snapshot = {
        "scene_enter": {},
        "messages": 0,
        "conversations": 0,
        "ended": 0,
        "safety_hits": 0,
        "duration_seconds": 0,
        "ai_success": 0,
        "ai_fallback": 0,
    }
    with connect() as db:
        for row in db.execute("SELECT name, key, value FROM metrics"):
            if row["name"] == "scene_enter":
                snapshot["scene_enter"][row["key"]] = row["value"]
            else:
                snapshot[row["name"]] = row["value"]
    snapshot["avg_duration_seconds"] = (
        round(snapshot["duration_seconds"] / snapshot["ended"], 1) if snapshot["ended"] else 0
    )
    return snapshot


def insert_safety_event(event: dict):
    with connect() as db:
        db.execute(
            """
            INSERT INTO safety_events (conversation_id, scene_id, risk_level, trigger_text, action_taken, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.get("conversation_id"),
                event.get("scene_id"),
                event["risk_level"],
                event["trigger_text"],
                event["action_taken"],
                time(),
            ),
        )


def safety_events() -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM safety_events ORDER BY id DESC LIMIT 100")]


def insert_feedback(item: dict):
    with connect() as db:
        db.execute(
            "INSERT INTO feedback (conversation_id, type, content, created_at) VALUES (?, ?, ?, ?)",
            (item.get("conversation_id"), item["type"], item.get("content", ""), time()),
        )


def feedback() -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM feedback ORDER BY id DESC LIMIT 100")]


def insert_conversation_summary(item: dict):
    with connect() as db:
        db.execute(
            """
            INSERT INTO conversation_summaries
              (conversation_id, scene_id, risk_level, summary, duration_seconds, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                item["conversation_id"],
                item["scene_id"],
                item["risk_level"],
                item["summary"],
                item["duration_seconds"],
                time(),
            ),
        )


def conversation_summaries() -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM conversation_summaries ORDER BY id DESC LIMIT 100")]
