"""
Travel Planner — the demo agent Nengok watches in the hackathon video.

The agent calls three mock tools (`flights`, `weather`, `hotels`) that
can have their failure modes toggled at runtime via `failure_modes.py`.
The demo flow is:

    1. Run the agent with all failure modes OFF -> traces look healthy.
    2. Flip the failure modes ON -> agent silently produces wrong plans.
    3. Run `nengok run` -> three clusters detected, one resolved end-to-end.
"""
