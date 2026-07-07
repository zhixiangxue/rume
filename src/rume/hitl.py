"""Human-in-the-Loop (HITL) handler for rume CLI.

Intercepts Bash tool calls and prompts the user for approval
before execution.
"""

from chak.tools.manager import HITLRequest, HITLDecision, HITLHandler


def create_hitl_handler(no_hitl: bool = False) -> HITLHandler | None:
    """Create a HITL handler for CLI interaction.

    Args:
        no_hitl: If True, auto-approve all tool calls (returns None).

    Returns:
        An async handler function, or None if HITL is disabled.
    """
    if no_hitl:
        return None

    async def handler(request: HITLRequest) -> HITLDecision:
        # Only intercept Bash calls; auto-approve others
        if request.tool_name != "bash":
            return HITLDecision.allow()

        cmd = request.arguments.get("cmd", "")
        working_dir = request.arguments.get("work_dir", "")

        print()
        print("┌" + "─" * 48 + "┐")
        print(f"│ 🔧 LLM wants to execute:".ljust(49) + "│")
        if working_dir:
            print(f"│    cwd: {working_dir}".ljust(49) + "│")
        # Truncate long commands for display
        display_cmd = cmd if len(cmd) <= 42 else cmd[:39] + "..."
        print(f"│    {display_cmd}".ljust(49) + "│")
        print("│".ljust(49) + "│")
        print("│ [y] allow  [n] deny  [e] edit  [?] info".ljust(49) + "│")
        print("└" + "─" * 48 + "┘")

        while True:
            try:
                answer = input("> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted by user.")
                return HITLDecision.abort()

            if answer in ("y", "yes", ""):
                return HITLDecision.allow()
            elif answer in ("n", "no"):
                return HITLDecision.abort()
            elif answer == "?":
                print(f"   Full command: {cmd}")
                print(f"   Arguments: {request.arguments}")
                continue
            elif answer.startswith("e ") or answer == "e":
                if answer == "e":
                    try:
                        new_cmd = input("   New command: ").strip()
                    except (EOFError, KeyboardInterrupt):
                        return HITLDecision.abort()
                else:
                    new_cmd = answer[2:].strip()
                if new_cmd:
                    return HITLDecision.allow(overrides={"cmd": new_cmd})
                continue
            else:
                print("   Invalid input. [y] allow, [n] deny, [e] edit, [?] info")
                continue

    return handler
