from pathlib import Path

ROOT = Path(__file__).resolve().parent

REQUIRED_CORE_RULES = [
    "ICT / Smart Money Concepts",
    "H1",
    "M15",
    "M5",
    "liquidity sweep",
    "displacement",
    "market structure shift",
    "CANDIDATE → ACTIVE → APPROACH → ENTRY_READY",
    "do not invent",
    "WAIT",
    "confluence",
]

FORBIDDEN_CONFLICTS = [
    "fixed $50 risk",
    "fixed $1 SL buffer",
    "automatically upgrade WAIT to APPROACH",
    "always risk 1%",
]


def read(path: str) -> str:
    file = ROOT / path
    assert file.exists(), f"missing prompt file: {path}"
    return file.read_text(encoding="utf-8").lower()


def test_github_prompt_contains_core_rules():
    github_prompt = read("prompts/scalper.txt")
    for rule in REQUIRED_CORE_RULES:
        assert rule.lower() in github_prompt, f"GitHub prompt missing: {rule}"


def test_cloudflare_prompt_contains_core_rules():
    cloudflare_prompt = read("cloudflare/chat_prompt.md")
    for rule in ["verified structured evidence", "do not upgrade", "do not invent", "stale"]:
        assert rule.lower() in cloudflare_prompt, f"Cloudflare prompt missing: {rule}"


def test_no_conflicting_fixed_risk_language():
    for path in ["prompts/scalper.txt", "cloudflare/chat_prompt.md"]:
        prompt = read(path)
        for phrase in FORBIDDEN_CONFLICTS:
            assert phrase.lower() not in prompt, f"conflicting phrase found in {path}: {phrase}"
