"""Official MRCR grader, ported from the openai/mrcr HuggingFace README.

Score = difflib.SequenceMatcher(None, response, answer).ratio() in [0, 1].
Hard constraint: the response must START with the random_string_to_prepend;
if the prefix is absent the score is forced to 0.
"""

from difflib import SequenceMatcher


def grade(response: str, answer: str, random_string: str) -> float:
    """Return the official MRCR score for a response against the gold answer.

    Args:
        response: Model's output text.
        answer: Gold answer string (already includes the random_string prefix).
        random_string: The 10-char code the model was required to prepend.
    """
    if not response.startswith(random_string):
        return 0.0
    return SequenceMatcher(None, response, answer).ratio()
