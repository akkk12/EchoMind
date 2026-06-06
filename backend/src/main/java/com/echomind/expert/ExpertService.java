package com.echomind.expert;

import java.util.List;

import org.springframework.data.neo4j.core.Neo4jClient;
import org.springframework.stereotype.Service;

@Service
public class ExpertService {
    private final Neo4jClient neo4jClient;

    public ExpertService(Neo4jClient neo4jClient) {
        this.neo4jClient = neo4jClient;
    }

    public ExpertSearchResponse findExpertsByProject(String project) {
        List<ExpertDto> experts = neo4jClient.query("""
                MATCH (p:Person)-[r:CONTRIBUTED_TO]->(project:Project)
                WHERE toLower(project.name) = toLower($project)
                OPTIONAL MATCH (p)-[:AUTHORED]->(pr:PullRequest)-[:AFFECTS]->(project)
                OPTIONAL MATCH (p)-[:AUTHORED]->(ticket:Ticket)-[:AFFECTS]->(project)
                OPTIONAL MATCH (p)-[:PARTICIPATED_IN]->(review:ArchitectureReview)-[:SUPPORTS]->(:Decision)-[:AFFECTS]->(project)
                RETURN p.id AS id,
                       p.name AS name,
                       p.role AS role,
                       p.team AS team,
                       coalesce(r.weight, 0) AS score,
                       collect(DISTINCT {type: "PullRequest", id: pr.id, title: pr.title}) +
                       collect(DISTINCT {type: "Ticket", id: ticket.id, title: ticket.title}) +
                       collect(DISTINCT {type: "ArchitectureReview", id: review.id, title: review.title}) AS evidence
                ORDER BY score DESC, name ASC
                LIMIT 6
                """)
            .bind(project).to("project")
            .fetchAs(ExpertDto.class)
            .mappedBy((typeSystem, record) -> {
                List<EvidenceDto> evidence = record.get("evidence").asList(value -> {
                    if (value.get("id").isNull()) {
                        return null;
                    }
                    return new EvidenceDto(
                        value.get("type").asString(),
                        value.get("id").asString(),
                        value.get("title").asString(null),
                        "Connected to " + project
                    );
                }).stream().filter(item -> item != null).toList();

                PersonDto person = new PersonDto(
                    record.get("id").asString(),
                    record.get("name").asString(),
                    record.get("role").asString(null),
                    record.get("team").asString(null)
                );
                int score = record.get("score").asInt(0);
                String why = person.name() + " is connected to " + project + " through " + evidence.size() + " evidence item(s).";
                return new ExpertDto(person, score, why, evidence);
            })
            .all()
            .stream()
            .toList();

        return new ExpertSearchResponse(project, experts);
    }

    public record ExpertSearchResponse(String project, List<ExpertDto> experts) {}

    public record ExpertDto(PersonDto person, int score, String why, List<EvidenceDto> evidence) {}

    public record PersonDto(String id, String name, String role, String team) {}

    public record EvidenceDto(String type, String id, String title, String reason) {}
}
