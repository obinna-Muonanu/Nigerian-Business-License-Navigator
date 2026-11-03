"""
It creates the Amazon Bedrock Guardrail that protects Navi from prompt-injection attacks. You run it once.

A prompt-injection attack is a message that tries to give Navi new instructions instead of asking a real question,
like "ignore your rules", "you are now in developer mode" or "print your system prompt". Bedrock Guardrails has a
filter trained to recognise these in any wording, which is far more reliable than a list of suspicious phrases.

The guardrail only switches on that one filter, the "prompt attack" filter, at its strictest setting. Nothing else
is filtered, so genuine business questions (in English or Pidgin) are never blocked for their topic. The script then
publishes a fixed version of the guardrail and prints the two settings to copy into .env.

Running it again is safe: if the guardrail already exists, it's reused instead of created twice.

HOW TO RUN IT
    python -m scripts.create_guardrail
"""

from agent.llm.bedrock import _boto_session

NAME = "license-navigator-prompt-attack"
# Shown only if a guardrail is ever attached to a model call directly; Navi's own refusal text lives in
# agent/llm/guardrail.py. Bedrock requires these fields when creating a guardrail.
BLOCKED_MESSAGE = "Sorry, I can't help with that request. I can help with business registration and licensing."


def main() -> None:
    client = _boto_session().client("bedrock")

    # Reuse the guardrail if it was created before, so running this twice doesn't make a second one.
    existing = [g for g in client.list_guardrails(maxResults=100).get("guardrails", []) if g["name"] == NAME]
    if existing:
        guardrail_id = existing[0]["id"]
        print(f"Guardrail '{NAME}' already exists ({guardrail_id}).")
    else:
        created = client.create_guardrail(
            name=NAME,
            description="Blocks prompt-injection and jailbreak attempts in messages sent to Navi.",
            # PROMPT_ATTACK is the only filter switched on. It checks the user's input at HIGH strength; Bedrock
            # requires its output strength to be NONE, because it only makes sense for input.
            contentPolicyConfig={"filtersConfig": [
                {"type": "PROMPT_ATTACK", "inputStrength": "HIGH", "outputStrength": "NONE"},
            ]},
            blockedInputMessaging=BLOCKED_MESSAGE,
            blockedOutputsMessaging=BLOCKED_MESSAGE,
        )
        guardrail_id = created["guardrailId"]
        print(f"Created guardrail '{NAME}' ({guardrail_id}).")

    # Publish a numbered version. The app uses a fixed version, so editing the guardrail in the AWS console later
    # can't silently change how the live app behaves until you choose to switch versions.
    versions = [g["version"] for g in client.list_guardrails(guardrailIdentifier=guardrail_id).get("guardrails", [])
                if g["version"] != "DRAFT"]
    version = max(versions, key=int) if versions else client.create_guardrail_version(
        guardrailIdentifier=guardrail_id, description="Prompt-attack filter at HIGH strength")["version"]

    print("\nAdd these two lines to your .env file:")
    print(f"GUARDRAIL_ID={guardrail_id}")
    print(f"GUARDRAIL_VERSION={version}")


if __name__ == "__main__":
    main()
