from .state import RetrievedChunk, Turn

REWRITE_SYSTEM_PROMPT = """You rewrite a user's latest question as a standalone search query for a \
database of research papers. Use the conversation to resolve pronouns and references ("it", \
"that method", "the second paper"). Keep the original meaning and add no new facts.

Respond with ONLY the rewritten query on a single line."""

SYNTHESIZE_SYSTEM_PROMPT = """You are a research assistant. Answer the user's question using ONLY \
the numbered source chunks below. Do not use outside knowledge. The conversation so far, if any, \
is only there to tell you what the question refers to - every claim must still be backed by a \
source chunk.

Write your answer as a list of short, single-claim sentences, one per line. Every line MUST end \
with a citation tag like [N], where N is the number of the source chunk that supports that \
sentence. If a sentence is backed by several chunks, list all the tags, e.g. [1][3]. If the \
chunks don't contain enough information to answer, say so in a single line citing the closest \
relevant chunk, e.g. "Not enough information in the retrieved papers. [1]"

Example output:
Transformers replace recurrence with self-attention. [2]
This removes the sequential bottleneck RNNs have during training. [2]
"""

CRITIQUE_SYSTEM_PROMPT = """You are a strict fact-checker. You will be given numbered source \
chunks and a numbered draft answer, where each answer line ends in a citation tag [N]. For each \
line, decide whether the cited chunk N actually supports the claim made on that line.

Respond with ONLY one line in exactly this format:
UNSUPPORTED: <comma-separated line numbers that are NOT supported, or "none">
"""


def _format_chunk_block(retrieved_chunks: list[RetrievedChunk]) -> str:
    return "\n\n".join(
        f"[{i + 1}] (paper: {c['paper_title']}) {c['text']}" for i, c in enumerate(retrieved_chunks)
    )


def _format_history(history: list[Turn]) -> str:
    return "\n".join(f"{'User' if t['role'] == 'user' else 'Assistant'}: {t['content']}" for t in history)


def build_rewrite_messages(question: str, history: list[Turn]) -> list[dict]:
    return [
        {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Conversation:\n{_format_history(history)}\n\nLatest question: {question}",
        },
    ]


def build_synthesize_messages(
    question: str,
    retrieved_chunks: list[RetrievedChunk],
    critique_notes: list[str] | None = None,
    history: list[Turn] | None = None,
) -> list[dict]:
    chunk_block = _format_chunk_block(retrieved_chunks)
    conversation = f"Conversation so far:\n{_format_history(history)}\n\n" if history else ""
    messages = [
        {"role": "system", "content": SYNTHESIZE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"{conversation}Question: {question}\n\nSource chunks:\n{chunk_block}",
        },
    ]
    if critique_notes:
        notes = "\n".join(f"- {n}" for n in critique_notes)
        messages.append(
            {
                "role": "user",
                "content": (
                    "Your previous answer had unsupported claims. Revise it, keeping the same "
                    f"one-sentence-per-line [N] format, and fix these issues:\n{notes}"
                ),
            }
        )
    return messages


def build_critique_messages(retrieved_chunks: list[RetrievedChunk], draft_answer: str) -> list[dict]:
    chunk_block = _format_chunk_block(retrieved_chunks)
    lines = draft_answer.strip().splitlines()
    numbered_draft = "\n".join(f"{i + 1}. {line}" for i, line in enumerate(lines))
    return [
        {"role": "system", "content": CRITIQUE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Source chunks:\n{chunk_block}\n\nDraft answer:\n{numbered_draft}",
        },
    ]
