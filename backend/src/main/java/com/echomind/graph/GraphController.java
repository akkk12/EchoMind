package com.echomind.graph;

import java.util.List;

import org.springframework.data.neo4j.core.Neo4jClient;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/graph")
public class GraphController {
    private final Neo4jClient neo4jClient;

    public GraphController(Neo4jClient neo4jClient) {
        this.neo4jClient = neo4jClient;
    }

    @GetMapping("/search")
    public ResponseEntity<List<SearchResult>> search(@RequestParam("q") String q) {
        List<SearchResult> results = neo4jClient.query("""
                MATCH (n)
                WHERE any(label IN labels(n) WHERE label IN ["Person", "Project", "Decision", "Incident", "ArchitectureReview"])
                  AND toLower(coalesce(n.title, n.name, "")) CONTAINS toLower($q)
                RETURN n.id AS id, labels(n)[0] AS type, coalesce(n.title, n.name) AS title
                LIMIT 20
                """)
            .bind(q).to("q")
            .fetchAs(SearchResult.class)
            .mappedBy((typeSystem, record) -> new SearchResult(
                record.get("id").asString(),
                record.get("type").asString(),
                record.get("title").asString()
            ))
            .all()
            .stream()
            .toList();
        return ResponseEntity.ok(results);
    }

    public record SearchResult(String id, String type, String title) {}
}
