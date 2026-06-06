#!/usr/bin/env python3
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PORT = 5173
AI_PROVIDER = os.getenv("ECHOMIND_AI_PROVIDER", "auto").lower()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def load(name):
    with (DATA / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


REVIEWS = load("architecture_reviews.json")
TICKETS = load("jira_tickets.json")
INCIDENTS = load("incidents.json")
DISCUSSIONS = load("slack_discussions.json")
PRS = load("pull_requests.json")
MEMORY = load("memory.json")

ALIASES = {
    "events": ["event", "event-driven", "order", "lifecycle"],
    "event": ["event-driven", "order", "lifecycle"],
    "duplicate": ["idempotency", "retry", "delivery", "notification"],
    "duplicates": ["idempotency", "retry", "delivery", "notification"],
    "inventory": ["stocksync", "stock", "reservation", "substitution", "store"],
    "stock": ["stocksync", "inventory", "reservation", "substitution"],
    "delivery": ["deliverytrack", "driver", "notification", "support", "status"],
    "support": ["deliverytrack", "customer", "context", "status"],
    "privacy": ["support", "customer", "address", "driver", "deliverytrack"],
    "security": ["support", "customer", "address", "driver", "deliverytrack"],
    "monolith": ["checkoutflow", "checkout", "freeze", "orders"],
    "latency": ["checkoutflow", "checkout", "freeze", "scaling"],
    "freeze": ["checkoutflow", "checkout", "holiday", "traffic"],
    "scaling": ["checkoutflow", "traffic", "holiday"],
    "expert": ["who", "person", "owner"],
    "timeline": ["evolved", "history", "project"],
}

PROJECTS = list(MEMORY["projects"].keys())


def memory_card(kind, key, title, summary, extra=None):
    return {
        "type": kind,
        "id": key,
        "title": title,
        "summary": summary,
        "extra": extra or "",
    }


def extract_response_text(payload):
    if payload.get("output_text"):
        return payload["output_text"].strip()
    parts = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in ("output_text", "text") and content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts).strip()


def ai_prompt_payload(question, base_answer):
    evidence = [
        {
            "type": item.get("type"),
            "id": item.get("id"),
            "title": item.get("title") or item.get("topic") or item.get("person", {}).get("name"),
            "summary": item.get("summary") or item.get("impact") or item.get("rootCause") or item.get("why") or item.get("extra"),
        }
        for item in base_answer.get("evidence", [])[:8]
    ]
    return {
        "question": question,
        "deterministic_answer": base_answer.get("answer"),
        "mode": base_answer.get("mode"),
        "evidence": evidence,
        "instructions": [
            "Rewrite the deterministic answer as a concise, polished EchoMind response.",
            "Use only the supplied evidence. Do not invent facts.",
            "If evidence is thin, say what is supported and what is uncertain.",
            "Keep it under 160 words.",
            "Mention source ids naturally when useful, such as AR-005 or INC-003."
        ],
    }


def call_ollama_answer(question, base_answer):
    prompt = ai_prompt_payload(question, base_answer)
    body = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "system": "You are EchoMind, an organizational memory assistant. Answer using only provided FreshCart evidence, be clear, and avoid unsupported claims.",
        "prompt": json.dumps(prompt),
        "options": {
            "temperature": 0.2,
            "num_predict": 220,
        },
    }
    request = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text = (payload.get("response") or "").strip()
        if not text:
            return None, "Ollama returned no text"
        return text, None
    except urllib.error.HTTPError as error:
        try:
            detail = error.read().decode("utf-8")
        except Exception:
            detail = str(error)
        return None, f"Ollama HTTP error: {detail[:240]}"
    except Exception as error:
        return None, f"Ollama unavailable at {OLLAMA_BASE_URL}: {error}"


def check_ollama_running():
    request = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return True, [model.get("name") for model in payload.get("models", [])]
    except Exception:
        return False, []


