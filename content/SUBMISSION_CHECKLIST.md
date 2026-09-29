# Submission checklist

## Project
- [ ] Push this folder to a public GitHub repo (`pagermind`)
- [ ] Add `.env` locally only (it's git-ignored): `GROQ_API_KEY`, `HINDSIGHT_URL`, `HINDSIGHT_API_KEY` (Cloud; promo code MEMHACK99 in Billing after sign-up)
- [ ] `python -m scripts.seed_memory` against real Hindsight, then run `python -m scripts.demo` once
- [ ] Re-take `docs/console.png` with real Hindsight + Groq (the status bar should say `HindsightMemory`)
- [ ] Paste the real "with memory" output into the article's before/after section if it differs
- [ ] Hindsight explanation: `HINDSIGHT_MEMORY.md` (link it in the submission form)

## Article (each team member)
- [ ] Publish `content/article.md` on Medium / Dev.to / Hashnode / LinkedIn Articles (public URL)
- [ ] Upload `docs/console.png` and `docs/architecture.png`, and fix the image paths for the platform
- [ ] Check that the 3 links are present: Hindsight GitHub, Hindsight docs, vectorize.io/what-is-agent-memory
- [ ] Submit as a Link post to r/llmdevs, r/sideproject, r/aiagents or r/aimemory
- [ ] Tag Code.in if you used it
- [ ] Each member writes from a different angle (for example: memory design · tool-call resilience · UI/demo)

## LinkedIn post (each team member)
- [ ] Post `content/linkedin_post.md` with the GitHub link in the body
- [ ] First comment: article URL · second comment: https://github.com/vectorize-io/hindsight

## Video (one per team)
- [ ] Record 2–5 min at 1080p using `content/video_script.md`
- [ ] Thumbnail from `content/thumbnail_prompt.md` (Nano Banana)
- [ ] Upload to YouTube as a public video

## Rule check
- [ ] The word "hackathon" does not appear in the article, post, hashtags or video title
