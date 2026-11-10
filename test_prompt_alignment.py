"""Static prompt text contract checks only; these do not evaluate model understanding."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED_CORE_RULES = [
    "ICT / Smart Money Concepts", "H1", "M15", "M5",
    "liquidity sweep", "displacement", "market structure shift",
    "CANDIDATE → ACTIVE → APPROACH → ENTRY_READY",
    "do not invent", "WAIT", "confluence",
]
FORBIDDEN_CONFLICTS = [
    "fixed $50 risk", "fixed $1 SL buffer",
    "automatically upgrade WAIT to APPROACH", "always risk 1%",
]

def read(path: str) -> str:
    file = ROOT / path
    assert file.exists(), f"missing prompt file: {path}"
    return file.read_text(encoding="utf-8").lower()

def test_github_prompt_contains_core_rules():
    prompt = read("prompts/scalper.txt")
    for rule in REQUIRED_CORE_RULES:
        assert rule.lower() in prompt, f"GitHub prompt missing: {rule}"

def test_cloudflare_prompt_contains_core_rules():
    prompt = read("cloudflare/chat_prompt.md")
    rules = [
        "latest verified structured report",
        "do not create, upgrade, or downgrade market status.",
        "do not turn wait into approach or entry_ready.",
        "do not invent", "stale",
    ]
    for rule in rules:
        assert rule in prompt, f"Cloudflare prompt missing: {rule}"

def test_no_conflicting_fixed_risk_language():
    for path in ["prompts/scalper.txt", "cloudflare/chat_prompt.md"]:
        prompt = read(path)
        for phrase in FORBIDDEN_CONFLICTS:
            assert phrase.lower() not in prompt, f"conflicting phrase found in {path}: {phrase}"