def call_openai_answer(question, base_answer):
    if not OPENAI_API_KEY:
        return None, "OPENAI_API_KEY is not set"

    prompt = ai_prompt_payload(question, base_answer)
    body = {
        "model": OPENAI_MODEL,
        "instructions": "You are EchoMind, an organizational memory assistant. Answer using only provided FreshCart evidence, be clear, and avoid unsupported claims.",
        "input": json.dumps(prompt),
        "max_output_tokens": 450,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text = extract_response_text(payload)
        if not text:
            return None, "OpenAI returned no text"
        return text, None
    except urllib.error.HTTPError as error:
        try:
            detail = error.read().decode("utf-8")
        except Exception:
            detail = str(error)
        return None, f"OpenAI HTTP error: {detail[:240]}"
    except Exception as error:
        return None, f"OpenAI request failed: {error}"


def maybe_enhance_with_ai(question, base_answer):
    errors = []
    providers = []
    if AI_PROVIDER in ("auto", "ollama", "local"):
        providers.append(("Ollama", OLLAMA_MODEL, call_ollama_answer))
    if AI_PROVIDER in ("auto", "openai"):
        providers.append(("OpenAI", OPENAI_MODEL, call_openai_answer))

    for provider_name, model_name, provider_call in providers:
        ai_text, ai_error = provider_call(question, base_answer)
        if not ai_text:
            errors.append(ai_error)
            continue
        enhanced = dict(base_answer)
        enhanced["answer"] = ai_text
        enhanced["aiUsed"] = True
        enhanced["aiProvider"] = provider_name
        enhanced["aiStatus"] = f"{provider_name} generated via {model_name}"
        enhanced["reasoningSteps"] = [
            *(base_answer.get("reasoningSteps", [])),
            f"Sent retrieved evidence to {provider_name} for natural-language synthesis",
        ]
        return add_answer_metadata(enhanced)

    fallback = dict(base_answer)
    fallback["aiUsed"] = False
    fallback["aiProvider"] = "Local fallback"
    fallback["aiStatus"] = " | ".join(error for error in errors if error) or "Local deterministic fallback"
    return add_answer_metadata(fallback)


def add_answer_metadata(answer):
    enriched = dict(answer)
    evidence = enriched.get("evidence", [])
    score_total = sum(int(item.get("score", 2)) for item in evidence[:8])
    if len(evidence) >= 5 and score_total >= 25:
        confidence = "high"
    elif len(evidence) >= 2:
        confidence = "medium"
    else:
        confidence = "low"
    enriched["confidence"] = confidence
    enriched["citations"] = [
        {
            "id": item.get("id"),
            "type": item.get("type", "Record"),
            "title": item.get("title") or item.get("topic") or item.get("id"),
        }
        for item in evidence[:6]
        if item.get("id")
    ]
    enriched["missingEvidence"] = (
        "No major evidence gaps detected."
        if confidence == "high"
        else "Some supporting records may be missing or weakly connected."
        if confidence == "medium"
        else "EchoMind found limited direct evidence. Treat this answer as a starting point."
    )
    return enriched


def contextual_question(question, context):
    if not context:
        return question
    lowered = question.lower()
    followup_terms = ["that", "this", "it", "they", "them", "afterward", "after that", "who approved", "why was"]
    if len(question.split()) <= 7 or any(term in lowered for term in followup_terms):
        return f"{context}. Follow-up question: {question}"
    return question


def artifact_detail(artifact_id):
    collections = [
        ("ArchitectureReview", REVIEWS),
        ("Incident", INCIDENTS),
        ("Ticket", TICKETS),
        ("PullRequest", PRS),
        ("Discussion", DISCUSSIONS),
    ]
    for kind, items in collections:
        item = next((entry for entry in items if entry.get("id") == artifact_id), None)
        if item:
            return {"type": kind, "item": item}
    if artifact_id in MEMORY["people"]:
        return {"type": "Person", "item": {"name": artifact_id, **MEMORY["people"][artifact_id]}}
    if artifact_id in MEMORY["projects"]:
        return {"type": "Project", "item": {"name": artifact_id, **MEMORY["projects"][artifact_id]}}
    return None


def project_workspace(project):
    project_name = infer_project(project, project)
    return {
        "project": {"name": project_name, **MEMORY["projects"].get(project_name, {})},
        "experts": experts(project_name)["experts"][:4],
        "timeline": timeline(project_name)["events"][:12],
        "incidents": [item for item in INCIDENTS if project_name in item.get("relatedProjects", [])],
        "decisions": [item for item in REVIEWS if project_name in item.get("related_projects", [])],
    }


def person_workspace(name):
    profile = MEMORY["people"].get(name)
    if not profile:
        return None
    artifacts = []
    for item in REVIEWS:
        if any(person.get("name") == name for person in item.get("participants", [])):
            artifacts.append({"type": "ArchitectureReview", "id": item["id"], "title": item["title"], "summary": item["discussion_summary"]})
    for item in TICKETS:
        if item.get("owner") == name:
            artifacts.append({"type": "Ticket", "id": item["id"], "title": item["title"], "summary": item["description"]})
    for item in PRS:
        if item.get("author") == name or name in item.get("reviewers", []):
            artifacts.append({"type": "PullRequest", "id": item["id"], "title": item["title"], "summary": item["description"]})
    return {"person": {"name": name, **profile}, "artifacts": artifacts[:12]}


def incident_story(incident_id):
    incident = next((item for item in INCIDENTS if item["id"] == incident_id), None)
    if not incident:
        return None
    decisions = [item for item in REVIEWS if item["id"] in incident.get("relatedDecisionIds", [])]
    return {
        "incident": incident,
        "steps": [
            {"label": "Problem", "text": incident["impact"]},
            {"label": "Investigation", "text": incident["rootCause"]},
            {"label": "Decision", "text": decisions[0]["final_decision"] if decisions else "The team documented follow-up decisions."},
            {"label": "Fix", "text": incident["remediation"]},
            {"label": "Result", "text": "The remediation became part of FreshCart's organizational memory."},
        ],
        "decisions": decisions,
    }


def memory_answer(question):
    lowered = question.lower()
    if any(phrase in lowered for phrase in ["what is freshcart", "who is freshcart", "explain freshcart", "what is finnova", "who is finnova", "explain finnova", "company"]):
        company = MEMORY["company"]
        return {
            "mode": "Company Memory",
            "title": company["name"],
            "answer": f"{company['description']} {company['story']}",
            "evidence": [
                memory_card("Company", "FreshCart", "Company overview", company["description"]),
                memory_card("Company", "Story", "Connected company story", company["story"]),
                memory_card("Company", "Why EchoMind exists", "Why EchoMind exists", company["whyEchoMindExists"]),
            ],
            "followUps": MEMORY["demoQuestions"][:4],
            "reasoningSteps": ["Recognized a company overview question", "Loaded FreshCart story memory", "Returned the highest-level narrative before artifact details"],
        }
    if any(phrase in lowered for phrase in ["what is echomind", "why echomind", "what does echomind", "trying to solve"]):
        company = MEMORY["company"]
        return {
            "mode": "Product Memory",
            "title": "Why EchoMind exists",
            "answer": company["whyEchoMindExists"],
            "evidence": [
                memory_card("Project", "EchoMind", "EchoMind", MEMORY["projects"]["EchoMind"]["plainEnglish"]),
                memory_card("Decision", "AR-009", "Create FreshCart Decision Memory", "FreshCart decided to create a graph-based memory layer connecting reviews, incidents, tickets, PRs, and discussions."),
            ],
            "followUps": ["Show me the EchoMind timeline", "What data does EchoMind connect?", "Who sponsored EchoMind?"],
            "reasoningSteps": ["Recognized an EchoMind product question", "Used the purpose statement from memory", "Linked it to AR-008"],
        }
    if any(phrase in lowered for phrase in ["full story", "simple terms", "what is happening", "explain the story", "i don't understand", "dont understand"]):
        company = MEMORY["company"]
        cards = [
            memory_card("Project", name, name, project["plainEnglish"], project["businessProblem"])
            for name, project in MEMORY["projects"].items()
        ]
        return {
            "mode": "Guided Story",
            "title": "FreshCart story in simple terms",
            "answer": f"{company['story']} In short: CheckoutFlow fixes checkout reliability, StockSync keeps grocery inventory accurate, DeliveryTrack explains order status to customers, and EchoMind connects the decisions behind all of it.",
            "evidence": cards,
            "followUps": ["Why did CheckoutFlow start?", "What broke after order events were introduced?", "Who knows each project best?"],
            "reasoningSteps": ["Recognized confusion or broad-story phrasing", "Summarized the whole memory map", "Explained each project's role in plain English"],
        }
    for project_name, project in MEMORY["projects"].items():
        if project_name.lower() in lowered and any(word in lowered for word in ["what is", "explain", "describe", "about", "purpose"]):
            return {
                "mode": "Project Memory",
                "title": project_name,
                "answer": f"{project['plainEnglish']} Its goal is to {project['goal'].lower()} The business problem: {project['businessProblem']}",
                "evidence": [
                    memory_card("Project", project_name, project_name, project["plainEnglish"], project["businessProblem"]),
                    *[
                        memory_card("Decision", review["id"], review["title"], review["final_decision"])
                        for review in REVIEWS
                        if review["id"] in project.get("keyDecisions", [])
                    ][:4],
                ],
                "followUps": [f"Show me the {project_name} timeline", f"Who knows {project_name} best?", f"What incidents affected {project_name}?"],
                "reasoningSteps": ["Recognized a project explanation question", f"Loaded {project_name} project memory", "Attached the most important related decisions"],
            }
    for term, explanation in MEMORY["glossary"].items():
        if any(word in lowered for word in ["who", "expert", "ask", "owner", "knows"]):
            continue
        if term in lowered or all(word in lowered for word in term.split()[:2]):
            return {
                "mode": "Glossary",
                "title": term,
                "answer": explanation,
                "evidence": [memory_card("Glossary", term, term, explanation)],
                "followUps": [f"Why did FreshCart use {term}?", "Show related decisions", "Who understands this best?"],
                "reasoningSteps": ["Matched a glossary term", "Returned plain-English definition", "Suggested artifact-backed follow-ups"],
            }
    return None


def decision_summary(review):
    decision_id = review["id"]
    return {
        "decision": {
            "id": decision_id,
            "title": review["title"],
            "date": review["date"],
            "owner": review["participants"][0]["name"] if review.get("participants") else None,
            "finalDecision": review["final_decision"],
            "reasons": review.get("reasons", []),
            "sourceReviewId": decision_id,
        },
        "architectureReviews": [{
            "id": review["id"],
            "title": review["title"],
            "date": review["date"],
            "status": review["status"],
            "context": review["context"],
            "discussionSummary": review["discussion_summary"],
            "alternativesConsidered": [item["option"] for item in review.get("alternatives_considered", [])],
            "finalDecision": review["final_decision"],
            "participants": [item["name"] for item in review.get("participants", [])],
        }],
        "discussions": [
            {
                "id": item["id"],
                "channel": item["channel"],
                "date": item["date"],
                "topic": item["topic"],
                "summary": item["summary"],
                "participants": item["participants"],
            }
            for item in DISCUSSIONS
            if item.get("relatedDecisionId") == decision_id
        ],
        "incidents": [
            item for item in INCIDENTS
            if decision_id in item.get("relatedDecisionIds", []) or item["title"] in review.get("related_incidents", [])
        ],
    }


def terms_for(query):
    raw = [term for term in query.lower().replace("-", " ").replace("?", " ").split() if len(term) > 2]
    expanded = []
    for term in raw:
        expanded.append(term)
        expanded.extend(ALIASES.get(term, []))
    return list(dict.fromkeys(expanded))


def infer_project(text, default="CheckoutFlow"):
    lowered = text.lower()
    for project in PROJECTS:
        if project.lower() in lowered:
            return project
    if any(word in lowered for word in ["inventory", "stock", "substitution", "reservation", "store"]):
        return "StockSync"
    if any(word in lowered for word in ["delivery", "driver", "notification", "support", "customer", "status"]):
        return "DeliveryTrack"
    if any(word in lowered for word in ["checkout", "cart", "order", "holiday", "freeze"]):
        return "CheckoutFlow"
    if any(word in lowered for word in ["memory", "echomind", "decision history"]):
        return "EchoMind"
    return default


def all_people():
    people = {}
    for review in REVIEWS:
        for person in review.get("participants", []):
            people[person["name"].lower()] = person
    return people


def infer_person(text):
    lowered = text.lower()
    for name, person in all_people().items():
        parts = name.split()
        if name in lowered or any(part in lowered for part in parts if len(part) > 3):
            return person
    return None


def artifact_text(item):
    values = []
    for key in ["id", "title", "description", "summary", "impact", "rootCause", "remediation", "topic", "channel", "project", "relatedProject", "relatedDecisionId", "relatedIncidentId"]:
        if item.get(key):
            values.append(str(item[key]))
    for key in ["reasons", "participants", "reviewers", "relatedProjects", "relatedDecisionIds"]:
        value = item.get(key)
        if isinstance(value, list):
            values.append(" ".join(str(part) for part in value))
    if item.get("participants") and isinstance(item["participants"], list):
        values.append(" ".join(p.get("name", str(p)) if isinstance(p, dict) else str(p) for p in item["participants"]))
    if item.get("messages"):
        values.append(" ".join(message.get("text", "") for message in item["messages"]))
    return " ".join(values)


def score_text(text, terms):
    lowered = text.lower()
    return sum(3 if term in lowered else 0 for term in terms)


def global_search(query, limit=8):
    terms = terms_for(query)
    artifacts = []

    for review in REVIEWS:
        artifacts.append({
            "type": "ArchitectureReview",
            "id": review["id"],
            "title": review["title"],
            "date": review["date"],
            "summary": review["discussion_summary"],
            "project": ", ".join(review.get("related_projects", [])),
            "_text": artifact_text(review) + " " + review.get("final_decision", "")
        })
    for incident in INCIDENTS:
        artifacts.append({
            "type": "Incident",
            "id": incident["id"],
            "title": incident["title"],
            "date": incident["date"],
            "summary": incident["impact"],
            "project": ", ".join(incident.get("relatedProjects", [])),
            "_text": artifact_text(incident)
        })
    for ticket in TICKETS:
        artifacts.append({
            "type": "Ticket",
            "id": ticket["id"],
            "title": ticket["title"],
            "date": None,
            "summary": ticket["description"],
            "project": ticket["project"],
            "_text": artifact_text(ticket)
        })
    for pr in PRS:
        artifacts.append({
            "type": "PullRequest",
            "id": pr["id"],
            "title": pr["title"],
            "date": pr["date"],
            "summary": pr["description"],
            "project": pr["relatedProject"],
            "_text": artifact_text(pr)
        })
    for discussion in DISCUSSIONS:
        artifacts.append({
            "type": "Discussion",
            "id": discussion["id"],
            "title": discussion["topic"],
            "date": discussion["date"],
            "summary": discussion["summary"],
            "project": discussion["project"],
            "_text": artifact_text(discussion)
        })

    scored = []
    for artifact in artifacts:
        score = score_text(artifact["_text"], terms)
        if score:
            clean = {key: value for key, value in artifact.items() if not key.startswith("_")}
            clean["score"] = score
            scored.append(clean)
    scored.sort(key=lambda item: (item["score"], item.get("date") or ""), reverse=True)
    return scored[:limit]


def person_profile(person):
    name = person["name"]
    related_reviews = [
        {"type": "ArchitectureReview", "id": review["id"], "title": review["title"], "summary": review["discussion_summary"]}
        for review in REVIEWS
        if any(p.get("name") == name for p in review.get("participants", []))
    ]
    owned_tickets = [
        {"type": "Ticket", "id": ticket["id"], "title": ticket["title"], "summary": ticket["description"]}
        for ticket in TICKETS
        if ticket.get("owner") == name
    ]
    authored_prs = [
        {"type": "PullRequest", "id": pr["id"], "title": pr["title"], "summary": pr["description"]}
        for pr in PRS
        if pr.get("author") == name
    ]
    discussions = [
        {"type": "Discussion", "id": discussion["id"], "title": discussion["topic"], "summary": discussion["summary"]}
        for discussion in DISCUSSIONS
        if name in discussion.get("participants", [])
    ]
    evidence = (authored_prs + owned_tickets + related_reviews + discussions)[:8]
    projects = sorted({
        item.get("project") or item.get("relatedProject")
        for item in TICKETS + PRS
        if item.get("owner") == name or item.get("author") == name
    } | {
        project
        for review in REVIEWS
        if any(p.get("name") == name for p in review.get("participants", []))
        for project in review.get("related_projects", [])
    })
    return {
        "mode": "Person Profile",
        "title": name,
        "answer": f"{name} is {person.get('role')} on {person.get('team')}. EchoMind connects them to {', '.join(projects[:4]) or 'FreshCart'} through architecture reviews, Jira tickets, pull requests, and discussions.",
        "evidence": evidence,
        "followUps": [
            f"Who worked with {name}?",
            f"What projects is {name} connected to?",
            f"What decisions did {name} participate in?"
        ],
        "reasoningSteps": ["Matched a FreshCart employee name", "Collected their PRs, tickets, reviews, and discussions", "Summarized their strongest project connections"],
    }


def connection_answer(question):
    mentioned_projects = [project for project in PROJECTS if project.lower() in question.lower()]
    if len(mentioned_projects) < 2:
        return None
    a, b = mentioned_projects[:2]
    evidence = []
    for review in REVIEWS:
        projects = review.get("related_projects", [])
        if a in projects and b in projects:
            evidence.append({"type": "ArchitectureReview", "id": review["id"], "title": review["title"], "summary": review["discussion_summary"]})
    for incident in INCIDENTS:
        projects = incident.get("relatedProjects", [])
        if a in projects and b in projects:
            evidence.append({"type": "Incident", "id": incident["id"], "title": incident["title"], "summary": incident["impact"]})
    if not evidence:
        return None
    return {
        "mode": "Graph Connection",
        "title": f"{a} ↔ {b}",
        "answer": f"{a} and {b} are connected through {len(evidence)} shared incidents or architecture decisions. The strongest connection is {evidence[0]['title']}.",
        "evidence": evidence[:8],
        "followUps": [
            f"Show me the {a} timeline",
            f"Who knows {b} best?",
            f"Why are {a} and {b} related?"
        ],
        "reasoningSteps": ["Detected two project names in the question", "Searched for shared incidents and architecture reviews", "Returned the strongest shared evidence"],
    }


def search_decisions(query):
    terms = terms_for(query)
    scored = []
    for review in REVIEWS:
        haystack = " ".join([
            review["title"],
            review["final_decision"],
            review["context"],
            review["discussion_summary"],
            " ".join(review.get("related_projects", [])),
            " ".join(review.get("related_incidents", [])),
            " ".join(review.get("reasons", [])),
        ]).lower()
        score = sum(1 for term in terms if term in haystack)
        if score or not terms:
            scored.append((score, review))
    scored.sort(key=lambda item: (item[0], item[1]["date"]), reverse=True)
    return [decision_summary(review) for _, review in scored[:5]]


def experts(project):
    scores = {}
    evidence = {}

    def add(name, points, item):
        scores[name] = scores.get(name, 0) + points
        evidence.setdefault(name, []).append(item)

    for ticket in TICKETS:
        if ticket["project"].lower() == project.lower():
            add(ticket["owner"], 4, {"type": "Ticket", "id": ticket["id"], "title": ticket["title"], "reason": "Owned related Jira work."})
    for pr in PRS:
        if pr["relatedProject"].lower() == project.lower():
            add(pr["author"], 5, {"type": "PullRequest", "id": pr["id"], "title": pr["title"], "reason": "Authored related implementation."})
            for reviewer in pr.get("reviewers", []):
                add(reviewer, 2, {"type": "PullRequest", "id": pr["id"], "title": pr["title"], "reason": "Reviewed related implementation."})
    for review in REVIEWS:
        if project in review.get("related_projects", []):
            for person in review.get("participants", []):
                add(person["name"], 3, {"type": "ArchitectureReview", "id": review["id"], "title": review["title"], "reason": "Participated in related architecture review."})

    people = {}
    for review in REVIEWS:
        for person in review.get("participants", []):
            people[person["name"]] = person

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:6]
    return {
        "project": project,
        "experts": [
            {
                "person": {
                    "id": "person-" + name.lower().replace(" ", "-"),
                    "name": name,
                    "role": people.get(name, {}).get("role"),
                    "team": people.get(name, {}).get("team"),
                },
                "score": score,
                "why": f"{name} is strongly connected to {project} through {len(evidence.get(name, []))} evidence item(s).",
                "evidence": evidence.get(name, [])[:6],
            }
            for name, score in ranked
        ],
    }


