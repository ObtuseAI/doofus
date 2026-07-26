from __future__ import annotations

from doofus.core.metrics_db import connect_metrics_db
from doofus.evolution import elite_archive as ea
from doofus.evolution import evolution_pressure_mode as epm
from doofus.meta.gep import capsule_store as cs
from doofus.meta.gep import event_emitter as ee


def test_after_candidate_scored_passes_conn_to_add_elite(monkeypatch):
    seen: dict[str, object] = {}

    monkeypatch.setattr(epm, "evolution_pressure_enabled", lambda: True)
    monkeypatch.setattr(epm, "get_best_ever", lambda: {"best_score": 0})
    monkeypatch.setattr(epm, "update_best_ever", lambda *_args, **_kwargs: None)

    def fake_add_elite(candidate, score, *, skip_dedupe=False, conn=None):
        seen["candidate_id"] = candidate["candidate_id"]
        seen["score"] = score
        seen["conn"] = conn
        return {"ok": True}

    monkeypatch.setattr(epm, "add_elite", fake_add_elite)

    conn = object()
    scores = epm.after_candidate_scored(
        {"candidate_id": "PROMO1", "generation": 1637},
        {"score_total": 0.95},
        promoted=True,
        conn=conn,
    )

    assert scores["score_total"] == 0.95
    assert seen["candidate_id"] == "PROMO1"
    assert seen["score"] == 0.95
    assert seen["conn"] is conn


def test_add_elite_passes_conn_to_map_insert(tmp_path, monkeypatch):
    monkeypatch.setattr(ea, "ARCHIVE", tmp_path / "elite_archive.json")
    calls: dict[str, object] = {}

    def fake_map_insert(candidate, scores, *, arena_pass_rate=0.0, conn=None):
        calls["candidate_id"] = candidate["candidate_id"]
        calls["score_total"] = scores["score_total"]
        calls["conn"] = conn
        return {"cell_key": "cell", "sql_write_ok": True}

    monkeypatch.setattr("doofus.evolution.map_elites_archive.insert", fake_map_insert)

    conn = object()
    result = ea.add_elite(
        {
            "candidate_id": "PROMO2",
            "generation": 1637,
            "parent_id": "P1",
            "mutation_type": "trait_mutation",
            "traits": ["proof_density"],
            "score_safety": 1.0,
        },
        0.96,
        conn=conn,
    )

    assert result["elite_archive_count"] == 1
    assert calls["candidate_id"] == "PROMO2"
    assert calls["score_total"] == 0.96
    assert calls["conn"] is conn


def test_create_capsule_from_candidate_can_reuse_existing_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CAPSULES_FILE", tmp_path / "gep" / "capsules.json")

    conn = connect_metrics_db(db_path=tmp_path / "metrics.sqlite")
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS gep_capsules (
                capsule_id TEXT PRIMARY KEY,
                genes TEXT,
                fitness REAL,
                reuse_count INTEGER,
                created_at TEXT,
                updated_at TEXT
            )"""
        )
        capsule = cs.create_capsule_from_candidate(
            {"candidate_id": "PROMO3", "mutation_type": "trait_mutation", "traits": ["proof_density"]},
            0.97,
            conn=conn,
        )
        row = conn.execute(
            "SELECT capsule_id, fitness FROM gep_capsules WHERE capsule_id=?",
            (capsule.capsule_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == capsule.capsule_id
        assert float(row[1]) == 0.97
    finally:
        conn.close()


def test_gep_emit_can_reuse_existing_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(ee, "EVENTS_FILE", tmp_path / "gep" / "events.jsonl")

    conn = connect_metrics_db(db_path=tmp_path / "metrics.sqlite")
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS gep_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT,
                payload TEXT,
                created_at TEXT
            )"""
        )
        event = ee.emit("full_promotion", {"candidate_id": "PROMO4"}, conn=conn)
        row = conn.execute(
            "SELECT event_type, payload FROM gep_events WHERE created_at=?",
            (event.created_at,),
        ).fetchone()
        assert row is not None
        assert row[0] == "full_promotion"
        assert "PROMO4" in row[1]
    finally:
        conn.close()
