"""Content-addressed nudger prompts used after a natural stall."""
from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class NudgerPrompt:
    label: str
    description: str
    prompt: str | None

    @property
    def id(self) -> str:
        if self.prompt is None:
            return self.label
        return sha256(self.prompt.encode()).hexdigest()


NUDGERS = [
    NudgerPrompt("none", "control: send nothing after a stall", None),
    NudgerPrompt("continue", "baseline: the shortest plausible nudge", "Please continue."),
    NudgerPrompt(
        "advanced",
        "continue when possible; ask and wait when a required fact is missing",
        "Review what remains unfinished. If you can do the next part with the tools "
        "and information already available, do it. If a necessary fact is missing, "
        "request it with <question>...</question> and wait for the reply. "
        "A guess is not a reply.",
    ),
]

NUDGERS_BY_LABEL = {nudger.label: nudger for nudger in NUDGERS}

NUDGERS_BY_ID = {nudger.id: nudger for nudger in NUDGERS}
