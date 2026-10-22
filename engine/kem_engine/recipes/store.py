"""Recipe cache + tutorial history (SPEC §6.11). SQLite under %LOCALAPPDATA%\\Kem.

key = hash(app, task_canonical, office_major_build, ui_lang, dpi_bucket). A recipe is stored only when
every step verified; it holds the plan + text locators (no images), so replay needs 0 LLM calls.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

from ..models import EnvProfile, Plan, Trace, Tutorial


def default_db() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Kem"
    base.mkdir(parents=True, exist_ok=True)
    return base / "kem.db"


def recipe_key(app: str, task: str, env: EnvProfile) -> str:
    raw = "|".join([app, task, env.office_build, env.ui_lang, str(env.scale_pct)])
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def plan_with_locators(plan: Plan, trace: Trace) -> Plan:
    """Pin each plan step to the exact UIA name/AutomationId it grounded to (inserted repair steps are
    not stored — the Grounder re-derives them if the ribbon is collapsed again)."""
    by_step = {s.plan_step_id: s for s in trace.steps if s.plan_step_id is not None and s.locator}
    steps = []
    for st in plan.steps:
        ts = by_step.get(st.id)
        if ts and st.target:
            names = [ts.locator.name] + [n for n in st.target.names if n != ts.locator.name]
            target = st.target.model_copy(update={"names": names,
                                                  "automation_id": ts.locator.automation_id or st.target.automation_id,
                                                  "control_type": ts.locator.control_type})
            st = st.model_copy(update={"target": target})
        steps.append(st)
    return plan.model_copy(update={"steps": steps})


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or default_db()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS recipes (
              key TEXT PRIMARY KEY, app TEXT, task TEXT, plan_json TEXT, knowledge_version TEXT,
              office_build TEXT, ui_lang TEXT, scale_pct INTEGER, created REAL, hits INTEGER DEFAULT 0,
              tutorial_json TEXT);
            CREATE TABLE IF NOT EXISTS aliases (question_fold TEXT PRIMARY KEY, task TEXT);
            CREATE TABLE IF NOT EXISTS tutorials (
              tutorial_id TEXT PRIMARY KEY, title TEXT, status TEXT, path TEXT, created REAL,
              llm_calls INTEGER, source TEXT);
            CREATE TABLE IF NOT EXISTS env_cache (app TEXT PRIMARY KEY, env_json TEXT, tabs_json TEXT, updated REAL);
        """)

    # recipes ------------------------------------------------------------------------------
    def save_recipe(self, plan: Plan, trace: Trace, knowledge_version: str, tutorial: Tutorial | None = None) -> bool:
        if not trace.steps or not all(s.verified for s in trace.steps):
            return False
        env = trace.env
        p = plan_with_locators(plan, trace)
        self.db.execute("INSERT OR REPLACE INTO recipes VALUES (?,?,?,?,?,?,?,?,?,0,?)",
                        (recipe_key(plan.app, plan.task_canonical, env), plan.app, plan.task_canonical,
                         p.model_dump_json(), knowledge_version, env.office_build, env.ui_lang, env.scale_pct,
                         time.time(), tutorial.model_dump_json() if tutorial else None))
        self.db.commit()
        return True

    def get_recipe(self, app: str, task: str, env: EnvProfile) -> tuple[Plan, Tutorial | None] | None:
        """(plan, stored tutorial text) — the text is reused on replay when the steps come out the same."""
        key = recipe_key(app, task, env)
        row = self.db.execute("SELECT plan_json, tutorial_json FROM recipes WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        self.db.execute("UPDATE recipes SET hits=hits+1 WHERE key=?", (key,))
        self.db.commit()
        return Plan.model_validate_json(row[0]), (Tutorial.model_validate_json(row[1]) if row[1] else None)

    def remember_question(self, question_fold: str, task: str):
        self.db.execute("INSERT OR REPLACE INTO aliases VALUES (?,?)", (question_fold, task))
        self.db.commit()

    def task_for_question(self, question_fold: str) -> str | None:
        row = self.db.execute("SELECT task FROM aliases WHERE question_fold=?", (question_fold,)).fetchone()
        return row[0] if row else None

    # env cache ----------------------------------------------------------------------------
    def save_env(self, env: EnvProfile, tabs: list[str]):
        self.db.execute("INSERT OR REPLACE INTO env_cache VALUES (?,?,?,?)",
                        (env.app, env.model_dump_json(), json.dumps(tabs, ensure_ascii=False), time.time()))
        self.db.commit()

    def get_env(self, app: str) -> tuple[EnvProfile, list[str]] | None:
        row = self.db.execute("SELECT env_json, tabs_json FROM env_cache WHERE app=?", (app,)).fetchone()
        return (EnvProfile.model_validate_json(row[0]), json.loads(row[1])) if row else None

    # tutorials ----------------------------------------------------------------------------
    def add_tutorial(self, tut: Tutorial, path: Path, llm_calls: int, source: str):
        self.db.execute("INSERT OR REPLACE INTO tutorials VALUES (?,?,?,?,?,?,?)",
                        (tut.tutorial_id, tut.title, tut.status, str(path), time.time(), llm_calls, source))
        self.db.commit()

    def list_tutorials(self) -> list[dict]:
        rows = self.db.execute("SELECT tutorial_id, title, status, path, created, llm_calls, source "
                               "FROM tutorials ORDER BY created DESC").fetchall()
        keys = ("tutorial_id", "title", "status", "path", "created", "llm_calls", "source")
        return [dict(zip(keys, r)) for r in rows]

    def tutorial_path(self, tutorial_id: str) -> Path | None:
        row = self.db.execute("SELECT path FROM tutorials WHERE tutorial_id=?", (tutorial_id,)).fetchone()
        return Path(row[0]) if row else None
