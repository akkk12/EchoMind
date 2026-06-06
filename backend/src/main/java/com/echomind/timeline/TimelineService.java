package com.echomind.timeline;

import java.time.LocalDate;
import java.util.Comparator;
import java.util.List;

import org.springframework.data.neo4j.core.Neo4jClient;
import org.springframework.stereotype.Service;

@Service
public class TimelineService {
    private final Neo4jClient neo4jClient;

    public TimelineService(Neo4jClient neo4jClient) {
        this.neo4jClient = neo4jClient;
    }

    public TimelineResponse getProjectTimeline(String projectName) {
        List<TimelineEvent> events = neo4jClient.query("""
                MATCH (project:Project)
                WHERE toLower(project.name) = toLower($projectName)
                CALL {
                    WITH project
                    MATCH (incident:Incident)-[:AFFECTS]->(project)
                    RETURN incident.id AS id, "Incident" AS type, incident.title AS title, toString(incident.date) AS date, incident.impact AS summary
                    UNION
                    WITH project
                    MATCH (decision:Decision)-[:AFFECTS]->(project)
                    RETURN decision.id AS id, "Decision" AS type, decision.title AS title, toString(decision.date) AS date, decision.finalDecision AS summary
                    UNION
                    WITH project
                    MATCH (review:ArchitectureReview)-[:SUPPORTS]->(:Decision)-[:AFFECTS]->(project)
                    RETURN review.id AS id, "ArchitectureReview" AS type, review.title AS title, toString(review.date) AS date, review.discussionSummary AS summary
                    UNION
                    WITH project
                    MATCH (ticket:Ticket)-[:AFFECTS]->(project)
                    OPTIONAL MATCH (ticket)-[:SUPPORTS]->(decision:Decision)
                    OPTIONAL MATCH (ticket)-[:RELATED_TO]->(incident:Incident)
                    RETURN ticket.id AS id, "Ticket" AS type, ticket.title AS title, coalesce(toString(decision.date), toString(incident.date)) AS date, ticket.description AS summary
                    UNION
                    WITH project
                    MATCH (pullRequest:PullRequest)-[:AFFECTS]->(project)
                    RETURN pullRequest.id AS id, "PullRequest" AS type, pullRequest.title AS title, toString(pullRequest.date) AS date, pullRequest.description AS summary
                }
                RETURN id, type, title, date, summary
                """)
            .bind(projectName).to("projectName")
            .fetchAs(TimelineEvent.class)
            .mappedBy((typeSystem, record) -> new TimelineEvent(
                record.get("id").asString(),
                record.get("type").asString(),
                record.get("title").asString(),
                parseLocalDate(record.get("date").asString(null)),
                record.get("summary").asString(null)
            ))
            .all()
            .stream()
            .sorted(Comparator.comparing(TimelineEvent::date, Comparator.nullsLast(Comparator.naturalOrder())))
            .toList();

        return new TimelineResponse(projectName, events);
    }

    private static LocalDate parseLocalDate(String value) {
        return value == null || value.isBlank() ? null : LocalDate.parse(value);
    }

    public record TimelineResponse(String project, List<TimelineEvent> events) {}

    public record TimelineEvent(String id, String type, String title, LocalDate date, String summary) {}
}