def important_people():
    people = {
        name: {"name": name, **person}
        for name, person in MEMORY["people"].items()
    }
    scores = {name: 0 for name in people}
    evidence = {name: [] for name in people}

    def add(name, points, item):
        if name not in scores:
            return
        scores[name] += points
        evidence[name].append(item)

    for review in REVIEWS:
        for person in review.get("participants", []):
            add(person["name"], 3, {"type": "ArchitectureReview", "id": review["id"], "title": review["title"], "summary": "Participated in an architecture decision."})
        if review.get("participants"):
            owner = review["participants"][0]["name"]
            add(owner, 2, {"type": "DecisionOwner", "id": review["id"], "title": review["title"], "summary": "Led or opened the architecture review."})

    for ticket in TICKETS:
        add(ticket["owner"], 4, {"type": "Ticket", "id": ticket["id"], "title": ticket["title"], "summary": "Owned delivery work."})

    for pr in PRS:
        add(pr["author"], 5, {"type": "PullRequest", "id": pr["id"], "title": pr["title"], "summary": "Authored implementation work."})
        for reviewer in pr.get("reviewers", []):
            add(reviewer, 2, {"type": "CodeReview", "id": pr["id"], "title": pr["title"], "summary": "Reviewed implementation work."})

    for discussion in DISCUSSIONS:
        for participant in discussion.get("participants", []):
            add(participant, 1, {"type": "Discussion", "id": discussion["id"], "title": discussion["topic"], "summary": "Contributed to team discussion."})

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_name, top_score = ranked[0]
    top_person = people[top_name]
    cards = []
    for name, score in ranked[:6]:
        person = people[name]
        cards.append({
            "type": "Person",
            "id": name,
            "title": name,
            "summary": f"{person['role']} on {person['team']}. Score {score}. {person['memorySummary']}",
            "extra": "Best for: " + ", ".join(person.get("bestFor", [])),
            "score": score,
        })

    return {
        "mode": "People Importance",
        "title": "Most important people at FreshCart",
        "answer": f"If you mean broad influence across the whole FreshCart story, {top_name} is the strongest answer. {top_person['memorySummary']} EchoMind ranks this from architecture reviews, Jira ownership, pull requests, code reviews, and discussions. For specific areas, Ethan is strongest for checkout/orders, Priya for inventory, Lucas for reliability, Amara for customer experience, and Sofia for privacy.",
        "evidence": cards,
        "followUps": [
            "Who is most important for CheckoutFlow?",
            "Who is most important for StockSync?",
            "Who should I ask about delivery notifications?",
            "Who is Priya Shah?"
        ],
        "reasoningSteps": ["Recognized a people-importance question", "Scored people across reviews, tickets, pull requests, reviews, and discussions", f"Top cross-functional score: {top_name} ({top_score})"],
    }


def timeline(project):
    events = []
    for item in INCIDENTS:
        if project in item.get("relatedProjects", []):
            events.append({"id": item["id"], "type": "Incident", "title": item["title"], "date": item["date"], "summary": item["impact"]})
    for item in REVIEWS:
        if project in item.get("related_projects", []):
            events.append({"id": item["id"], "type": "Decision", "title": item["title"], "date": item["date"], "summary": item["final_decision"]})
            events.append({"id": item["id"], "type": "ArchitectureReview", "title": item["title"], "date": item["date"], "summary": item["discussion_summary"]})
    for item in TICKETS:
        if item["project"].lower() == project.lower():
            related = next((review for review in REVIEWS if review["id"] == item["relatedDecisionId"]), None)
            events.append({"id": item["id"], "type": "Ticket", "title": item["title"], "date": related["date"] if related else None, "summary": item["description"]})
    for item in PRS:
        if item["relatedProject"].lower() == project.lower():
            events.append({"id": item["id"], "type": "PullRequest", "title": item["title"], "date": item["date"], "summary": item["description"]})
    events.sort(key=lambda item: item.get("date") or "9999-12-31")
    return {"project": project, "events": events}


def ask_echomind(question):
    lowered = question.lower()
    memory = memory_answer(question)
    if memory:
        return memory

    if any(phrase in lowered for phrase in ["most important", "key person", "main person", "most valuable", "important person", "important people", "who matters", "team lead"]):
        return important_people()

    person = infer_person(question)
    if person and any(word in lowered for word in ["who is", "person", "what does", "tell me about", "work on", "worked on"]):
        return person_profile(person)

    connection = connection_answer(question)
    if connection:
        return connection

    if any(word in lowered for word in ["who", "expert", "ask", "owner", "knows"]):
        project = infer_project(question, "CheckoutFlow")
        result = experts(project)
        names = ", ".join(item["person"]["name"] for item in result["experts"][:3]) or "No expert found"
        return {
            "mode": "Expert Finder",
            "title": f"Experts for {project}",
            "answer": f"The strongest experts for {project} are {names}. EchoMind ranks them using connected tickets, pull requests, architecture reviews, and discussions.",
            "evidence": result["experts"][:3],
            "followUps": [
                f"Show me the {project} timeline",
                f"Why was {project} designed this way?",
                f"What incidents affected {project}?"
            ],
            "reasoningSteps": ["Classified the question as an expert-finding request", f"Inferred project: {project}", "Ranked people by PRs, tickets, reviews, and discussion participation"],
        }
    if any(word in lowered for word in ["timeline", "evolve", "evolved", "history", "happened after", "after"]):
        project = infer_project(question, "CheckoutFlow")
        result = timeline(project)
        first = result["events"][0]["title"] if result["events"] else "the first recorded event"
        latest = result["events"][-1]["title"] if result["events"] else "the latest recorded event"
        return {
            "mode": "Timeline Explorer",
            "title": f"{project} timeline",
            "answer": f"{project} evolves from {first} to {latest}. The timeline connects incidents, architecture decisions, Jira work, and pull requests into one project story.",
            "evidence": result["events"][:8],
            "followUps": [
                f"Who knows {project} best?",
                f"Why did the first major {project} decision happen?",
                "What PRs implemented the follow-up work?"
            ],
            "reasoningSteps": ["Classified the question as timeline/history", f"Inferred project: {project}", "Collected incidents, decisions, reviews, tickets, and pull requests in chronological order"],
        }

    matches = search_decisions(question)
    search_hits = global_search(question)
    if not matches and not search_hits:
        return {
            "mode": "No Match",
            "title": "No strong match",
            "answer": "I could not find a strong FreshCart match. Try mentioning CheckoutFlow, StockSync, DeliveryTrack, checkout freeze, inventory, delivery notifications, idempotency, privacy, or support.",
            "evidence": [],
            "followUps": [
                "Why did checkout freeze during the holiday sale?",
                "Who knows StockSync best?",
                "How did CheckoutFlow evolve?"
            ],
            "reasoningSteps": ["Searched memory and artifacts", "No strong evidence passed the match threshold", "Suggested known FreshCart topics"],
        }
    if search_hits and (not matches or search_hits[0]["score"] > 8):
        top = search_hits[0]
        return {
            "mode": "Evidence Search",
            "title": top["title"],
            "answer": f"I found the strongest evidence in {top['type']} {top['id']}: {top['summary']} This looks related to {top.get('project') or 'FreshCart'} based on the source text.",
            "evidence": search_hits,
            "followUps": [
                f"Why did {top['title']} happen?",
                f"Who is connected to {top.get('project') or 'this work'}?",
                f"Show the timeline for {top.get('project') or infer_project(question)}"
            ],
            "reasoningSteps": ["No specialized intent was stronger than evidence search", "Searched across reviews, incidents, tickets, PRs, and discussions", f"Top match: {top['type']} {top['id']}"],
        }
    result = matches[0]
    decision = result["decision"]
    evidence = (result["incidents"] + result["architectureReviews"] + result["discussions"] + search_hits)[:10]
    return {
        "mode": "Decision Time Machine",
        "title": decision["title"],
        "answer": f"Short answer: {decision['finalDecision']} The main reasons were: {'; '.join(decision.get('reasons', [])[:3])}.",
        "evidence": evidence[:8],
        "followUps": [
            f"Who contributed to {decision['title']}?",
            "What incident led to this?",
            "Show the related project timeline"
        ],
        "reasoningSteps": ["Classified the question as decision rationale", f"Matched decision {decision['id']}", "Expanded evidence from related incidents, reviews, discussions, and search hits"],
    }


def graph_summary():
    people = sorted({person["name"] for review in REVIEWS for person in review.get("participants", [])})
    decisions = [{"id": item["id"], "title": item["title"], "projects": item.get("related_projects", [])} for item in REVIEWS]
    return {
        "people": people,
        "projects": PROJECTS,
        "incidents": [{"id": item["id"], "title": item["title"], "projects": item["relatedProjects"]} for item in INCIDENTS],
        "decisions": decisions,
        "links": [
            {"source": item["id"], "target": project, "type": "AFFECTS"}
            for item in REVIEWS
            for project in item.get("related_projects", [])
        ],
    }


def memory_summary():
    return {
        "company": MEMORY["company"],
        "projects": [
            {"name": name, **details}
            for name, details in MEMORY["projects"].items()
        ],
        "people": [
            {"name": name, **details}
            for name, details in MEMORY["people"].items()
        ],
        "glossary": [
            {"term": term, "definition": definition}
            for term, definition in MEMORY["glossary"].items()
        ],
        "incidents": INCIDENTS,
        "decisions": REVIEWS,
        "demoQuestions": MEMORY["demoQuestions"],
    }


HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EchoMind Demo</title>
  <style>
    :root{--bg:#020617;--panel:#0f172a;--line:#1e293b;--text:#e2e8f0;--muted:#94a3b8;--cyan:#22d3ee;--green:#34d399;--red:#fb7185;--violet:#a78bfa;--amber:#fbbf24;--blue:#38bdf8}
    *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,sans-serif;overflow-x:hidden}
    .app{display:grid;grid-template-columns:280px 1fr;min-height:100vh;min-width:0}
    aside{border-right:1px solid var(--line);padding:20px;background:#030712;min-width:0}
    main{padding:24px;max-width:1220px;width:100%;min-width:0}
    button,input{font:inherit}
    .brand{font-size:22px;font-weight:800;background:linear-gradient(90deg,#67e8f9,#a7f3d0,#fbbf24);background-size:200% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;animation:gradient-drift 6s ease infinite}.demo{margin-top:4px;color:var(--muted);font-size:13px;line-height:1.5}.sidebar-note{margin:18px 0;padding:12px;border:1px solid #164e63;border-radius:8px;background:linear-gradient(135deg,#082f49,#10233d 58%,#172033);color:#bae6fd;font-size:13px;line-height:1.5}.status{display:flex;align-items:center;gap:7px;margin-top:10px;color:#a7f3d0;font-size:12px}.status:before{content:"";width:7px;height:7px;border-radius:99px;background:linear-gradient(135deg,#34d399,#67e8f9);box-shadow:0 0 12px rgba(52,211,153,.75)}
    .nav{margin-top:18px}.nav button{display:block;width:100%;text-align:left;margin:7px 0;padding:11px;border:1px solid transparent;border-radius:8px;background:var(--panel);color:#cbd5e1;cursor:pointer}.nav button span{display:block;font-weight:750}.nav button small{display:block;margin-top:3px;color:#64748b;font-size:11px;font-weight:500;line-height:1.3}
    .nav button.active{background:linear-gradient(120deg,#67e8f9,#34d399 55%,#fbbf24);color:#020617;font-weight:800;animation:soft-pop .35s cubic-bezier(.2,1.5,.4,1);box-shadow:0 8px 25px rgba(34,211,238,.2)}
    .nav button.active small{color:#164e63}
    h1{margin:.25rem 0 0;font-size:34px;letter-spacing:0} h2{margin:4px 0 0} h3{margin:4px 0}
    .muted{color:var(--muted)} .eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#67e8f9;font-weight:800}
    .panel{border:1px solid var(--line);background:linear-gradient(145deg,#0f172a 0%,#101827 55%,#0b1724 100%);border-radius:8px;padding:18px;margin:16px 0;animation:rise-in .38s ease both}
    .hero{background:linear-gradient(135deg,#071521 0%,#0a2230 48%,#102239 100%);border-color:#155e75;padding:26px;box-shadow:inset 0 1px rgba(255,255,255,.03),0 16px 45px rgba(2,6,23,.32)}.hero h1{font-size:40px;max-width:760px;background:linear-gradient(90deg,#f8fafc,#a5f3fc 55%,#a7f3d0);-webkit-background-clip:text;background-clip:text;color:transparent}.hero p{max-width:800px;line-height:1.65}
    .row{display:flex;gap:10px}.stack{display:grid;gap:12px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
    input{flex:1;min-height:46px;border:1px solid #334155;border-radius:8px;background:#020617;color:var(--text);padding:0 14px}
    .primary{position:relative;overflow:hidden;background:linear-gradient(120deg,#67e8f9,#34d399 52%,#fbbf24);background-size:180% 100%;color:#020617;border:0;border-radius:8px;padding:0 18px;font-weight:800;cursor:pointer;min-height:46px;transition:transform .18s cubic-bezier(.2,1.5,.4,1),box-shadow .18s;animation:gradient-drift 7s ease infinite}.primary:after{content:"";position:absolute;inset:0;background:linear-gradient(105deg,transparent 35%,rgba(255,255,255,.45) 50%,transparent 65%);transform:translateX(-120%);animation:button-shine 4.5s ease-in-out infinite}.primary:hover{transform:translateY(-2px) scale(1.01);box-shadow:0 10px 28px rgba(52,211,153,.24)}.primary:active{transform:scale(.97)}
    .ghost{border:1px solid #334155;background:#020617;color:#cbd5e1;border-radius:8px;padding:9px 11px;cursor:pointer;text-align:left;transition:transform .18s cubic-bezier(.2,1.5,.4,1),border-color .18s,background .18s}.ghost:hover{transform:translateY(-2px);border-color:#22d3ee;background:#071521}.ghost:active{transform:scale(.98)}
    .card{border:1px solid var(--line);background:#020617;border-radius:8px;padding:14px;margin:10px 0;transition:transform .2s cubic-bezier(.2,1.5,.4,1),border-color .2s,box-shadow .2s}
    .card:hover{border-color:#155e75;transform:translateY(-3px);box-shadow:0 10px 26px rgba(0,0,0,.24)}
    .tag{display:inline-block;border:1px solid #334155;border-radius:6px;padding:4px 8px;margin:4px 4px 0 0;font-size:12px;color:#cbd5e1}
    .score{float:right;border:1px solid #155e75;background:#083344;border-radius:8px;color:#a5f3fc;padding:8px 10px;font-weight:800}
    .typeCard{border:1px solid #1e293b;background:#020617;border-radius:8px;padding:16px}.typeCard h3{margin-top:8px}.typeCard button{margin-top:10px;width:100%}
    .answerBox{border:1px solid #155e75;background:linear-gradient(135deg,#082f49,#0b3550 60%,#123047);border-radius:10px;padding:18px;line-height:1.7;box-shadow:inset 0 1px rgba(255,255,255,.04)}
    .subtle{font-size:13px;color:#64748b}
    .source-strip{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:16px}.source-item{border-left:2px solid #155e75;padding:4px 10px}.source-item strong{display:block;font-size:18px;color:#a5f3fc}.source-item span{font-size:12px;color:var(--muted)}
    .result-lead{display:flex;justify-content:space-between;gap:16px;align-items:start;flex-wrap:wrap}.result-lead h2{font-size:25px}.result-label{color:#a5f3fc;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.08em}
    details{border:1px solid var(--line);border-radius:8px;background:#020617;margin:12px 0;padding:12px 14px}summary{cursor:pointer;font-weight:750;color:#cbd5e1}details[open] summary{margin-bottom:12px}
    .section-intro{color:var(--muted);line-height:1.55;margin:6px 0 12px}.evidence-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.evidence-grid .card{margin:0}
    .ask-shell{display:flex;gap:10px;padding:7px;border:1px solid #155e75;background:#020617;border-radius:8px;margin-top:20px}.ask-shell input{border:0;background:transparent;min-height:52px;font-size:16px}.ask-shell input:focus{outline:none}.ask-shell .primary{min-height:52px}
    .quick-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}.quick-row button{border:1px solid #334155;background:#0f172a;color:#cbd5e1;border-radius:6px;padding:7px 10px;cursor:pointer;font-size:12px}
    .memory-flow{display:grid;grid-template-columns:1fr 28px 1fr 28px 1fr;align-items:center;margin-top:20px}.flow-node{border:1px solid #1e3a4a;background:#06111c;border-radius:8px;padding:12px}.flow-node strong{display:block;color:#a5f3fc;margin-bottom:4px}.flow-node span{font-size:12px;color:var(--muted)}.flow-arrow{text-align:center;color:#22d3ee;font-weight:800}
    .answer-layout{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(250px,.8fr);gap:16px;margin-top:14px}.answer-main{min-width:0}.insight-side{border:1px solid #1e293b;background:#020617;border-radius:8px;padding:14px}.insight-side h3{font-size:14px;margin-bottom:12px}
    .source-bar{margin:10px 0}.source-bar-head{display:flex;justify-content:space-between;font-size:12px;color:#cbd5e1;margin-bottom:5px}.bar-track{height:6px;border-radius:99px;background:#172033;overflow:hidden}.bar-fill{height:100%;border-radius:99px;background:linear-gradient(90deg,#22d3ee,#34d399,#fbbf24);box-shadow:0 0 10px rgba(34,211,238,.35)}
    .story-path{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:14px 0}.story-step{position:relative;border:1px solid #263548;background:#020617;border-radius:8px;padding:12px;min-height:100px}.story-step:not(:last-child):after{content:"›";position:absolute;right:-9px;top:36px;z-index:2;color:#67e8f9;font-size:22px;font-weight:800}.story-step strong{display:block;font-size:13px;margin-top:5px}.story-step span{font-size:11px;color:#67e8f9;text-transform:uppercase;font-weight:800}
    .question-echo{border-left:3px solid #22d3ee;padding:7px 12px;margin:0 0 12px;color:#cbd5e1;font-size:14px}.question-echo strong{color:#fff}
    .loading-track{height:4px;background:#172033;border-radius:99px;overflow:hidden;margin-top:14px}.loading-track:after{content:"";display:block;width:35%;height:100%;background:#22d3ee;animation:loading 1.2s ease-in-out infinite}@keyframes loading{0%{transform:translateX(-100%)}100%{transform:translateX(380%)}}
    .memory-map{position:relative;min-height:560px;border:1px solid #164e63;background:#030b14;border-radius:8px;overflow:hidden;margin-top:16px}.memory-map:before{content:"";position:absolute;inset:0;background-image:radial-gradient(#164e63 1px,transparent 1px);background-size:28px 28px;opacity:.35}.map-line{position:absolute;height:2px;background:#155e75;transform-origin:left center;opacity:.7}.map-line:after{content:"";position:absolute;top:-2px;width:6px;height:6px;border-radius:99px;background:#67e8f9;animation:travel 2.8s linear infinite}.map-center,.map-node{position:absolute;border:1px solid #155e75;background:#061521;color:var(--text);cursor:pointer;text-align:left;z-index:2;transition:transform .22s cubic-bezier(.2,1.7,.4,1),border-color .2s,box-shadow .2s}.map-center{left:50%;top:50%;width:170px;height:120px;transform:translate(-50%,-50%);padding:20px;text-align:center;border-color:#22d3ee;box-shadow:0 0 30px rgba(34,211,238,.14);animation:memory-breathe 3s ease-in-out infinite}.map-center:hover{transform:translate(-50%,-50%) scale(1.05)}.map-node{width:165px;min-height:82px;padding:12px;border-radius:8px}.map-node:hover{transform:translateY(-5px) scale(1.03);border-color:#67e8f9;box-shadow:0 12px 28px rgba(34,211,238,.12)}.map-node strong,.map-center strong{display:block}.map-node span,.map-center span{display:block;color:var(--muted);font-size:11px;margin-top:5px;line-height:1.35}.map-projects{left:5%;top:8%}.map-people{right:5%;top:8%}.map-decisions{left:5%;bottom:8%}.map-incidents{right:5%;bottom:8%}.map-spark{position:absolute;width:5px;height:5px;background:#a7f3d0;border-radius:99px;animation:twinkle 2s ease-in-out infinite}.spark-a{left:30%;top:15%}.spark-b{right:28%;top:34%;animation-delay:.7s}.spark-c{left:35%;bottom:17%;animation-delay:1.2s}
    .map-legend{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.map-legend span{border:1px solid #334155;border-radius:6px;padding:5px 8px;color:#cbd5e1;font-size:12px}
    .citation{border:1px solid #155e75;background:#061521;color:#a5f3fc;border-radius:6px;padding:5px 8px;cursor:pointer;font-size:12px;margin:4px 4px 0 0}.citation:hover{background:#083344}.confidence{display:grid;grid-template-columns:auto 1fr;gap:10px;align-items:center;border:1px solid #263548;background:#020617;border-radius:8px;padding:12px;margin-top:12px}.confidence strong{color:#a7f3d0;text-transform:capitalize}.confidence p{margin:0;color:var(--muted);font-size:12px}
    .modal-backdrop{position:fixed;inset:0;background:rgba(2,6,23,.82);z-index:20;display:grid;place-items:center;padding:18px}.modal{width:min(760px,100%);max-height:85vh;overflow:auto;border:1px solid #155e75;background:#0f172a;border-radius:8px;padding:20px;box-shadow:0 24px 80px rgba(0,0,0,.5);animation:soft-pop .25s ease}.modal-close{float:right;border:1px solid #334155;background:#020617;color:#fff;border-radius:6px;padding:7px 10px;cursor:pointer}.json-view{white-space:pre-wrap;word-break:break-word;color:#cbd5e1;background:#020617;border:1px solid #1e293b;padding:12px;border-radius:8px;font-size:12px}
    .back-btn{border:1px solid #334155;background:linear-gradient(145deg,#07111e,#0c1928);color:#cbd5e1;border-radius:7px;padding:8px 11px;cursor:pointer;margin-bottom:14px;transition:transform .18s,border-color .18s}.back-btn:hover{border-color:#22d3ee;color:#fff;transform:translateX(-2px)}.source-app{border:1px solid #334155;background:#f8fafc;color:#172033;border-radius:8px;overflow:hidden;animation:rise-in .35s ease;box-shadow:0 24px 70px rgba(0,0,0,.38)}.source-top{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px 18px;background:#fff;border-bottom:1px solid #dbe3ec}.source-brand{font-weight:900;font-size:18px}.source-origin{font-size:12px;color:#64748b}.source-layout{display:grid;grid-template-columns:minmax(0,1fr) 240px;gap:0}.source-main{padding:22px}.source-side{padding:18px;background:#f1f5f9;border-left:1px solid #dbe3ec}.source-app h1{font-size:28px;color:#0f172a}.source-app h3{color:#334155;margin-top:20px}.source-app p{line-height:1.6}.source-field{border-bottom:1px solid #dbe3ec;padding:10px 0}.source-field span{display:block;color:#64748b;font-size:11px;text-transform:uppercase;font-weight:800;margin-bottom:3px}.source-field strong{display:block;color:#1e293b;font-size:13px}.source-block{border:1px solid #dbe3ec;background:#fff;border-radius:7px;padding:14px;margin:10px 0}.source-tag{display:inline-block;border-radius:5px;padding:4px 7px;background:#e2e8f0;color:#334155;font-size:11px;font-weight:700;margin:3px}.source-jira .source-brand{color:#0052cc}.source-slack .source-brand{color:#611f69}.source-github .source-brand{color:#24292f}.source-pagerduty .source-brand{color:#06ac38}.source-confluence .source-brand{color:#1868db}
    .workspace-hero{border:1px solid #155e75;background:#061521;border-radius:8px;padding:18px}.workspace-hero h2{font-size:28px}.metric-row{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px}.metric{border:1px solid #263548;background:#020617;border-radius:8px;padding:12px}.metric strong{display:block;font-size:22px;color:#a5f3fc}.metric span{font-size:11px;color:var(--muted)}
    .incident-story{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.incident-step{position:relative;border:1px solid #263548;background:#020617;border-radius:8px;padding:12px;min-height:135px}.incident-step strong{display:block;color:#67e8f9;margin-bottom:8px}.incident-step p{font-size:12px;color:#cbd5e1;line-height:1.45}.incident-step:not(:last-child):after{content:"›";position:absolute;right:-9px;top:55px;color:#67e8f9;font-size:22px;z-index:2}
    .demo-step{display:grid;grid-template-columns:42px 1fr;gap:12px;align-items:start;border-left:2px solid #155e75;padding:0 0 20px 18px;margin-left:15px}.demo-number{width:42px;height:42px;border-radius:99px;background:#22d3ee;color:#020617;display:grid;place-items:center;font-weight:900;margin-left:-40px}.dropzone{border:1px dashed #22d3ee;background:#061521;border-radius:8px;padding:32px;text-align:center}.absorb{height:10px;background:#172033;border-radius:99px;overflow:hidden;margin-top:15px}.absorb div{height:100%;background:#34d399;width:0;transition:width 1s ease}.absorb.done div{width:100%}
    .memory-map{background:linear-gradient(145deg,#030b14,#071521 55%,#101b31);box-shadow:inset 0 0 70px rgba(34,211,238,.04)}
    .map-line{background:linear-gradient(90deg,#155e75,#22d3ee,#34d399)}
    .map-center,.map-node{background:linear-gradient(145deg,#061521,#0b2231)}
    .map-center{border-color:#67e8f9;background:linear-gradient(145deg,#082f49,#123047 58%,#153a35)}
    .citation{background:linear-gradient(135deg,#061521,#0b2633)}.citation:hover{background:linear-gradient(135deg,#083344,#164e63);box-shadow:0 0 16px rgba(34,211,238,.15)}
    .metric strong,.score{background:linear-gradient(90deg,#67e8f9,#a7f3d0,#fbbf24);-webkit-background-clip:text;background-clip:text;color:transparent}
    .demo-number{background:linear-gradient(135deg,#67e8f9,#34d399,#fbbf24);box-shadow:0 0 20px rgba(34,211,238,.2)}
    .absorb div{background:linear-gradient(90deg,#22d3ee,#34d399,#fbbf24)}
    /* Investor-demo shell */
    body{background:linear-gradient(155deg,#020617 0%,#06111d 48%,#071827 100%);min-height:100vh}
    .app{display:grid;grid-template-columns:1fr}
    aside{position:sticky;top:0;z-index:12;display:flex;align-items:center;gap:18px;border-right:0;border-bottom:1px solid rgba(148,163,184,.16);padding:12px 24px;background:rgba(3,7,18,.94);backdrop-filter:blur(18px)}
    aside .demo{display:block;max-width:320px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    aside .sidebar-note{margin:0 0 0 auto;padding:7px 10px;border-radius:7px;font-size:11px;line-height:1.25;max-width:225px}.sidebar-note>.status{margin-top:3px}
    .nav{display:flex;gap:7px;margin:0}.nav button{width:auto;min-width:150px;margin:0;padding:9px 13px}.nav button small{display:none}
    main{max-width:1280px;margin:0 auto;padding:30px 26px 50px}
    h1{font-size:38px}.eyebrow{color:#7dd3fc}
    .hero{padding:30px;background:linear-gradient(135deg,#071521 0%,#0a2634 50%,#10243b 100%);box-shadow:0 22px 60px rgba(0,0,0,.28)}
    .hero-grid{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(280px,.7fr);gap:26px;align-items:stretch}
    .hero-grid:has(#out:not(:empty)){grid-template-columns:1fr}.hero-grid:has(#out:not(:empty)) .hero-signal{display:none}
    .hero-copy{display:flex;flex-direction:column;justify-content:center}.hero-copy h1{font-size:48px;line-height:1.05;max-width:760px;margin-top:10px}.hero-copy p{font-size:16px;color:#b8c5d6}
    .hero-copy #out:not(:empty){margin-top:16px}.hero-copy #out .panel{margin:12px 0 0}
    .ask-shell{scroll-margin-top:88px}
    .hero-signal{border:1px solid rgba(103,232,249,.22);background:rgba(2,6,23,.5);border-radius:8px;padding:18px;display:flex;flex-direction:column;justify-content:center}
    .live-badge{display:inline-flex;align-items:center;gap:7px;width:max-content;border:1px solid rgba(52,211,153,.3);background:rgba(6,78,59,.22);color:#a7f3d0;border-radius:99px;padding:6px 9px;font-size:11px;font-weight:800}.live-badge:before{content:"";width:7px;height:7px;border-radius:99px;background:#34d399;box-shadow:0 0 12px #34d399}
    .wow-card{margin-top:18px;border-left:3px solid #22d3ee;padding:12px 14px;background:rgba(8,47,73,.35)}.wow-card strong{display:block;font-size:15px}.wow-card span{display:block;color:#94a3b8;font-size:12px;margin-top:5px;line-height:1.45}.example-question{display:block;margin-top:16px;color:#a5f3fc;font-size:12px;line-height:1.5}
    .trust-row{display:flex;gap:7px;flex-wrap:wrap;margin-top:15px}.trust-row span{border:1px solid #263548;border-radius:6px;padding:5px 7px;color:#a5b4c7;font-size:11px}
    .stat-strip{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:16px 0}.stat-tile{border:1px solid #263548;background:linear-gradient(145deg,#08111f,#0d1b2b);border-radius:8px;padding:13px;transition:transform .2s,border-color .2s}.stat-tile:hover{transform:translateY(-3px);border-color:#22d3ee}.stat-tile strong{display:block;font-size:24px;background:linear-gradient(90deg,#67e8f9,#a7f3d0);-webkit-background-clip:text;background-clip:text;color:transparent}.stat-tile span{display:block;color:#94a3b8;font-size:11px;margin-top:3px}
    .empty-state{border:1px solid #263548;background:linear-gradient(145deg,#0b1423,#0b1726);border-radius:8px;padding:20px}.empty-title{display:flex;align-items:center;justify-content:space-between;gap:14px}.empty-title p{margin:5px 0 0;color:#94a3b8}.prompt-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:16px}.prompt-card{border:1px solid #263548;background:#050d18;border-radius:8px;padding:14px;text-align:left;color:#e2e8f0;cursor:pointer;transition:transform .2s,border-color .2s,background .2s}.prompt-card:hover{transform:translateY(-3px);border-color:#22d3ee;background:#071827}.prompt-card span{display:block;color:#67e8f9;font-size:10px;text-transform:uppercase;font-weight:900;margin-bottom:7px}.prompt-card strong{display:block;font-size:13px;line-height:1.4}
    .section-header{display:flex;align-items:end;justify-content:space-between;gap:16px;margin:26px 0 12px}.section-header h2{font-size:25px}.section-header p{margin:4px 0 0;color:#94a3b8}.section-link{border:1px solid #334155;background:#07111e;color:#cbd5e1;border-radius:7px;padding:8px 11px;cursor:pointer}
    .memory-dashboard{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}.memory-dashboard .metric{background:linear-gradient(145deg,#08111f,#0c1c2d);min-height:100px}.memory-dashboard .metric p{font-size:11px;color:#94a3b8;line-height:1.4}
    .workspace-hero{background:linear-gradient(135deg,#071521,#0a2634 55%,#10243b);box-shadow:0 16px 45px rgba(0,0,0,.22)}
    .source-app{box-shadow:0 20px 60px rgba(0,0,0,.32)}
    @media(max-width:1000px){.hero-grid{grid-template-columns:1fr}.hero-signal{min-height:180px}.stat-strip,.memory-dashboard{grid-template-columns:repeat(2,1fr)}aside .demo,aside .sidebar-note{display:none}}
    @media(max-width:700px){aside{padding:10px 12px;gap:10px}.brand{font-size:19px}.nav{margin-left:auto}.nav button{min-width:auto;padding:8px 10px}.prompt-grid,.stat-strip,.memory-dashboard{grid-template-columns:1fr}.hero-copy h1{font-size:36px}main{padding:18px 12px 40px}}
    @keyframes rise-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}@keyframes soft-pop{0%{transform:scale(.96)}100%{transform:scale(1)}}@keyframes memory-breathe{0%,100%{box-shadow:0 0 20px rgba(34,211,238,.1)}50%{box-shadow:0 0 40px rgba(52,211,153,.24)}}@keyframes travel{from{left:0}to{left:100%}}@keyframes twinkle{0%,100%{opacity:.25;transform:scale(.7)}50%{opacity:1;transform:scale(1.8)}}@keyframes gradient-drift{0%,100%{background-position:0% 50%}50%{background-position:100% 50%}}@keyframes button-shine{0%,70%{transform:translateX(-120%)}88%,100%{transform:translateX(120%)}}
    .timeline{border-left:1px solid #334155;padding-left:18px}.dot{position:relative}.dot:before{content:"";position:absolute;left:-25px;top:18px;width:12px;height:12px;border-radius:99px;background:var(--cyan);border:2px solid #020617}
    .graphRow{display:grid;grid-template-columns:170px 1fr;gap:10px;align-items:start}.pill{display:inline-block;border-radius:99px;padding:3px 8px;font-size:12px;font-weight:800;color:#020617;margin-right:6px}.p-Person{background:#94a3b8}.p-Project{background:#14b8a6}.p-Decision{background:#22d3ee}.p-Incident{background:#fb7185}
    /* 2026 startup design system */
    :root{--bg:#07080b;--panel:#101116;--panel-2:#14161d;--line:rgba(255,255,255,.09);--line-strong:rgba(255,255,255,.16);--text:#f7f8fa;--muted:#999faa;--cyan:#8be9fd;--green:#8af0c7;--amber:#ffd479;--shadow:0 1px 2px rgba(0,0,0,.32),0 18px 55px rgba(0,0,0,.18);--shadow-hover:0 1px 2px rgba(0,0,0,.4),0 22px 70px rgba(0,0,0,.32)}
    html{scroll-behavior:smooth}body{background:radial-gradient(circle at 50% -20%,#192132 0,#0b0d12 35%,#07080b 68%);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:14px;line-height:1.55;letter-spacing:0;color:var(--text)}
    aside{padding:10px 24px;background:rgba(7,8,11,.82);border-color:var(--line);box-shadow:0 1px rgba(255,255,255,.02);backdrop-filter:blur(22px) saturate(130%)}
    .brand{display:flex;align-items:center;gap:9px;font-size:17px;font-weight:750;letter-spacing:-.02em;background:none;color:#fff;animation:none}.brand:before{content:"E";display:grid;place-items:center;width:28px;height:28px;border:1px solid rgba(139,233,253,.38);border-radius:7px;background:linear-gradient(145deg,#1a2230,#10131a);color:#a5f3fc;font-size:13px;box-shadow:inset 0 1px rgba(255,255,255,.08),0 5px 16px rgba(0,0,0,.3)}
    aside .demo{color:#7e8490;font-size:12px}.sidebar-note{background:#0d1117!important;border-color:var(--line)!important;color:#b3b8c2!important}
    .nav{padding:3px;background:#0b0c10;border:1px solid var(--line);border-radius:8px}.nav button{min-width:136px;padding:7px 12px;border-radius:6px;background:transparent;color:#858b96;font-size:12px;font-weight:650;transition:background .2s ease,color .2s ease,box-shadow .2s ease,transform .2s ease}.nav button:hover{background:#15171d;color:#e8eaed}.nav button.active{background:#f2f3f5;color:#111318;box-shadow:0 1px 3px rgba(0,0,0,.35);animation:none}.nav button.active small{color:#5d6470}
    main{max-width:1240px;padding:44px 30px 80px}
    h1,h2,h3{letter-spacing:-.025em;color:#f6f7f8}h1{font-size:42px;line-height:1.08;font-weight:730}h2{font-size:22px;line-height:1.2;font-weight:690}h3{font-size:15px;line-height:1.35;font-weight:660}.eyebrow{font-size:10px;letter-spacing:.12em;color:#8be9fd;font-weight:750}.muted,.section-intro{color:var(--muted)}
    .panel{padding:22px;margin:18px 0;border-color:var(--line);border-radius:8px;background:rgba(16,17,22,.88);box-shadow:var(--shadow);animation:startup-enter .45s cubic-bezier(.16,1,.3,1) both}
    .hero{position:relative;overflow:hidden;padding:42px;border-color:rgba(139,233,253,.16);background:linear-gradient(145deg,rgba(20,24,32,.98),rgba(12,14,19,.98));box-shadow:0 1px rgba(255,255,255,.05),0 35px 100px rgba(0,0,0,.3)}
    .hero:before{content:"";position:absolute;inset:0;background:linear-gradient(110deg,transparent 35%,rgba(139,233,253,.045),transparent 65%);pointer-events:none}.hero-grid{position:relative;gap:34px}.hero-copy h1{font-size:54px;line-height:1.02;letter-spacing:-.045em;background:linear-gradient(180deg,#fff 25%,#aab1bc 100%);-webkit-background-clip:text;background-clip:text}.hero-copy p{font-size:15px;max-width:660px;color:#a1a7b2}
    .hero-signal{border-color:var(--line);border-radius:8px;background:rgba(255,255,255,.025);box-shadow:inset 0 1px rgba(255,255,255,.04)}.wow-card{background:transparent;border-color:#8be9fd}.example-question{color:#9ea5b0}
    .ask-shell{padding:5px;margin-top:24px;border-color:var(--line-strong);border-radius:8px;background:#08090c;box-shadow:0 0 0 1px rgba(0,0,0,.3),0 14px 35px rgba(0,0,0,.22);transition:border-color .2s ease,box-shadow .2s ease}.ask-shell:focus-within{border-color:rgba(139,233,253,.52);box-shadow:0 0 0 3px rgba(139,233,253,.08),0 18px 42px rgba(0,0,0,.3)}.ask-shell input{min-height:48px;padding:0 14px;color:#fff}.ask-shell input::placeholder{color:#656b76}
    .primary{min-height:44px;border:1px solid rgba(255,255,255,.8);border-radius:6px;background:#f4f5f6;color:#111318;font-size:12px;font-weight:750;animation:none;box-shadow:0 1px 2px rgba(0,0,0,.4);transition:transform .2s cubic-bezier(.16,1,.3,1),background .2s ease,box-shadow .2s ease}.primary:after{display:none}.primary:hover{transform:translateY(-1px);background:#fff;box-shadow:0 8px 24px rgba(0,0,0,.32)}.primary:active{transform:translateY(0) scale(.98)}
    .ghost,.section-link,.back-btn{border-color:var(--line);border-radius:6px;background:#0c0d11;color:#c5c9d0;transition:transform .2s cubic-bezier(.16,1,.3,1),border-color .2s ease,background .2s ease,color .2s ease,box-shadow .2s ease}.ghost:hover,.section-link:hover,.back-btn:hover{transform:translateY(-1px);border-color:var(--line-strong);background:#15171d;color:#fff;box-shadow:0 10px 28px rgba(0,0,0,.2)}
    .card,.typeCard,.metric,.stat-tile,.prompt-card,.empty-state,.workspace-hero,.insight-side,.story-step,.incident-step,details,.confidence{border-color:var(--line);border-radius:8px;background:rgba(13,14,18,.92);box-shadow:0 1px rgba(255,255,255,.025);transition:transform .25s cubic-bezier(.16,1,.3,1),border-color .25s ease,background .25s ease,box-shadow .25s ease}.card:hover,.metric:hover,.stat-tile:hover,.prompt-card:hover{transform:translateY(-3px);border-color:rgba(139,233,253,.25);background:#12151b;box-shadow:var(--shadow-hover)}
    .tag,.trust-row span,.map-legend span{border-color:var(--line);border-radius:5px;background:rgba(255,255,255,.025);color:#aeb4be}.citation{border-color:rgba(139,233,253,.22);border-radius:5px;background:#0d1419;color:#a5f3fc}.citation:hover{background:#12212a;border-color:rgba(139,233,253,.45)}
    .answerBox{border-color:rgba(139,233,253,.18);border-radius:8px;background:#101820;box-shadow:inset 0 1px rgba(255,255,255,.035);font-size:15px}.answer-layout{gap:14px}.question-echo{border-color:#8be9fd;color:#b7bdc6}.result-label{color:#8be9fd;font-size:10px}.confidence strong{color:#8af0c7}
    .stat-strip{gap:12px;margin:20px 0}.stat-tile{padding:16px}.stat-tile strong,.metric strong,.score{background:none;color:#f5f6f7;font-size:22px}.stat-tile span{color:#858b96}.empty-state{padding:24px}.prompt-grid{gap:12px}.prompt-card{padding:17px}.prompt-card span{color:#8be9fd}.prompt-card strong{font-size:14px}
    .memory-dashboard{gap:12px}.memory-dashboard .metric{padding:16px;background:#0d0f14}.memory-map{border-color:var(--line);background:linear-gradient(145deg,#0a0c10,#0d1117);box-shadow:inset 0 1px rgba(255,255,255,.03),var(--shadow)}.memory-map:before{opacity:.2}.map-center,.map-node{border-color:var(--line-strong);background:#12151b;box-shadow:0 12px 35px rgba(0,0,0,.25)}.map-center{border-color:rgba(139,233,253,.4);background:#111b22}.map-node:hover{border-color:rgba(139,233,253,.45);box-shadow:0 18px 50px rgba(0,0,0,.4)}
    .loading-track{height:3px;background:#20232a}.loading-track:after{width:28%;background:linear-gradient(90deg,transparent,#8be9fd,#8af0c7,transparent);animation:loading 1.05s ease-in-out infinite}.loading-state{display:grid;gap:10px;margin-top:14px}.loading-line{height:9px;border-radius:4px;background:linear-gradient(90deg,#151820 25%,#222731 50%,#151820 75%);background-size:220% 100%;animation:skeleton 1.35s ease infinite}.loading-line:nth-child(2){width:88%}.loading-line:nth-child(3){width:64%}
    .source-app{border-color:var(--line);border-radius:8px}.source-block{border-radius:6px}.section-header{margin:34px 0 14px}.section-header h2{font-size:26px}.live-badge{border-color:rgba(138,240,199,.22);background:rgba(138,240,199,.06);color:#8af0c7}.status:before{background:#8af0c7}
    @keyframes startup-enter{from{opacity:0;transform:translateY(10px) scale(.992)}to{opacity:1;transform:none}}@keyframes skeleton{0%{background-position:120% 0}100%{background-position:-120% 0}}
    @media(max-width:900px){main{padding:24px 14px 60px}.hero{padding:24px}.hero-copy h1{font-size:40px}.panel{padding:17px}.empty-title,.section-header{align-items:flex-start;flex-direction:column}.stat-strip,.memory-dashboard{grid-template-columns:repeat(2,1fr)}}
    @media(max-width:560px){aside{padding:9px 10px}.brand:before{display:none}.nav{margin-left:auto}.hero-copy h1{font-size:34px}.stat-strip,.memory-dashboard{grid-template-columns:1fr}.trust-row{display:none}}
    @media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
    @media(max-width:900px){.app{grid-template-columns:1fr}.grid,.grid3,.source-strip,.evidence-grid,.answer-layout,.story-path,.metric-row,.incident-story,.source-layout{grid-template-columns:1fr}.source-side{border-left:0;border-top:1px solid #dbe3ec}.incident-step:not(:last-child):after{display:none}.row,.ask-shell{flex-direction:column}.memory-flow{grid-template-columns:1fr}.flow-arrow{transform:rotate(90deg);padding:4px}.story-step:not(:last-child):after{display:none}aside{border-right:0;border-bottom:1px solid var(--line);padding:12px}.demo,.sidebar-note{display:none}.nav{display:flex;gap:7px;overflow-x:auto;margin-top:10px;padding-bottom:3px}.nav button{min-width:150px;margin:0;padding:9px}.nav button small{display:none}main{padding:14px}.hero{padding:18px}.hero h1{font-size:32px}.memory-map{min-height:650px}.map-center{top:50%}.map-projects,.map-people,.map-decisions,.map-incidents{left:50%;right:auto;transform:translateX(-50%)}.map-projects{top:3%}.map-people{top:20%}.map-decisions{bottom:20%}.map-incidents{bottom:3%}.map-node:hover{transform:translateX(-50%) scale(1.03)}.map-line{display:none}}
  </style>
</head>
<body><div class="app"><aside><div class="brand">EchoMind</div><div class="demo">AI-powered organizational memory for the fictional FreshCart engineering team.</div><div class="sidebar-note">EchoMind connects decisions, incidents, projects, people, tickets, pull requests, and discussions into one searchable company memory.<div class="status">Local AI is ready</div></div><div class="nav">
<button id="nav-ask" class="active" onclick="show('ask')"><span>Ask EchoMind</span><small>Start with any company question</small></button>
<button id="nav-memory" onclick="show('memory')"><span>Company Memory</span><small>Browse the map, projects, people, incidents, and decisions</small></button>
</div></aside><main id="main"></main></div>
<div id="modal-root"></div>
<script>
const main=document.getElementById('main');
let lastQuestion='';
const viewStack=[];
const viewMotion=new MutationObserver(()=>{if(window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;main.animate([{opacity:.35,transform:'translateY(7px)'},{opacity:1,transform:'translateY(0)'}],{duration:360,easing:'cubic-bezier(.16,1,.3,1)'});});
viewMotion.observe(main,{childList:true});
const samples=[
  'Explain the full story in simple terms',
  'Who is the most important person on the team?',
  'What is CheckoutFlow?',
  'Who is Priya Shah?',
  'Why did checkout freeze during the holiday sale?',
  'Who knows StockSync inventory reservations?',
  'How did CheckoutFlow evolve?',
  'Why did delivery notifications need idempotency keys?',
  'What happened after duplicate delivery notifications?',
  'How is StockSync connected to DeliveryTrack?'
];
const groupedSamples=[
  ['Understand the story',['Explain the full story in simple terms','What is FreshCart?','What is CheckoutFlow?']],
  ['Ask who knows what',['Who is the most important person on the team?','Who knows StockSync inventory reservations?','Who should I ask about delivery notifications?']],
  ['Ask why things changed',['Why did checkout freeze during the holiday sale?','Why did FreshCart add inventory reservations?','Why did delivery notifications need idempotency keys?']],
  ['Explore connections',['How did CheckoutFlow evolve?','How is StockSync connected to DeliveryTrack?','What happened after duplicate delivery notifications?']]
];
function esc(x){return String(x??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function nav(id){document.querySelectorAll('.nav button').forEach(b=>b.classList.remove('active'));document.getElementById('nav-'+id).classList.add('active')}
async function get(url){const r=await fetch(url);return r.json()}
function show(id){viewStack.length=0;nav(id); if(id==='ask') ask(); if(id==='memory') memory()}
function panel(title,body,eyebrow=''){return `<section class="panel">${eyebrow?`<div class="eyebrow">${esc(eyebrow)}</div>`:''}<h2>${esc(title)}</h2>${body}</section>`}
function chips(items){return (items||[]).map(x=>`<span class="tag">${esc(x)}</span>`).join('')}
function card(item){const id=item.id||item.person?.name;return `<div class="card" ${id?`onclick="openDetail('${esc(id)}')" style="cursor:pointer"`:''}><div class="eyebrow">${esc(item.type||item.id||'Evidence')} ${esc(item.id||'')}</div><h3>${esc(item.title||item.topic||item.person?.name||'Evidence')}</h3><p class="muted">${esc(item.summary||item.impact||item.rootCause||item.reason||item.why||'')}</p>${item.extra?`<p>${esc(item.extra)}</p>`:''}${id?'<span class="subtle">Open source details</span>':''}</div>`}
function reasoning(steps){return `<details><summary>How EchoMind reached this answer</summary><ol>${(steps||[]).map(s=>`<li>${esc(s)}</li>`).join('')}</ol></details>`}
function evidenceView(items){const evidence=items||[];const top=evidence.slice(0,3);const more=evidence.slice(3);return panel('Sources behind this answer',`<p class="section-intro">These are the strongest company records EchoMind connected to your question.</p><div class="evidence-grid">${top.map(card).join('')||'<p class="muted">No supporting source was found.</p>'}</div>${more.length?`<details><summary>View ${more.length} more supporting sources</summary>${more.map(card).join('')}</details>`:''}`,'Evidence')}
function sourceSummary(items){const counts={};(items||[]).forEach(x=>{const type=x.type||'Record';counts[type]=(counts[type]||0)+1});const rows=Object.entries(counts).sort((a,b)=>b[1]-a[1]);const max=Math.max(...rows.map(x=>x[1]),1);return `<div class="insight-side"><h3>Evidence mix</h3>${rows.map(([type,count])=>`<div class="source-bar"><div class="source-bar-head"><span>${esc(type)}</span><strong>${count}</strong></div><div class="bar-track"><div class="bar-fill" style="width:${Math.max(18,(count/max)*100)}%"></div></div></div>`).join('')||'<p class="muted">No sources found.</p>'}</div>`}
function storyPath(items){const top=(items||[]).slice(0,3);return top.length?`<div class="story-path">${top.map(x=>`<div class="story-step"><span>${esc(x.type||'Record')} ${esc(x.id||'')}</span><strong>${esc(x.title||x.topic||'Company record')}</strong></div>`).join('')}</div>`:''}
function citations(items){return (items||[]).map(x=>`<button class="citation" onclick="openDetail('${esc(x.id)}')">${esc(x.id)}</button>`).join('')}
function confidence(data){return `<div class="confidence"><strong>${esc(data.confidence||'medium')} confidence</strong><p>${esc(data.missingEvidence||'')}</p></div>`}
function closeModal(){document.getElementById('modal-root').innerHTML=''}
function pushView(){viewStack.push(main.innerHTML)}
function backButton(){return `<button class="back-btn" onclick="goBack()">← Back</button>`}
function goBack(){if(viewStack.length){main.innerHTML=viewStack.pop();window.scrollTo(0,0)}else{show('memory')}}
function sourceInfo(type){return {Ticket:['Jira','jira'],PullRequest:['GitHub','github'],Discussion:['Slack','slack'],Incident:['PagerDuty','pagerduty'],ArchitectureReview:['Confluence','confluence'],Decision:['Confluence','confluence']}[type]||['FreshCart Source','confluence']}
function sourceFields(item){const skip=['description','impact','rootCause','remediation','discussion_summary','final_decision','messages','alternatives_considered','reasons'];return Object.entries(item).filter(([k,v])=>!skip.includes(k)&&typeof v!=='object').slice(0,8).map(([k,v])=>`<div class="source-field"><span>${esc(k.replaceAll('_',' '))}</span><strong>${esc(v)}</strong></div>`).join('')}
function sourceBlocks(type,item){const blocks=[];const add=(title,text)=>{if(text)blocks.push(`<div class="source-block"><h3>${esc(title)}</h3><p>${esc(Array.isArray(text)?text.join(' · '):text)}</p></div>`)};add('Description',item.description||item.discussion_summary||item.impact);add('Root cause',item.rootCause);add('Remediation',item.remediation);add('Final decision',item.final_decision);add('Reasons',item.reasons);add('Alternatives considered',item.alternatives_considered?.map(x=>x.name||x));add('Conversation',item.messages?.map(x=>`${x.author||x.user}: ${x.text||x.message}`));return blocks.join('')}
async function openDetail(id){pushView();const data=await get('/api/detail?id='+encodeURIComponent(id));const [brand,kind]=sourceInfo(data.type);const item=data.item||{};main.innerHTML=`${backButton()}<div class="source-app source-${kind}"><div class="source-top"><div><div class="source-brand">${brand}</div><div class="source-origin">Synthetic FreshCart source record</div></div><span class="source-tag">${esc(data.type)}</span></div><div class="source-layout"><div class="source-main"><div class="eyebrow">${esc(id)}</div><h1>${esc(item.title||item.topic||item.name||id)}</h1>${sourceBlocks(data.type,item)||'<div class="source-block"><p>This source record contains structured company memory.</p></div>'}</div><aside class="source-side"><h3>Record details</h3>${sourceFields(item)}${Object.entries(item).filter(([k,v])=>Array.isArray(v)&&!['messages','reasons','alternatives_considered'].includes(k)).slice(0,4).map(([k,v])=>`<div class="source-field"><span>${esc(k.replaceAll('_',' '))}</span>${v.map(x=>`<span class="source-tag">${esc(typeof x==='object'?(x.name||JSON.stringify(x)):x)}</span>`).join('')}</div>`).join('')}</aside></div></div>`;window.scrollTo(0,0)}
async function openProject(name){pushView();const d=await get('/api/project?name='+encodeURIComponent(name));main.innerHTML=`${backButton()}<div class="eyebrow">Project workspace</div><div class="workspace-hero"><h2>${esc(d.project.name)}</h2><p>${esc(d.project.plainEnglish||'Connected FreshCart project memory.')}</p><div class="metric-row"><div class="metric"><strong>${d.experts.length}</strong><span>experts</span></div><div class="metric"><strong>${d.incidents.length}</strong><span>incidents</span></div><div class="metric"><strong>${d.decisions.length}</strong><span>decisions</span></div><div class="metric"><strong>${d.timeline.length}</strong><span>timeline events</span></div></div></div>${panel('Experts',d.experts.map(card).join(''))}${panel('Recent history',d.timeline.map(card).join(''))}`;window.scrollTo(0,0)}
async function openPerson(name){pushView();const d=await get('/api/person?name='+encodeURIComponent(name));main.innerHTML=`${backButton()}<div class="eyebrow">Person profile</div><div class="workspace-hero"><h2>${esc(d.person.name)}</h2><p>${esc(d.person.role)} · ${esc(d.person.team)}</p><p class="muted">${esc(d.person.memorySummary)}</p>${chips(d.person.bestFor)}</div>${panel('Connected work',d.artifacts.map(card).join('')||'<p class="muted">No connected work found.</p>')}`;window.scrollTo(0,0)}
async function openIncident(id){pushView();const d=await get('/api/incident-story?id='+encodeURIComponent(id));main.innerHTML=`${backButton()}<div class="eyebrow">Incident story</div><h1>${esc(d.incident.title)}</h1><p class="muted">${esc(d.incident.date)} · ${esc(d.incident.relatedProjects.join(', '))}</p><button class="primary" onclick="openDetail('${esc(id)}')">Open original incident source</button><div class="incident-story">${d.steps.map(s=>`<div class="incident-step"><strong>${esc(s.label)}</strong><p>${esc(s.text)}</p></div>`).join('')}</div>${panel('Related decisions',d.decisions.map(x=>card({type:'Decision',id:x.id,title:x.title,summary:x.final_decision})).join('')||'<p class="muted">No linked decision.</p>')}`;window.scrollTo(0,0)}
function memoryMap(data){return `<div class="memory-map"><div class="map-spark spark-a"></div><div class="map-spark spark-b"></div><div class="map-spark spark-c"></div><div class="map-line" style="left:25%;top:25%;width:31%;transform:rotate(26deg)"></div><div class="map-line" style="left:55%;top:49%;width:30%;transform:rotate(-43deg)"></div><div class="map-line" style="left:25%;top:75%;width:31%;transform:rotate(-26deg)"></div><div class="map-line" style="left:55%;top:51%;width:30%;transform:rotate(43deg)"></div><button class="map-center" onclick="show('ask')"><strong>EchoMind</strong><span>Ask across the full FreshCart memory</span></button><button class="map-node map-projects" onclick="openProject('CheckoutFlow')"><strong>${data.projects.length} Projects</strong><span>Open a connected project workspace</span></button><button class="map-node map-people" onclick="openPerson('Ethan Brooks')"><strong>${data.people.length} People</strong><span>Open a connected expert profile</span></button><button class="map-node map-decisions" onclick="openDetail('AR-001')"><strong>10 Decisions</strong><span>Open an architecture decision record</span></button><button class="map-node map-incidents" onclick="openIncident('INC-001')"><strong>5 Incidents</strong><span>Open an incident story</span></button></div><div class="map-legend"><span>Select a node to explore</span><span>Moving pulses show memory connections</span><span>Local AI explains the story</span></div>`}
function sampleButtons(target){return `<div class="grid3">${samples.map(s=>`<button class="ghost" onclick="document.getElementById('${target}').value='${esc(s)}'">${esc(s)}</button>`).join('')}</div>`}
function ask(){main.innerHTML=`<section class="panel hero"><div class="hero-grid"><div class="hero-copy"><div class="eyebrow">AI-powered organizational memory</div><h1>Ask what happened.<br>Understand why.</h1><p>EchoMind reconstructs the story behind decisions, incidents, and projects from scattered company records, then explains it with local AI.</p><form class="ask-shell" onsubmit="runAsk(event)"><input id="askq" aria-label="Ask about FreshCart" placeholder="Ask why a decision happened, who knows a project, or what changed..." value=""><button class="primary">Ask EchoMind</button></form><div id="out"></div><div class="trust-row"><span>Private local AI</span><span>Evidence-backed answers</span><span>Clickable source records</span></div></div><div class="hero-signal"><div><div class="live-badge">FreshCart memory online</div><div class="wow-card"><strong>One question. The complete story.</strong><span>Connect an incident to its Slack discussion, architecture decision, Jira work, pull requests, and experts.</span></div><span class="example-question">Example: “Why did checkout freeze during the holiday sale?”</span></div></div></div></section><div class="stat-strip"><div class="stat-tile"><strong>95</strong><span>connected records</span></div><div class="stat-tile"><strong>21</strong><span>decisions + incidents</span></div><div class="stat-tile"><strong>6</strong><span>known experts</span></div><div class="stat-tile"><strong>4</strong><span>active projects</span></div><div class="stat-tile"><strong>100%</strong><span>synthetic demo data</span></div></div><section class="empty-state"><div class="empty-title"><div><div class="eyebrow">Start exploring</div><h2>What would you like to understand?</h2><p>Ask naturally. EchoMind chooses the right memory path automatically.</p></div><button class="section-link" onclick="show('memory')">Browse Company Memory</button></div><div class="prompt-grid"><button class="prompt-card" onclick="askExample('Why did checkout freeze during the holiday sale?')"><span>Decision time machine</span><strong>Why did checkout freeze during the holiday sale?</strong></button><button class="prompt-card" onclick="askExample('Who knows StockSync inventory reservations?')"><span>Expert discovery</span><strong>Who knows StockSync inventory reservations?</strong></button><button class="prompt-card" onclick="askExample('How did CheckoutFlow evolve?')"><span>Project history</span><strong>How did CheckoutFlow evolve?</strong></button></div></section><div class="section-header"><div><div class="eyebrow">More questions</div><h2>Reveal the FreshCart story</h2><p>Every answer stays grounded in the underlying source records.</p></div></div><section class="panel"><div class="grid">${groupedSamples.map(group=>`<div class="typeCard"><div class="eyebrow">${esc(group[0])}</div>${group[1].map(q=>`<button class="ghost" onclick="askExample('${esc(q)}')">${esc(q)}</button>`).join('')}</div>`).join('')}</div></section>`}
function askExample(question){if(!document.getElementById('askq'))show('ask');document.getElementById('askq').value=question;runAsk(new Event('submit'))}
async function runAsk(e){e.preventDefault();const q=document.getElementById('askq').value.trim();if(!q)return;const context=lastQuestion;lastQuestion=q;const out=document.getElementById('out');out.innerHTML=panel('Connecting the company story...',`<div class="question-echo"><strong>Your question:</strong> ${esc(q)}</div><div class="answerBox">Searching FreshCart records and asking the local AI to explain what they mean.<div class="loading-state"><div class="loading-line"></div><div class="loading-line"></div><div class="loading-line"></div></div></div><div class="loading-track"></div>`,'EchoMind is thinking');document.querySelector('.ask-shell').scrollIntoView({behavior:'smooth',block:'start'});const data=await get('/api/ask?query='+encodeURIComponent(q)+'&context='+encodeURIComponent(context));const aiChip=data.aiUsed?`${data.aiProvider||'AI'} generated`:'local fallback';const status=data.aiUsed&&data.aiStatus?`<p class="subtle">${esc(data.aiStatus)}</p>`:data.aiUsed?'':`<p class="subtle">Using EchoMind's evidence-grounded local fallback.</p>`;out.innerHTML=panel('Answer',`<div class="question-echo"><strong>You asked:</strong> ${esc(q)}</div><div class="result-lead"><div><div class="result-label">What EchoMind found</div><h2>${esc(data.title)}</h2></div>${chips([aiChip])}</div><div class="answer-layout"><div class="answer-main"><div class="answerBox">${esc(data.answer)}</div><div style="margin-top:12px">${chips([data.mode,'grounded in company records'])}</div>${status}<div style="margin-top:10px">${citations(data.citations)}</div>${confidence(data)}</div>${sourceSummary(data.evidence)}</div><div class="result-label" style="margin-top:18px">How the story connects</div>${storyPath(data.evidence)}${reasoning(data.reasoningSteps)}`,'Your question')+evidenceView(data.evidence)+panel('Ask a follow-up',`<p class="section-intro">EchoMind remembers your previous question, so short follow-ups like “Who approved that?” work.</p><div class="grid3">${data.followUps.map(x=>`<button class="ghost" onclick="askExample('${esc(x)}')">${esc(x)}</button>`).join('')}<button class="ghost" onclick="askExample('Who approved that?')">Who approved that?</button></div>`,'Conversation')}
async function memory(){const data=await get('/api/memory');main.innerHTML=`<div class="section-header"><div><div class="eyebrow">Living company memory</div><h1>FreshCart Company Memory</h1><p>Explore the people, projects, incidents, and decisions behind every answer.</p></div><button class="primary" onclick="show('ask')">Ask about this memory</button></div><div class="memory-dashboard"><div class="metric"><strong>${data.projects.length}</strong><span>Projects</span><p>Connected product and platform initiatives.</p></div><div class="metric"><strong>${data.people.length}</strong><span>People</span><p>Experts ranked from demonstrated contributions.</p></div><div class="metric"><strong>${data.incidents.length}</strong><span>Incidents</span><p>Operational events that changed future work.</p></div><div class="metric"><strong>${data.decisions.length}</strong><span>Decisions</span><p>Architecture choices with traceable rationale.</p></div></div>${memoryMap(data)}${panel('The story EchoMind remembers',`<p>${esc(data.company.story)}</p><p class="muted">${esc(data.company.whyEchoMindExists)}</p>`,'FreshCart')}${panel('Projects',`<div class="grid">${data.projects.map(p=>`<div class="card" onclick="openProject('${esc(p.name)}')" style="cursor:pointer"><div class="eyebrow">Project workspace</div><h3>${esc(p.name)}</h3><p>${esc(p.plainEnglish)}</p><p class="muted">${esc(p.businessProblem)}</p>${chips(p.keywords.slice(0,6))}</div>`).join('')}</div>`)}${panel('People',`<div class="grid">${data.people.map(p=>`<div class="card" onclick="openPerson('${esc(p.name)}')" style="cursor:pointer"><div class="eyebrow">${esc(p.team)}</div><h3>${esc(p.name)}</h3><p>${esc(p.role)}</p><p class="muted">${esc(p.memorySummary)}</p>${chips(p.bestFor)}</div>`).join('')}</div>`)}${panel('Incidents',`<div class="grid">${data.incidents.map(x=>`<div class="card" onclick="openIncident('${esc(x.id)}')" style="cursor:pointer"><div class="eyebrow">${esc(x.id)} · ${esc(x.date)}</div><h3>${esc(x.title)}</h3><p class="muted">${esc(x.impact)}</p></div>`).join('')}</div>`)}${panel('Decisions',`<div class="grid">${data.decisions.map(x=>`<div class="card" onclick="openDetail('${esc(x.id)}')" style="cursor:pointer"><div class="eyebrow">${esc(x.id)} · Architecture decision</div><h3>${esc(x.title)}</h3><p class="muted">${esc(x.final_decision)}</p></div>`).join('')}</div>`)}${panel('Shared language',`<div class="grid">${data.glossary.map(g=>`<div class="card"><h3>${esc(g.term)}</h3><p class="muted">${esc(g.definition)}</p></div>`).join('')}</div>`)}`}
function decision(){main.innerHTML=`<div class="eyebrow">Decision history</div><h1>Why did we choose this?</h1><p class="muted">Connect an architecture choice to the incidents, discussions, and tradeoffs that shaped it.</p><form class="panel row" onsubmit="runDecision(event)"><input id="q" value="Why did delivery notifications need idempotency keys?"><button class="primary">Find the reason</button></form>${sampleButtons('q')}<div id="out"></div>`}
async function runDecision(e){e.preventDefault();const q=document.getElementById('q').value;const data=await get('/api/decisions/search?query='+encodeURIComponent(q));if(!data.length){document.getElementById('out').innerHTML=panel('No match','<p class="muted">Try CheckoutFlow, StockSync, DeliveryTrack, idempotency, checkout freeze, inventory, support, or privacy.</p>');return}const d=data[0];const analysis=await fetch('/decision-analysis',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...d,question:q})}).then(r=>r.json());document.getElementById('out').innerHTML=panel(d.decision.title,`<p>${esc(d.decision.finalDecision)}</p>${chips(d.decision.reasons)}`,'Matched Decision')+panel('Polished Explanation',`<p>${esc(analysis.answer)}</p><h3>Why it mattered</h3>${(analysis.whyItMattered||[]).map(x=>`<div class="card">${esc(x)}</div>`).join('')}<h3>Tradeoffs</h3>${chips(analysis.tradeoffs)}`,'AI-style summary')+panel('Evidence',[...d.incidents,...d.architectureReviews,...d.discussions].map(card).join(''))}
function expert(){main.innerHTML=`<div class="eyebrow">Team knowledge</div><h1>Who should I ask?</h1><p class="muted">Find the people with the strongest demonstrated knowledge of a project.</p><form class="panel row" onsubmit="runExpert(event)"><input id="project" value="StockSync"><button class="primary">Find experts</button></form><div class="grid3">${['CheckoutFlow','StockSync','DeliveryTrack','EchoMind'].map(p=>`<button class="ghost" onclick="document.getElementById('project').value='${p}'">${p}</button>`).join('')}</div><div id="out"></div>`}
async function runExpert(e){e.preventDefault();const p=document.getElementById('project').value;const data=await get('/api/experts?project='+encodeURIComponent(p));document.getElementById('out').innerHTML=panel(`Experts for ${data.project}`,data.experts.map(x=>`<div class="card" onclick="openPerson('${esc(x.person.name)}')" style="cursor:pointer"><div class="score">${x.score}</div><div class="eyebrow">Open person profile</div><h3>${esc(x.person.name)}</h3><p>${esc(x.person.role||'')} · ${esc(x.person.team||'')}</p><p class="muted">${esc(x.why)}</p>${x.evidence.map(ev=>`<button class="citation" onclick="event.stopPropagation();openDetail('${esc(ev.id)}')">${esc(ev.type)} ${esc(ev.id)}</button>`).join('')}</div>`).join('')||'<p class="muted">No experts found.</p>')}
function timeline(){main.innerHTML=`<div class="eyebrow">Project history</div><h1>How did this project evolve?</h1><p class="muted">Follow incidents, decisions, tickets, and pull requests in the order they happened.</p><form class="panel row" onsubmit="runTimeline(event)"><input id="project" value="CheckoutFlow"><button class="primary">Show history</button></form><div class="grid3">${['CheckoutFlow','StockSync','DeliveryTrack','EchoMind'].map(p=>`<button class="ghost" onclick="document.getElementById('project').value='${p}'">${p}</button>`).join('')}</div><div id="out"></div>`}
async function runTimeline(e){e.preventDefault();const p=document.getElementById('project').value;const data=await get('/api/timeline?project='+encodeURIComponent(p));document.getElementById('out').innerHTML=panel(data.project,`<button class="primary" onclick="openProject('${esc(data.project)}')">Open project workspace</button><div class="timeline">${data.events.map(ev=>`<div class="card dot" onclick="${ev.type==='Incident'?`openIncident('${esc(ev.id)}')`:`openDetail('${esc(ev.id)}')`}" style="cursor:pointer"><div class="eyebrow">${esc(ev.type)} · ${esc(ev.date||'No date')}</div><h3>${esc(ev.title)}</h3><p class="muted">${esc(ev.summary||'')}</p></div>`).join('')}</div>`,'Chronological events')}
async function graph(){const data=await get('/api/graph/summary');main.innerHTML=`<div class="eyebrow">Connected company memory</div><h1>How everything connects</h1><p class="muted">See which decisions, projects, incidents, and people share history.</p>${panel('What EchoMind connects',`<div class="grid"><div class="card"><span class="pill p-Person">Person</span><h3>${data.people.length} people</h3><p class="muted">${data.people.join(', ')}</p></div><div class="card"><span class="pill p-Project">Project</span><h3>${data.projects.length} projects</h3><p class="muted">${data.projects.join(', ')}</p></div><div class="card"><span class="pill p-Incident">Incident</span><h3>${data.incidents.length} incidents</h3><p class="muted">${data.incidents.map(x=>x.title).join(', ')}</p></div><div class="card"><span class="pill p-Decision">Decision</span><h3>${data.decisions.length} decisions</h3><p class="muted">AR-001 through AR-010</p></div></div>`)}${panel('Decisions connected to projects',data.links.slice(0,30).map(x=>`<div class="card graphRow"><div><span class="pill p-Decision">Decision</span>${esc(x.source)}</div><div><span class="eyebrow">${esc(x.type)}</span><h3>${esc(x.target)}</h3></div></div>`).join(''))}`}
function demoMode(){main.innerHTML=`<div class="eyebrow">Three-minute guided story</div><h1>See EchoMind connect the dots</h1><p class="muted">Follow one FreshCart incident from failure to expertise to architecture change.</p><section class="panel"><div class="demo-step"><div class="demo-number">1</div><div><h3>Understand what broke</h3><p class="muted">Start with the holiday checkout freeze and see the evidence-backed explanation.</p><button class="primary" onclick="askExample('Why did checkout freeze during the holiday sale?')">Ask why it failed</button></div></div><div class="demo-step"><div class="demo-number">2</div><div><h3>Find who understood it</h3><p class="muted">See which engineers contributed to the system and its recovery.</p><button class="ghost" onclick="askExample('Who knows CheckoutFlow best?')">Find the expert</button></div></div><div class="demo-step"><div class="demo-number">3</div><div><h3>Trace what changed afterward</h3><p class="muted">Follow the project timeline from incident through decisions and implementation.</p><button class="ghost" onclick="show('timeline');document.getElementById('project').value='CheckoutFlow';runTimeline(new Event('submit'))">Open project history</button></div></div></section>`}
function importMemory(){main.innerHTML=`<div class="eyebrow">Memory ingestion simulator</div><h1>Show EchoMind learning something new</h1><p class="muted">This hackathon-safe simulator demonstrates how imported Jira, Slack, incident, or PR records become connected memory.</p><section class="panel"><div class="dropzone"><h2>Drop synthetic company records here</h2><p class="muted">No real company data is uploaded. Select a source type to simulate ingestion.</p><div class="quick-row" style="justify-content:center"><button onclick="simulateImport('incident-postmortem.json')">Incident postmortem</button><button onclick="simulateImport('jira-export.json')">Jira export</button><button onclick="simulateImport('slack-thread.json')">Slack discussion</button></div><div id="absorb" class="absorb"><div></div></div></div><div id="import-result"></div></section>`}
async function simulateImport(name){document.getElementById('absorb').classList.add('done');const d=await fetch('/api/import-simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})}).then(r=>r.json());setTimeout(()=>{document.getElementById('import-result').innerHTML=panel('New memory absorbed',`<p>${esc(d.summary)}</p><div class="metric-row"><div class="metric"><strong>${d.created.records}</strong><span>records</span></div><div class="metric"><strong>${d.created.connections}</strong><span>connections</span></div><div class="metric"><strong>${d.created.people}</strong><span>people</span></div><div class="metric"><strong>${d.created.projects}</strong><span>projects</span></div></div>`,'Import complete')},700)}
show('ask');
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def html(self):
        payload = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/":
            return self.html()
        if parsed.path == "/api/ask":
            question = params.get("query", [""])[0]
            context = params.get("context", [""])[0]
            resolved_question = contextual_question(question, context)
            answer = maybe_enhance_with_ai(question, ask_echomind(resolved_question))
            answer["resolvedQuestion"] = resolved_question
            return self.json(answer)
        if parsed.path == "/api/ai/status":
            ollama_running, ollama_models = check_ollama_running()
            return self.json({
                "mode": AI_PROVIDER,
                "ollama": {
                    "configured": True,
                    "running": ollama_running,
                    "baseUrl": OLLAMA_BASE_URL,
                    "model": OLLAMA_MODEL,
                    "installedModels": ollama_models,
                },
                "openai": {
                    "configured": bool(OPENAI_API_KEY),
                    "model": OPENAI_MODEL,
                },
            })
        if parsed.path == "/api/memory":
            return self.json(memory_summary())
        if parsed.path == "/api/search":
            return self.json(global_search(params.get("query", [""])[0], limit=20))
        if parsed.path == "/api/decisions/search":
            return self.json(search_decisions(params.get("query", [""])[0]))
        if parsed.path == "/api/experts":
            return self.json(experts(params.get("project", ["StockSync"])[0]))
        if parsed.path == "/api/timeline":
            return self.json(timeline(params.get("project", ["CheckoutFlow"])[0]))
        if parsed.path == "/api/graph/summary":
            return self.json(graph_summary())
        if parsed.path == "/api/detail":
            detail = artifact_detail(params.get("id", [""])[0])
            return self.json(detail or {"error": "Not found"}, 200 if detail else 404)
        if parsed.path == "/api/project":
            return self.json(project_workspace(params.get("name", ["CheckoutFlow"])[0]))
        if parsed.path == "/api/person":
            result = person_workspace(params.get("name", [""])[0])
            return self.json(result or {"error": "Not found"}, 200 if result else 404)
        if parsed.path == "/api/incident-story":
            result = incident_story(params.get("id", ["INC-001"])[0])
            return self.json(result or {"error": "Not found"}, 200 if result else 404)
        self.json({"error": "Not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or "{}")
        if self.path == "/decision-analysis":
            decision = body.get("decision", {})
            incidents = body.get("incidents", [])
            incident_text = ""
            if incidents:
                incident_text = f" This was especially important after {incidents[0].get('title')}, where {incidents[0].get('impact')}"
            return self.json({
                "answer": f"Short answer: {decision.get('title')} happened because FreshCart needed to turn scattered operational pain into a durable architecture choice. {decision.get('finalDecision')}{incident_text}",
                "whyItMattered": decision.get("reasons", [])[:3],
                "tradeoffs": ["FreshCart accepted more operational complexity to improve scalability, reliability, and traceability."],
                "citations": [{"type": "Decision", "id": decision.get("id"), "title": decision.get("title")}],
                "confidence": "medium",
            })
        if self.path == "/api/import-simulate":
            name = body.get("name", "uploaded-memory.json")
            return self.json({
                "name": name,
                "status": "absorbed",
                "created": {"records": 8, "connections": 21, "people": 3, "projects": 2},
                "summary": "EchoMind identified a new incident, linked it to two projects, and connected the discussion participants to follow-up work.",
            })
        self.json({"error": "Not found"}, 404)

    def log_message(self, fmt, *args):
        print(fmt % args)


if __name__ == "__main__":
    print(f"EchoMind no-install demo running at http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
