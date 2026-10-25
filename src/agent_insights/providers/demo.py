"""Explicit offline fixture mode. NOT a semantic model or quality benchmark."""


class DemoGenerator:
    def generate_json(self, system, payload):
        if "messages" in payload:
            facets = []
            for i, m in enumerate(payload["messages"]):
                if m["role"] == "customer":
                    text = m["text"].lower()
                    for name, words in [
                        ("Address change", ("address",)),
                        ("Card replacement", ("card",)),
                        ("Account balance", ("balance",)),
                    ]:
                        if any(w in text for w in words):
                            if not any(f["summary"] == name for f in facets):
                                facets.append({"summary": name, "evidence": [i]})
            return {"facets": facets[: payload.get("max_facets", 5)]}
        for t in payload.get("topics", []):
            if t["name"] == payload["summaries"][0]:
                return {
                    "action": "assign_existing",
                    "topic_id": t["id"],
                    "reason": "Offline fixture label match",
                }
        return {
            "action": "create",
            "name": payload["summaries"][0],
            "description": "Synthetic demonstration: " + payload["summaries"][0],
            "reason": "Offline fixture category",
        }


class DemoEmbedder:
    space_id = "offline-fixture-v1"

    def embed(self, texts):
        result = []
        for text in texts:
            vector = [0.0, 0.0, 0.0, 0.0]
            index = {"Address change": 0, "Card replacement": 1, "Account balance": 2}.get(text, 3)
            vector[index] = 1.0
            result.append(vector)
        return result
