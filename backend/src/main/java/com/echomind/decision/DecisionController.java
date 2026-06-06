package com.echomind.decision;

import java.util.List;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/decisions")
public class DecisionController {
    private final DecisionService decisionService;

    public DecisionController(DecisionService decisionService) {
        this.decisionService = decisionService;
    }

    @GetMapping("/search")
    public ResponseEntity<List<DecisionService.DecisionSummaryResponse>> search(@RequestParam("query") String query) {
        return ResponseEntity.ok(decisionService.searchDecisions(query));
    }

    @GetMapping("/{decisionId}")
    public ResponseEntity<DecisionService.DecisionSummaryResponse> get(@PathVariable String decisionId) {
        return ResponseEntity.ok(decisionService.getDecisionSummary(decisionId));
    }
}
