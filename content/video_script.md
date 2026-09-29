# Demo video script, about 3 minutes (Prompt 5)

Record at 1080p. Browser zoom 125%, terminal font 18pt+. Have the Hindsight control plane (http://localhost:9999) open in a second tab.

---

## 1. Intro (0:00–0:30)
**Screen:** you on camera, then the PagerMind console at `localhost:8000`.

> "Hi, I'm [YOUR NAME]. I built PagerMind, an on-call agent that remembers every outage your team has had, including the fixes that made things worse. It's built on Hindsight for memory and Groq for the model. Here's why that matters."

## 2. The problem (0:30–1:00)
**Screen:** click the `checkout-api` preset. Highlight the log line `pgbouncer: no more connections allowed`.

> "It's 2am. Checkout is throwing 18% errors right after a deploy. We've actually seen this three times this year. The answer is in three postmortems nobody reads at 2am."

**Screen:** click **Triage: without vs with memory** and point at the left panel.

> "Here's a normal stateless LLM. Check logs, restart the pods, scale up. Sounds fine. But restarting the pods is exactly what took this outage from 22% to 31% back in March."

## 3. Live demo (1:00–2:30)
**Screen:** right panel.

> "Same model, same prompt, memory on. It matches INC-2291 and INC-2602. The first step is the exact Argo rollback command, because our SRE lead told it once that she wants that first. And there's a 'Do NOT do' section: don't restart the pods, reconnect storm, with the incident number. It even knows to page Arjun, the DBA."

**Screen:** scroll to **Memories recalled**. Point at the type badges and `#service:payments-db`.

> "These are the memories Hindsight returned. Four recalls, scoped by service tags. Notice payments-db: the logs mention pgbouncer, so it pulled in the database team's history too."

**Screen:** open `pagermind/agent.py` at `gather_context` for about 5 seconds.

**Screen:** back in the console, go to **Close the loop**. Enter `set ANALYTICS_DB_POOL=0 via configmap`, choose **Did not work**, add the note "analytics engine ignores the env var", then click **Retain feedback**.

> "Now I tell it what happened tonight: I tried turning off the analytics pool with an env var and it didn't work. That's retained into Hindsight."

**Screen:** click **With memory only** again. Point at the new "Do NOT do" bullet.

> "Same alert again, and my failed attempt is now a warning. The next person on call won't waste those ten minutes."

**Screen:** in **Ask the team memory**, click **Reflect** on "What keeps breaking checkout-api?"

> "And reflect reasons over the whole history: pgbouncer exhaustion every time a deploy adds a DB pool. Fix the CI check permanently."

(Optional, 5 seconds: Hindsight control plane tab showing the bank's memories and observations.)

## 4. Takeaway (2:30–3:00)
**Screen:** back to camera or the README before/after table.

> "What surprised me: the biggest win wasn't the prompt or the model. It was storing 'did not work' as a first-class memory. Negative memory is the thing no wiki captures. Code's on GitHub, link below. Thanks!"

---

## Video titles
1. My AI On-Call Agent Remembers the Fix That Made Things Worse
2. Same LLM, Same Prompt, One Difference: Memory (Incident Response Demo)
3. I Gave My Pager Bot a Memory. It Stopped Saying "Restart the Pods"
4. Building an SRE Agent That Learns From Every Outage (Hindsight + Groq)
5. Stateless AI vs Agent Memory: A 2am Production Incident, Side by Side
