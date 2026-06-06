#!/usr/bin/env python3
"""
Seed the EchoMind Neo4j graph.

Setup:
  pip install neo4j
  export NEO4J_URI=bolt://localhost:7687
  export NEO4J_USER=neo4j
  export NEO4J_PASSWORD=password
  python scripts/seed_graph.py
"""

import json
import os
from pathlib import Path

from neo4j import GraphDatabase


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")


def load(name):
    with (DATA / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def slug(value):
    return value.lower().replace("&", "and").replace("#", "").replace("/", "-").replace(" ", "-").replace("_", "-")


def person_id(name):
    return f"person-{slug(name)}"


def project_id(name):
    return f"project-{slug(name)}"


def team_id(name):
    return f"team-{slug(name)}"


def constraints(tx):
    for label in ["Person", "Team", "Project", "Decision", "ArchitectureReview", "Incident", "Ticket", "PullRequest", "Discussion"]:
        tx.run(f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")


def merge_person(tx, name, role=None, team=None):
    tx.run(
        """
        MERGE (p:Person {id: $id})
        SET p.name = $name, p.role = coalesce($role, p.role), p.team = coalesce($team, p.team)
        """,
        id=person_id(name), name=name, role=role, team=team
    )
    if team:
        tx.run(
            """
            MERGE (t:Team {id: $teamId})
            SET t.name = $team
            WITH t
            MATCH (p:Person {id: $personId})
            MERGE (p)-[:BELONGS_TO]->(t)
            """,
            teamId=team_id(team), team=team, personId=person_id(name)
        )


def merge_project(tx, name):
    tx.run("MERGE (p:Project {id: $id}) SET p.name = $name, p.status = 'active'", id=project_id(name), name=name)


def seed_incidents(tx, incidents):
    for item in incidents:
        tx.run(
            """
            MERGE (i:Incident {id: $id})
            SET i.title = $title, i.date = date($date), i.impact = $impact,
                i.rootCause = $rootCause, i.remediation = $remediation
            """,
            **item
        )
        for project in item.get("relatedProjects", []):
            merge_project(tx, project)
            tx.run("MATCH (i:Incident {id: $id}), (p:Project {id: $projectId}) MERGE (i)-[:AFFECTS]->(p)", id=item["id"], projectId=project_id(project))


def seed_reviews(tx, reviews):
    for item in reviews:
        alternatives = [alt.get("option") for alt in item.get("alternatives_considered", [])]
        owner = item.get("participants", [{}])[0].get("name")
        tx.run(
            """
            MERGE (ar:ArchitectureReview {id: $id})
            SET ar.title = $title, ar.date = date($date), ar.status = $status, ar.context = $context,
                ar.discussionSummary = $discussion_summary, ar.alternativesConsidered = $alternatives,
                ar.finalDecision = $final_decision, ar.reasons = $reasons
            MERGE (d:Decision {id: $id})
            SET d.title = $title, d.date = date($date), d.owner = $owner,
                d.finalDecision = $final_decision, d.reasons = $reasons, d.sourceReviewId = $id
            MERGE (ar)-[:SUPPORTS {confidence: 'primary'}]->(d)
            """,
            alternatives=alternatives, owner=owner, **item
        )
        for participant in item.get("participants", []):
            merge_person(tx, participant["name"], participant.get("role"), participant.get("team"))
            tx.run("MATCH (p:Person {id: $personId}), (ar:ArchitectureReview {id: $reviewId}) MERGE (p)-[:PARTICIPATED_IN]->(ar)", personId=person_id(participant["name"]), reviewId=item["id"])
        for project in item.get("related_projects", []):
            merge_project(tx, project)
            tx.run("MATCH (d:Decision {id: $id}), (p:Project {id: $projectId}) MERGE (d)-[:AFFECTS]->(p)", id=item["id"], projectId=project_id(project))
        for incident_title in item.get("related_incidents", []):
            tx.run(
                "MATCH (i:Incident {title: $title}), (d:Decision {id: $id}) MERGE (i)-[:LED_TO]->(d)",
                title=incident_title, id=item["id"]
            )


def seed_tickets(tx, tickets, incident_titles):
    for item in tickets:
        merge_person(tx, item["owner"])
        merge_project(tx, item["project"])
        tx.run(
            """
            MERGE (t:Ticket {id: $id})
            SET t.title = $title, t.owner = $owner, t.project = $project, t.status = $status,
                t.description = $description, t.relatedDecisionId = $relatedDecisionId,
                t.relatedIncidentId = $relatedIncidentId
            WITH t
            MATCH (p:Person {id: $personId}), (project:Project {id: $projectId})
            MERGE (p)-[:AUTHORED {role: 'owner'}]->(t)
            MERGE (t)-[:AFFECTS {status: $status}]->(project)
            """,
            personId=person_id(item["owner"]), projectId=project_id(item["project"]), **item
        )
        if item.get("relatedDecisionId"):
            tx.run("MATCH (t:Ticket {id: $ticketId}), (d:Decision {id: $decisionId}) MERGE (t)-[:SUPPORTS]->(d)", ticketId=item["id"], decisionId=item["relatedDecisionId"])
        incident_id = incident_titles.get(item.get("relatedIncidentId"))
        if incident_id:
            tx.run("MATCH (t:Ticket {id: $ticketId}), (i:Incident {id: $incidentId}) MERGE (t)-[:RELATED_TO]->(i)", ticketId=item["id"], incidentId=incident_id)


def seed_prs(tx, prs):
    for item in prs:
        merge_person(tx, item["author"])
        merge_project(tx, item["relatedProject"])
        tx.run(
            """
            MERGE (pr:PullRequest {id: $id})
            SET pr.title = $title, pr.author = $author, pr.reviewers = $reviewers,
                pr.relatedProject = $relatedProject, pr.relatedTicketId = $relatedTicketId,
                pr.description = $description, pr.date = date($date)
            WITH pr
            MATCH (p:Person {id: $personId}), (project:Project {id: $projectId})
            MERGE (p)-[:AUTHORED]->(pr)
            MERGE (pr)-[:AFFECTS]->(project)
            """,
            personId=person_id(item["author"]), projectId=project_id(item["relatedProject"]), **item
        )
        tx.run("MATCH (pr:PullRequest {id: $prId}), (t:Ticket {id: $ticketId}) MERGE (pr)-[:SUPPORTS]->(t)", prId=item["id"], ticketId=item["relatedTicketId"])
        for reviewer in item.get("reviewers", []):
            merge_person(tx, reviewer)
            tx.run("MATCH (p:Person {id: $personId}), (pr:PullRequest {id: $prId}) MERGE (p)-[:REVIEWED]->(pr)", personId=person_id(reviewer), prId=item["id"])


def seed_discussions(tx, discussions):
    for item in discussions:
        merge_project(tx, item["project"])
        messages = [f"{m['sender']}: {m['text']}" for m in item.get("messages", [])]
        tx.run(
            """
            MERGE (d:Discussion {id: $id})
            SET d.channel = $channel, d.date = datetime($date), d.topic = $topic,
                d.project = $project, d.summary = $summary, d.relatedDecisionId = $relatedDecisionId,
                d.messages = $messages
            WITH d
            MATCH (project:Project {id: $projectId})
            MERGE (d)-[:RELATED_TO]->(project)
            """,
            messages=messages, projectId=project_id(item["project"]), **item
        )
        if item.get("relatedDecisionId"):
            tx.run("MATCH (discussion:Discussion {id: $id}), (decision:Decision {id: $decisionId}) MERGE (discussion)-[:DISCUSSED]->(decision)", id=item["id"], decisionId=item["relatedDecisionId"])
        for name in item.get("participants", []):
            merge_person(tx, name)
            tx.run("MATCH (p:Person {id: $personId}), (d:Discussion {id: $discussionId}) MERGE (p)-[:PARTICIPATED_IN]->(d)", personId=person_id(name), discussionId=item["id"])


def add_expert_edges(tx):
    tx.run("""
        MATCH (person:Person)-[:AUTHORED]->(:PullRequest)-[:AFFECTS]->(project:Project)
        WITH person, project, count(*) AS c
        MERGE (person)-[r:CONTRIBUTED_TO]->(project)
        SET r.weight = coalesce(r.weight, 0) + c * 5
    """)
    tx.run("""
        MATCH (person:Person)-[:AUTHORED]->(:Ticket)-[:AFFECTS]->(project:Project)
        WITH person, project, count(*) AS c
        MERGE (person)-[r:CONTRIBUTED_TO]->(project)
        SET r.weight = coalesce(r.weight, 0) + c * 4
    """)
    tx.run("""
        MATCH (person:Person)-[:PARTICIPATED_IN]->(:ArchitectureReview)-[:SUPPORTS]->(:Decision)-[:AFFECTS]->(project:Project)
        WITH person, project, count(*) AS c
        MERGE (person)-[r:CONTRIBUTED_TO]->(project)
        SET r.weight = coalesce(r.weight, 0) + c * 3
    """)
    tx.run("""
        MATCH (person:Person)-[:PARTICIPATED_IN]->(:Discussion)-[:RELATED_TO]->(project:Project)
        WITH person, project, count(*) AS c
        MERGE (person)-[r:CONTRIBUTED_TO]->(project)
        SET r.weight = coalesce(r.weight, 0) + c
    """)


def main():
    reviews = load("architecture_reviews.json")
    tickets = load("jira_tickets.json")
    discussions = load("slack_discussions.json")
    prs = load("pull_requests.json")
    incidents = load("incidents.json")
    incident_titles = {item["title"]: item["id"] for item in incidents}

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        session.execute_write(constraints)
        session.execute_write(seed_incidents, incidents)
        session.execute_write(seed_reviews, reviews)
        session.execute_write(seed_tickets, tickets, incident_titles)
        session.execute_write(seed_prs, prs)
        session.execute_write(seed_discussions, discussions)
        session.execute_write(add_expert_edges)
    driver.close()
    print("EchoMind Neo4j graph seeded successfully.")


if __name__ == "__main__":
    main()
