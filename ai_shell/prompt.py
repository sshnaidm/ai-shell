from ai_shell.output import OutputFormat


def build_prompt(
    question: str,
    context: str | None,
    *,
    output_format: OutputFormat = OutputFormat.markdown,
    prompt_instructions: bool = True,
) -> str:
    instructions = ""
    if prompt_instructions and output_format == OutputFormat.terminal:
        instructions = (
            "The answer will be displayed in a terminal using a Markdown renderer. "
            "Be concise and use simple Markdown for emphasis, lists, and fenced code "
            "blocks with language names. Use inline links. Do not output ANSI escape "
            "sequences or HTML; terminal colors are applied by the renderer.\n\n"
        )
    elif prompt_instructions and output_format == OutputFormat.plain:
        instructions = (
            "Answer in plain text for a terminal. Be concise. Do not use Markdown "
            "formatting, code fences, HTML, or ANSI escape sequences. Put commands "
            "on their own lines so they can be copied directly.\n\n"
        )
    if not context:
        return instructions + question
    return instructions + (
        "I am a developer working in a Linux terminal.\n"
        "Here is the recent output from my terminal:\n"
        "```\n"
        f"{context}\n"
        "```\n"
        f"My Question: {question}\n"
    )
