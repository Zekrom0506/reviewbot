# Interview notes

Short answers to the questions this project usually gets, with pointers into the code.

**Walk me through what happens when a PR is opened.**
GitHub sends a `pull_request` webhook. The receiver checks the HMAC-SHA256 signature (`signature.py`), turns the event into a job (`webhooks.py`) and puts it on SQS, then answers right away. A worker takes the job (`jobs.py` → `github_review.py`). It gets an installation token by signing a JWT with the App's private key, downloads the diff and the changed files, and runs the pipeline (`pipeline.py`). Then it posts one review with a summary, inline comments and a risk label, and saves everything to DynamoDB.

**Why not just send the diff to an LLM?**
Three reasons:
1. Static analysis catches concrete issues deterministically and cheaply. Passing those findings in as hints grounds the LLM.
2. Without retrieval, the model can't see callers or conventions, so it writes generic advice.
3. Raw LLM output is noisy. The filter keeps only confident comments on real diff lines and caps them at 5.

**How do you stop hallucinated line numbers?**
The diff is rendered with new-file line numbers on every line (`FileDiff.to_text`). Any comment whose line is not inside the diff is dropped (`filtering.py`), so GitHub never rejects the review. If GitHub still rejects it, the summary is posted without inline comments.

**How does retrieval work?**
Python files are split into one chunk per function with `ast`; other languages use 40-line windows. Chunks are embedded with FastEmbed (bge-small, 384 dimensions) and stored in pgvector with an HNSW index. For each changed function, the worker:
- text-searches for `name(` to find callers and tests,
- runs a cosine-similarity search for similar code.

Indexing is incremental: only files whose git blob SHA changed are re-embedded.

**How do you measure quality?**
`eval/cases.py` holds 50 PRs against the sample repo: 40 with 42 seeded bugs and 10 clean. A bug counts as caught if a comment's line range, widened by 2 lines, covers the bug line. A false positive is any comment that covers no bug. The `--no-retrieval` flag runs an ablation that shows what retrieval adds. In production, the 👍/👎 reaction rate is the helpfulness metric.

**How do you control cost?**
- Routing: diffs under 150 changed lines with low heuristic risk go to the 20B model; the rest go to the 120B model.
- Caching: static analysis is cached per file blob SHA, and LLM output per chunk prompt hash, so an unrelated push re-reviews nothing that didn't change.
- Logging: cost is recorded per PR in INR from token usage.

**What happens when things fail?**
- The LLM client retries with exponential backoff and waits longer on 429s.
- If the LLM fails completely, the review still posts with the static findings (secrets are always reported).
- A crashing job is not deleted from SQS, so it is retried. After 3 failures it goes to the DLQ, which triggers a CloudWatch alarm.

**How does the bot learn from feedback?**
GitHub doesn't send webhooks for reactions, so a scheduled job polls reactions on the bot's comments from the last 30 days. Per repo and category, with at least 5 votes: under 40% 👍 raises the confidence bar by 0.1, over 80% lowers it by 0.05. The bar never drops below the repo's strictness setting.

**What would you do next?**
- Tree-sitter chunking for more languages
- Learned per-repo comment ranking
- Comment threads where the bot answers follow-up questions
- Keeping the index in S3 for a fully serverless deployment
