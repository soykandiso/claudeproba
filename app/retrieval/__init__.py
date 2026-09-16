"""Retrieval over the official text of calls: chunk, embed, search.

docs/architecture.md §3.1 (chunker + embedder) and docs/matching.md §5 (hybrid
retrieval for the verification pass).

- chunker.py   normalised_text → overlapping spans with character offsets
- embedder.py  a local multilingual model; nothing is sent anywhere
- index.py     writes chunks for normalised snapshots and fills their embeddings
- search.py    vector and trigram rankings over one call's documents, fused

Chunks belong to a snapshot, not to a call: like normalised_text they are
written once and never rewritten, because evidence rows point at them. Which
chunks a call searches is decided at query time from call_document.
"""
