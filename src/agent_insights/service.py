import numpy as np

from .clustering import normalized
from .domain import Extraction, TopicDecision, TopicDescription
from .ports import Clusterer, Embedder, Generator, Repository

EXTRACT = """Extract independent customer requests from this CLOSED conversation.
Return {"facets":[{"summary":"specific request, omit private details",
"evidence":[zero-based CUSTOMER message indexes]}]}.
Do not extract greetings, identity verification, providing personal details or agent questions.
Keep requests distinct. Return an empty facets list if there is no substantive request.
Never include names, account numbers, exact addresses or other identifiers in summaries.
Respect max_facets from the payload. Use the conversation's language."""
DECIDE = """Review this temporary group against ALL registered topics.
Return {"action":"assign_existing|create|pending","topic_id":"existing ID or null",
"name":"short topic name for create","description":"scope for create","reason":"rationale"}.
Use assign_existing if ALL summaries fit an existing topic, including narrower examples.
City, person, date, product instance or wording differences do NOT justify a new topic.
Create only for a coherent, recurring substantive request not covered by any existing topic.
Choose pending for mixed, unclear or routine identity-verification groups. Do not include PII.
Do not rename, remove or merge any registered topic."""


class InsightService:
    def __init__(
        self,
        repository: Repository,
        generator: Generator,
        embedder: Embedder,
        clusterer: Clusterer,
        settings,
    ):
        self.repo, self.generator, self.embedder = repository, generator, embedder
        self.clusterer, self.settings = clusterer, settings

    def _registry(self, tenant, bot):
        result = self.repo.topics(tenant, bot)
        if any(t["space_id"] != self.embedder.space_id for t in result):
            raise ValueError("Embedding space changed; explicit topic prototype migration required")
        return result

    def process_one(self):
        s = self.settings
        job = self.repo.claim(s.lease_seconds, s.max_attempts)
        if job is None:
            return False
        try:
            registry = self._registry(job["tenant_id"], job["bot_id"])
            extraction = Extraction.model_validate(
                self.generator.generate_json(
                    EXTRACT, {"messages": job["messages"], "max_facets": s.max_facets_per_session}
                )
            )
            if len(extraction.facets) > s.max_facets_per_session:
                raise ValueError("Model exceeded facet budget")
            accepted, seen = [], set()
            for facet in extraction.facets:
                if any(
                    i < 0 or i >= len(job["messages"]) or job["messages"][i]["role"] != "customer"
                    for i in facet.evidence
                ):
                    raise ValueError("Model evidence did not refer to customer messages")
                key = facet.summary.casefold().strip()
                if key not in seen:
                    accepted.append(facet.model_dump())
                    seen.add(key)
            if accepted:
                vectors = normalized(self.embedder.embed([f["summary"] for f in accepted]))
                if len(vectors) != len(accepted):
                    raise ValueError("Embedding count mismatch")
                if registry:
                    centers = normalized([t["vector"] for t in registry])
                    if vectors.shape[1] != centers.shape[1]:
                        raise ValueError("Embedding dimensions changed")
                    scores = vectors @ centers.T
                    for facet, values in zip(accepted, scores):
                        order = np.argsort(values)[::-1]
                        best = float(values[order[0]])
                        margin = best - float(values[order[1]]) if len(order) > 1 else best
                        if best >= s.assignment_similarity and margin >= s.assignment_margin:
                            facet["topic_id"] = registry[int(order[0])]["id"]
            self.repo.finish(job, accepted)
        except Exception as exc:
            # Error class only: no prompts, raw model output or credentials in logs/storage.
            self.repo.fail(job, type(exc).__name__, s.max_attempts)
        return True

    def discover(self, tenant, bot):
        s = self.settings
        token = self.repo.acquire_discovery(tenant, bot, s.lease_seconds)
        if token is None:
            return {"status": "busy"}
        try:
            registry = self._registry(tenant, bot)
            pending = self.repo.pending(
                tenant, bot, s.pending_batch_size, s.pending_max_days, s.pending_max_reviews
            )
            if not pending:
                return {"status": "idle", "reviewed": 0}
            vectors = normalized(self.embedder.embed([p["summary"] for p in pending]))
            groups = self.clusterer.groups(vectors.tolist(), [p["id"] for p in pending])
            covered = [i for group in groups for i in group]
            if sorted(covered) != list(range(len(pending))):
                raise ValueError(
                    "Clusterer must partition every input exactly once, including noise"
                )
            decisions = []
            for group in groups:
                members = [pending[i] for i in group]
                decision = {"action": "pending", "facet_ids": [m["id"] for m in members]}
                if len({m["conversation_id"] for m in members}) >= s.min_sessions_per_topic:
                    payload = {
                        "summaries": [m["summary"] for m in members],
                        "topics": [
                            {
                                "id": t["id"],
                                "name": t["name"],
                                "description": t["description"][:400],
                            }
                            for t in registry
                        ],
                    }
                    proposed = TopicDecision.model_validate(
                        self.generator.generate_json(DECIDE, payload)
                    )
                    # Independent second novelty check before registering a new persistent topic.
                    if proposed.action == "create" and registry:
                        proposed = TopicDecision.model_validate(
                            self.generator.generate_json(
                                DECIDE
                                + " Recheck novelty conservatively; a narrower instance is existing.",
                                {**payload, "proposal": proposed.model_dump()},
                            )
                        )
                    if proposed.action == "assign_existing":
                        if proposed.topic_id not in {t["id"] for t in registry}:
                            raise ValueError("Model selected an unknown/out-of-scope topic")
                        decision.update(action="assign_existing", topic_id=proposed.topic_id)
                    elif proposed.action == "create":
                        description = TopicDescription(
                            name=proposed.name, description=proposed.description
                        )
                        duplicate = next(
                            (
                                t
                                for t in registry
                                if t["name"].casefold() == description.name.casefold()
                            ),
                            None,
                        )
                        staged = next(
                            (
                                d
                                for d in decisions
                                if d["action"] == "create"
                                and d["name"].casefold() == description.name.casefold()
                            ),
                            None,
                        )
                        if staged is not None:
                            # Same-batch duplicate labels share one registration and prototype.
                            staged["facet_ids"].extend(decision["facet_ids"])
                            continue
                        if duplicate:
                            decision.update(action="assign_existing", topic_id=duplicate["id"])
                        elif (
                            len(registry) + sum(d["action"] == "create" for d in decisions)
                            < s.max_topics_per_bot
                        ):
                            center = normalized([vectors[group].mean(axis=0)])[0].tolist()
                            decision.update(
                                action="create",
                                **description.model_dump(),
                                vector=center,
                                space_id=self.embedder.space_id,
                            )
                decisions.append(decision)
            result = self.repo.apply_discovery(tenant, bot, token, decisions, s.max_topics_per_bot)
            return {"status": "completed", **result}
        finally:
            self.repo.release_discovery(tenant, bot, token)
