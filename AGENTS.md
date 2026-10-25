# Contributor instructions

- Preserve the product flow: closed conversation → request summaries → persistent topic classification.
- Do not add an upper hierarchy as a mandatory analysis step. It can later be a separate relation.
- Keep model-server HTTP behind Generator/Embedder ports and persistence behind Repository.
- Do not persist per-request embedding vectors by default. Do not automatically delete or merge registered topic IDs.
- Topic registration and pending processing must be bounded. Never satisfy a topic cap by forcing semantically unrelated assignments.
- Keep public examples synthetic; do not add private conversations, model credentials, research PDFs, weights or external datasets without redistribution rights.
- Run appropriate offline tests. Distinguish mock provider tests, SQL compilation and live model/database verification in reports.
