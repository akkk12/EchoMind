import os
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel, Field


app = FastAPI(title="EchoMind AI Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


class Citation(BaseModel):
    type: str
    id: str
    title: str


class DecisionCore(BaseModel):
    id: str
    title: str
    date: Optional[str] = None
    owner: Optional[str] = None
    finalDecision: str
    reasons: List[str] = Field(default_factory=list)


class ArchitectureReviewEvidence(BaseModel):
    id: str
    title: str
    date: Optional[str] = None
    status: Optional[str] = None
    context: Optional[str] = None
    discussionSummary: Optional[str] = None
    alternativesConsidered: List[str] = Field(default_factory=list)
    finalDecision: Optional[str] = None
    participants: List[str] = Field(default_factory=list)


class IncidentEvidence(BaseModel):
    id: str
    title: str
    date: Optional[str] = None
    impact: Optional[str] = None
    rootCause: Optional[str] = None
    remediation: Optional[str] = None


class DiscussionEvidence(BaseModel):
    id: str
    channel: Optional[str] = None
    date: Optional[str] = None
    topic: str
    summary: Optional[str] = None
    participants: List[str] = Field(default_factory=list)


class DecisionAnalysisRequest(BaseModel):
    question: str
    decision: DecisionCore
    architectureReviews: List[ArchitectureReviewEvidence] = Field(default_factory=list)
    incidents: List[IncidentEvidence] = Field(default_factory=list)
    discussions: List[DiscussionEvidence] = Field(default_factory=list)


class DecisionAnalysisResponse(BaseModel):
    answer: str
    whyItMattered: List[str]
    tradeoffs: List[str]
    citations: List[Citation]
    confidence: str


class PersonRef(BaseModel):
    id: str
    name: str
    role: Optional[str] = None
    team: Optional[str] = None


class ExpertEvidence(BaseModel):
    type: str
    id: str
    title: str
    reason: Optional[str] = None


class ExpertCandidate(BaseModel):
    person: PersonRef
    score: int
    why: Optional[str] = None
    evidence: List[ExpertEvidence] = Field(default_factory=list)


class ExpertAnalysisRequest(BaseModel):
    query: str
    project: Optional[str] = None
    experts: List[ExpertCandidate]


class ExpertExplanation(BaseModel):
    personId: str
    name: str
    explanation: str
    bestFor: List[str]
    citations: List[Citation]


class ExpertAnalysisResponse(BaseModel):
    summary: str
    experts: List[ExpertExplanation]
    confidence: str


class TimelineEvent(BaseModel):
    id: str
    type: str
    title: str
    date: Optional[str] = None
    summary: Optional[str] = None


class TimelineAnalysisRequest(BaseModel):
    project: str
    events: List[TimelineEvent]


class TurningPoint(BaseModel):
    date: Optional[str] = None
    title: str
    explanation: str


class TimelineAnalysisResponse(BaseModel):
    narrative: str
    turningPoints: List[TurningPoint]
    currentState: str
    citations: List[Citation]
    confidence: str


def call_openai(prompt: str, response_model):
    if client is None:
        return None
    completion = client.beta.chat.completions.parse(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are EchoMind. Explain enterprise engineering history using only the supplied evidence. Be concise, polished, and cite sources."
            },
            {"role": "user", "content": prompt}
        ],
        response_format=response_model,
    )
    return completion.choices[0].message.parsed


@app.get("/health")
def health():
    return {"status": "ok", "openaiConfigured": client is not None, "model": OPENAI_MODEL}


@app.post("/decision-analysis", response_model=DecisionAnalysisResponse)
def decision_analysis(request: DecisionAnalysisRequest):
    prompt = f"""
Question: {request.question}
Decision: {request.decision.model_dump_json()}
Architecture reviews: {[item.model_dump() for item in request.architectureReviews]}
Incidents: {[item.model_dump() for item in request.incidents]}
Discussions: {[item.model_dump() for item in request.discussions]}

Return a direct decision rationale, why it mattered, tradeoffs, citations, and confidence.
"""
    parsed = call_openai(prompt, DecisionAnalysisResponse)
    if parsed:
        return parsed
    citations = [Citation(type="Decision", id=request.decision.id, title=request.decision.title)]
    citations += [Citation(type="Incident", id=item.id, title=item.title) for item in request.incidents[:2]]
    return DecisionAnalysisResponse(
        answer=f"{request.decision.title} was made because {request.decision.finalDecision}",
        whyItMattered=request.decision.reasons[:3] or ["The decision connected engineering tradeoffs to customer-facing reliability."],
        tradeoffs=["The team accepted more distributed-system complexity in exchange for better scalability and clearer ownership."],
        citations=citations,
        confidence="medium",
    )


@app.post("/expert-analysis", response_model=ExpertAnalysisResponse)
def expert_analysis(request: ExpertAnalysisRequest):
    prompt = f"""
Query: {request.query}
Project: {request.project}
Experts: {[item.model_dump() for item in request.experts]}

Explain the ranking, what each person is best for, citations, and confidence.
"""
    parsed = call_openai(prompt, ExpertAnalysisResponse)
    if parsed:
        return parsed
    experts = [
        ExpertExplanation(
            personId=item.person.id,
            name=item.person.name,
            explanation=item.why or f"{item.person.name} has strong evidence connected to {request.project}.",
            bestFor=[e.title for e in item.evidence[:3]] or [request.project or "project context"],
            citations=[Citation(type=e.type, id=e.id, title=e.title) for e in item.evidence[:3]],
        )
        for item in request.experts
    ]
    return ExpertAnalysisResponse(summary=f"EchoMind found {len(experts)} likely experts for {request.project}.", experts=experts, confidence="medium")


@app.post("/timeline-analysis", response_model=TimelineAnalysisResponse)
def timeline_analysis(request: TimelineAnalysisRequest):
    sorted_events = sorted(request.events, key=lambda event: event.date or "9999-12-31")
    prompt = f"""
Project: {request.project}
Events: {[item.model_dump() for item in sorted_events]}

Create a concise project evolution narrative, turning points, current state, citations, and confidence.
"""
    parsed = call_openai(prompt, TimelineAnalysisResponse)
    if parsed:
        return parsed
    turning_points = [
        TurningPoint(date=item.date, title=item.title, explanation=item.summary or "This event changed the project direction.")
        for item in sorted_events[:4]
    ]
    citations = [Citation(type=item.type, id=item.id, title=item.title) for item in sorted_events[:4]]
    return TimelineAnalysisResponse(
        narrative=f"{request.project} evolved through {len(sorted_events)} connected events across incidents, decisions, reviews, tickets, and pull requests.",
        turningPoints=turning_points,
        currentState=f"{request.project} now has a traceable engineering history in EchoMind.",
        citations=citations,
        confidence="medium",
    )
