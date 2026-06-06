package com.echomind.expert;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/experts")
public class ExpertController {
    private final ExpertService expertService;

    public ExpertController(ExpertService expertService) {
        this.expertService = expertService;
    }

    @GetMapping
    public ResponseEntity<ExpertService.ExpertSearchResponse> findExperts(@RequestParam("project") String project) {
        return ResponseEntity.ok(expertService.findExpertsByProject(project));
    }
}
