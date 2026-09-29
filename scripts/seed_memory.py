"""Seed the Hindsight memory bank with the team's incident history.

    python -m scripts.seed_memory
"""

from pagermind.config import settings
from pagermind.memory import build_memory
from pagermind.seed import seed

if __name__ == "__main__":
    mem = build_memory(settings)
    print(f"Seeding bank '{settings.bank_id}' via {type(mem).__name__} ...")
    n = seed(mem)
    print(f"Done: {n} documents retained. Hindsight consolidates observations in the background.")
