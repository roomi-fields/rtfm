# MRCR Retrieval Task

This working directory is an indexed conversation. The user's next message will
ask you to locate the **i-th occurrence of a specific kind of content** (e.g.
"the 6th short essay about distance") and return it with a required prefix.

## Your tools

You have access to the `rtfm` MCP server. The conversation turns are indexed
as files under `conv/` — each file is one turn (`0001_user.md`,
`0002_assistant.md`, ...). File names are zero-padded so alphabetical order
matches chronological order.

## Required workflow

1. Call `rtfm_search` with keywords from the user's request (e.g. topic +
   content type: `"distance essay"`). Use enough specificity to surface the
   target turns, not the many distractors.
2. Count matches **in file-name order** (lowest-numbered file = 1st occurrence).
3. Use `rtfm_expand` to read the full content of the i-th matching turn.
4. Copy the assistant's response verbatim from that turn.

## Output format (STRICT)

Your reply **must** be exactly:

    <random_string><verbatim content from the i-th matching turn>

- `<random_string>` is the 10-character code provided in the user's message.
- No preamble, no commentary, no markdown — start with the random_string and
  end when the verbatim content ends.
- Any deviation fails the grader.
