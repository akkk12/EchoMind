package com.echomind.decision;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.Arrays;
import java.util.List;

import org.springframework.data.neo4j.core.Neo4jClient;
import org.springframework.stereotype.Service;

@Service
public class DecisionService {
    private final Neo4jClient neo4jClient;

    public DecisionService(Neo4jClient neo4jClient) {
        this.neo4jClient = neo4jClient;
    }

    public List<DecisionSummaryResponse> searchDecisions(String query) {
        String keyword = query == null || query.isBlank() ? "" : query.trim();
        List<String> terms = Arrays.stream(keyword.toLowerCase().split("[^a-z0-9-]+"))
            .filter(term -> term.length() > 3)
            .toList();
        return neo4jClient.query("""
                MATCH (d:Decision)
                WITH d,
                     toLower(coalesce(d.title, "") + " " + coalesce(d.finalDecision, "") + " " + reduce(text = "", reason IN coalesce(d.reasons, []) | text + " " + reason)) AS haystack
                WITH d, size([term IN $terms WHERE haystack CONTAINS term]) AS score
                WHERE $keyword = "" OR score > 0
                RETURN d.id AS id, score
                ORDER BY score DESC, d.date DESC
                LIMIT 5
                """)
            .bind(keyword).to("keyword")
            .bind(terms).to("terms")
            .fetchAs(String.class)
            .mappedBy((typeSystem, record) -> record.get("id").asString())
            .all()
            .stream()
            .map(this::getDecisionSummary)
            .toList();
    }

    public DecisionSummaryResponse getDecisionSummary(String decisionId) {
        DecisionCore decision = fetchDecision(decisionId);
        if (decision == null) {
            throw new IllegalArgumentException("Decision not found: " + decisionId);
        }
        return new DecisionSummaryResponse(
            decision,
            fetchArchitectureReviews(decisionId),
            fetchDiscussions(decisionId),
            fetchIncidents(decisionId)
        );
    }

    private DecisionCore fetchDecision(String decisionId) {
        return neo4jClient.query("""
                MATCH (d:Decision {id: $decisionId})
                RETURN d.id AS id,
                       d.title AS title,
                       toString(d.date) AS date,
                       d.owner AS owner,
                       d.finalDecision AS finalDecision,
                       coalesce(d.reasons, []) AS reasons,
                       d.sourceReviewId AS sourceReviewId
                """)
            .bind(decisionId).to("decisionId")
            .fetchAs(DecisionCore.class)
            .mappedBy((typeSystem, record) -> new DecisionCore(
                record.get("id").asString(),
                record.get("title").asString(),
                parseLocalDate(record.get("date").asString(null)),
                record.get("owner").asString(null),
                record.get("finalDecision").asString(null),
                record.get("reasons").asList(value -> value.asString()),
                record.get("sourceReviewId").asString(null)
            ))
            .one()
            .orElse(null);
    }

    private List<ArchitectureReviewSummary> fetchArchitectureReviews(String decisionId) {
        return neo4jClient.query("""
                MATCH (ar:ArchitectureReview)-[:SUPPORTS]->(:Decision {id: $decisionId})
                OPTIONAL MATCH (p:Person)-[:PARTICIPATED_IN]->(ar)
                RETURN ar.id AS id,
                       ar.title AS title,
                       toString(ar.date) AS date,
                       ar.status AS status,
                       ar.context AS context,
                       ar.discussionSummary AS discussionSummary,
                       coalesce(ar.alternativesConsidered, []) AS alternativesConsidered,
                       ar.finalDecision AS finalDecision,
                       collect(DISTINCT p.name) AS participants
                ORDER BY ar.date DESC
                """)
            .bind(decisionId).to("decisionId")
            .fetchAs(ArchitectureReviewSummary.class)
            .mappedBy((typeSystem, record) -> new ArchitectureReviewSummary(
                record.get("id").asString(),
                record.get("title").asString(),
                parseLocalDate(record.get("date").asString(null)),
                record.get("status").asString(null),
                record.get("context").asString(null),
                record.get("discussionSummary").asString(null),
                record.get("alternativesConsidered").asList(value -> value.asString()),
                record.get("finalDecision").asString(null),
                record.get("participants").asList(value -> value.asString())
            ))
            .all()
            .stream()
            .toList();
    }

    private List<DiscussionSummary> fetchDiscussions(String decisionId) {
        return neo4jClient.query("""
                MATCH (discussion:Discussion)-[:DISCUSSED]->(:Decision {id: $decisionId})
                OPTIONAL MATCH (p:Person)-[:PARTICIPATED_IN]->(discussion)
                RETURN discussion.id AS id,
                       discussion.channel AS channel,
                       toString(discussion.date) AS date,
                       discussion.topic AS topic,
                       discussion.summary AS summary,
                       coalesce(discussion.messages, []) AS messages,
                       collect(DISTINCT p.name) AS participants
                ORDER BY discussion.date DESC
                """)
            .bind(decisionId).to("decisionId")
            .fetchAs(DiscussionSummary.class)
            .mappedBy((typeSystem, record) -> new DiscussionSummary(
                record.get("id").asString(),
                record.get("channel").asString(null),
                parseOffsetDateTime(record.get("date").asString(null)),
                record.get("topic").asString(null),
                record.get("summary").asString(null),
                record.get("messages").asList(value -> value.asString()),
                record.get("participants").asList(value -> value.asString())
            ))
            .all()
            .stream()
            .toList();
    }

    private List<IncidentSummary> fetchIncidents(String decisionId) {
        return neo4jClient.query("""
                MATCH (incident:Incident)-[:LED_TO]->(:Decision {id: $decisionId})
                RETURN incident.id AS id,
                       incident.title AS title,
                       toString(incident.date) AS date,
                       incident.impact AS impact,
                       incident.rootCause AS rootCause,
                       incident.remediation AS remediation
                ORDER BY incident.date DESC
                """)
            .bind(decisionId).to("decisionId")
            .fetchAs(IncidentSummary.class)
            .mappedBy((typeSystem, record) -> new IncidentSummary(
                record.get("id").asString(),
                record.get("title").asString(),
                parseLocalDate(record.get("date").asString(null)),
                record.get("impact").asString(null),
                record.get("rootCause").asString(null),
                record.get("remediation").asString(null)
            ))
            .all()
            .stream()
            .toList();
    }

    private static LocalDate parseLocalDate(String value) {
        return value == null || value.isBlank() ? null : LocalDate.parse(value);
    }

    private static OffsetDateTime parseOffsetDateTime(String value) {
        return value == null || value.isBlank() ? null : OffsetDateTime.parse(value);
    }

    public record DecisionSummaryResponse(
        DecisionCore decision,
        List<ArchitectureReviewSummary> architectureReviews,
        List<DiscussionSummary> discussions,
        List<IncidentSummary> incidents
    ) {}

    public record DecisionCore(String id, String title, LocalDate date, String owner, String finalDecision, List<String> reasons, String sourceReviewId) {}

    public record ArchitectureReviewSummary(String id, String title, LocalDate date, String status, String context, String discussionSummary, List<String> alternativesConsidered, String finalDecision, List<String> participants) {}

    public record DiscussionSummary(String id, String channel, OffsetDateTime date, String topic, String summary, List<String> messages, List<String> participants) {}

    public record IncidentSummary(String id, String title, LocalDate date, String impact, String rootCause, String remediation) {}
}
