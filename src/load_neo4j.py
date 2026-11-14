"""Load the hand-labeled lineage graph into Neo4j (Phase 2, U2).

Reads data/entities.json (same source the NetworkX backend uses) and writes:
    (:Document {id, sensitivity}) -[:MENTIONS]-> (:Entity {name, sensitivity})

Entity.sensitivity uses the explicit entity_sensitivity map; unlabeled entities
default to 'public' (generic overlap vocabulary), exactly like NetworkXGraphStore.

Idempotent: clears existing :Document/:Entity nodes first, then reloads.

Usage:
    # start Neo4j, e.g.:
    #   docker run -d --name neo4j -p 7474:7474 -p 7687:7687 \
    #     -e NEO4J_AUTH=neo4j/neo4jpassword neo4j:5
    python src/load_neo4j.py
"""
from __future__ import annotations

import json

from neo4j import GraphDatabase

from acl import doc_sensitivity
from config import ENTITIES_PATH, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER


def load() -> None:
    data = json.loads(ENTITIES_PATH.read_text())
    doc_entities: dict[str, list[str]] = data["documents"]
    entity_sensitivity: dict[str, str] = data.get("entity_sensitivity", {})

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as s:
        # Clean slate so reloads are idempotent.
        s.run("MATCH (n) WHERE n:Document OR n:Entity DETACH DELETE n")
        s.run("CREATE CONSTRAINT doc_id IF NOT EXISTS "
              "FOR (d:Document) REQUIRE d.id IS UNIQUE")
        s.run("CREATE CONSTRAINT entity_name IF NOT EXISTS "
              "FOR (e:Entity) REQUIRE e.name IS UNIQUE")

        for doc_id in doc_entities:
            s.run("MERGE (d:Document {id: $id}) SET d.sensitivity = $sens",
                  id=doc_id, sens=doc_sensitivity(doc_id))

        for doc_id, entities in doc_entities.items():
            for e in entities:
                e_sens = entity_sensitivity.get(e, "public")
                s.run(
                    "MERGE (e:Entity {name: $name}) SET e.sensitivity = $sens "
                    "WITH e MATCH (d:Document {id: $doc}) "
                    "MERGE (d)-[:MENTIONS]->(e)",
                    name=e, sens=e_sens, doc=doc_id,
                )

        docs = s.run("MATCH (d:Document) RETURN count(d) AS n").single()["n"]
        ents = s.run("MATCH (e:Entity) RETURN count(e) AS n").single()["n"]
        rels = s.run("MATCH ()-[r:MENTIONS]->() RETURN count(r) AS n").single()["n"]
    driver.close()
    print(f"Loaded Neo4j: {docs} documents, {ents} entities, {rels} MENTIONS edges")
    print(f"  URI={NEO4J_URI}  user={NEO4J_USER}")


if __name__ == "__main__":
    load()
