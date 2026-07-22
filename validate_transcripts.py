
import argparse
import os
import csv

# --- Format A markers ---
USER_MARKER = "<<<USER_TURN>>>"
LLM_MARKER = "<<<LLM_TURN>>>"

# --- Legacy Format A markers (informational only, no longer enforced) ---
BEGIN_MARKER = "BEGIN_LLM_TRANSCRIPT_"
END_MARKER = "END_LLM_TRANSCRIPT_"
CONTINUED_MARKER = "CONTINUED_IN_NEXT_RESPONSE"

# --- Format B labels (kept in sync with the Qualtrics v9 validator) ---
STUDENT_LABELS = [
    "User", "You", "Me", "I", "Student", "Human", "Prompt",
    "אני", "משתמש", "סטודנט", "פרומפט שלי", "פרומפט",
]

# "Answer" is deliberately NOT here - it appears as a section header
# inside model prose and causes false passes.
MODEL_LABELS = [
    "ChatGPT", "Chat GPT", "GPT", "Chat", "Gemini", "Claude", "Copilot",
    "Model", "Assistant", "AI assistant", "Math tutor", "Bot", "AI", "Response",
    "מודל", "מערכת", "בינה", "עוזר", "תשובה של Chat GPT",
]

STUDENT_LABELS.sort(key=len, reverse=True)
MODEL_LABELS.sort(key=len, reverse=True)

SEPARATORS = ":;：；"
DECORATION = "*_# >"
VERBS = ["said", "says", "wrote", "אמר", "אמרה", "אמרתי", "כתב", "כתבה"]

ARTIFACT_SUBSTRINGS = [
    "expand to view model thoughts",
    "chevron_right",
    "powered by gemini exporter",
    "ai-chat-exporter.com",
    "show thinking", "hide thinking",
    "regenerate response", "copy code",
    "thumb_up", "thumb_down", "content_copy", "more_vert",
]

ARTIFACT_LINES = ["thinking", "thinking:", "thoughts", "thoughts:", "reasoning"]

ARTIFACT_PREFIXES = [
    "link: https://gemini.google.com",
    "link: https://chatgpt.com",
    "link: https://chat.openai.com",
    "exported:",
]

ARTIFACT_MESSAGE = ("the file looks like a raw copy of the chat interface, "
                    "not the reformatted transcript")

MIN_TOTAL_TURNS = 2


# ---------------------------------------------------------------------------
# Step 1: Load the file
# ---------------------------------------------------------------------------

def load_file_text(filepath):
    """
    Try to read the file as text.

    Returns:
        (text, reason)
        text   -> the decoded string (never None, may be "" if unreadable)
        reason -> None if fully clean, otherwise a short string explaining
                  what was wrong (e.g. "not a text file", "bad encoding").

    Kept lenient on purpose (unlike the Qualtrics JS side): tries utf-8-sig
    and windows-1255 in addition to utf-8, and falls back to a lenient
    decode with errors="replace" so a batch scan can still report on a
    misencoded file instead of skipping it.
    """
    try:
        with open(filepath, "rb") as f:
            raw_bytes = f.read()
    except Exception as e:
        return "", f"could not open file: {e}"

    if len(raw_bytes) == 0:
        return "", "file is empty"

    for encoding in ("utf-8-sig", "utf-8", "windows-1255"):
        try:
            return raw_bytes.decode(encoding), None
        except UnicodeDecodeError:
            continue

    # Nothing worked cleanly -> decode leniently so other checks can still run.
    text = raw_bytes.decode("utf-8", errors="replace")
    return text, "bad encoding (could not cleanly decode file)"


# ---------------------------------------------------------------------------
# Step 2: Artifact / raw chat-UI dump detection (hard-fail, matches v9)
# ---------------------------------------------------------------------------

def clean_line(line):
    return line.strip().strip(DECORATION).strip()


def find_artifacts(text):
    low_all = text.lower()
    found = []

    for s in ARTIFACT_SUBSTRINGS:
        if s in low_all:
            found.append(s)

    bare_thinking = 0
    for line in text.splitlines():
        s = clean_line(line).lower()
        if s in ARTIFACT_LINES:
            bare_thinking += 1
        for p in ARTIFACT_PREFIXES:
            if s.startswith(p):
                found.append(p)

    if bare_thinking >= 2:
        found.append("model thinking/reasoning blocks")

    return sorted(set(found))


# ---------------------------------------------------------------------------
# Step 3: Format B label matching (matches v9's matches_label logic)
# ---------------------------------------------------------------------------

def strip_turn_prefix(low):
    if not low.startswith("turn"):
        return low
    rest = low[4:].lstrip()
    digits = 0
    while digits < len(rest) and rest[digits].isdigit():
        digits += 1
    if digits == 0:
        return low
    rest = rest[digits:].lstrip()
    if rest[:1] in (":", ".", ")", "-"):
        rest = rest[1:].lstrip()
    return rest


def matches_label(cleaned, labels):
    low = strip_turn_prefix(cleaned.lower().strip())
    if not low:
        return False

    for label in labels:
        lab = label.lower()
        if not low.startswith(lab):
            continue

        rest = low[len(lab):].strip()

        if rest == "":
            return True
        if rest[0] in SEPARATORS:
            return True
        for verb in VERBS:
            if rest.startswith(verb):
                after = rest[len(verb):].strip()
                if after == "" or after[0] in SEPARATORS:
                    return True

    return False


def find_label_lines(text):
    """
    Returns a list of (category, line_index) tuples, in the order the
    labels appear, where category is "student" or "model".
    """
    label_lines = []
    for i, line in enumerate(text.splitlines()):
        cleaned = clean_line(line)
        if not cleaned:
            continue
        if matches_label(cleaned, STUDENT_LABELS):
            label_lines.append(("student", i))
        elif matches_label(cleaned, MODEL_LABELS):
            label_lines.append(("model", i))
    return label_lines


# ---------------------------------------------------------------------------
# Step 4: Individual checks
# Each check takes the file's text and returns (passed: bool, reason: str|None)
# ---------------------------------------------------------------------------

def check_not_empty(text):
    if text.strip() == "":
        return False, "file is empty or whitespace-only"
    return True, None


# --- Format A: hard-fail checks (match v9) ---

def check_has_user_marker(text):
    if text.count(USER_MARKER) == 0:
        return False, f"no '{USER_MARKER}' markers found"
    return True, None


def check_has_llm_marker(text):
    if text.count(LLM_MARKER) == 0:
        return False, f"no '{LLM_MARKER}' markers found"
    return True, None


# --- Format B: hard-fail checks (match v9) ---

def check_has_student_label(text):
    if not any(cat == "student" for cat, _ in find_label_lines(text)):
        return False, "no known student label found (e.g. 'User:', 'אני:')"
    return True, None


def check_has_model_label(text):
    if not any(cat == "model" for cat, _ in find_label_lines(text)):
        return False, "no known model label found (e.g. 'ChatGPT:', 'Gemini:')"
    return True, None


CHECKS_FORMAT_A = [check_has_user_marker, check_has_llm_marker]
CHECKS_FORMAT_B = [check_has_student_label, check_has_model_label]


# --- Legacy checks: informational only, do NOT affect pass/fail ---
# These were hard-fail checks in v0, but the Qualtrics v9 validator
# deliberately dropped them (empty turns and consecutive same-speaker
# turns are allowed on purpose; begin/end/continued markers were an
# earlier scheme that's no longer part of the format). Kept here as
# signal for manually reviewing a batch, not as gating logic.

def check_has_begin_marker(text):
    if BEGIN_MARKER not in text:
        return False, f"missing '{BEGIN_MARKER}N' marker"
    return True, None


def check_has_end_marker(text):
    if END_MARKER not in text:
        return False, f"missing '{END_MARKER}N' marker"
    return True, None


def check_turns_alternate(text):
    markers_in_order = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == USER_MARKER:
            markers_in_order.append("USER")
        elif stripped == LLM_MARKER:
            markers_in_order.append("LLM")

    if not markers_in_order:
        return False, "no turn markers found to check alternation"

    for i in range(1, len(markers_in_order)):
        if markers_in_order[i] == markers_in_order[i - 1]:
            return False, f"turns do not alternate (two '{markers_in_order[i]}' in a row)"

    return True, None


def check_no_empty_turns(text):
    lines = text.splitlines()
    marker_line_indices = [
        i for i, line in enumerate(lines)
        if line.strip() in (USER_MARKER, LLM_MARKER)
    ]

    for pos, line_idx in enumerate(marker_line_indices):
        next_marker_idx = (
            marker_line_indices[pos + 1]
            if pos + 1 < len(marker_line_indices)
            else len(lines)
        )
        content_lines = lines[line_idx + 1:next_marker_idx]
        content = "\n".join(content_lines).strip()
        if content == "":
            return False, f"empty turn found after '{lines[line_idx].strip()}' (line {line_idx + 1})"

    return True, None


def check_no_unresolved_continuation(text):
    if CONTINUED_MARKER not in text:
        return True, None

    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count < 2 or end_count < 2 or begin_count != end_count:
        return False, "'CONTINUED_IN_NEXT_RESPONSE' found but no matching follow-up transcript block"

    return True, None


def check_min_turn_count(text):
    total_turns = text.count(USER_MARKER) + text.count(LLM_MARKER)
    if total_turns < MIN_TOTAL_TURNS:
        return False, f"only {total_turns} turn(s) found, expected at least {MIN_TOTAL_TURNS}"
    return True, None


def check_labels_alternate(text):
    categories = [cat for cat, _ in find_label_lines(text)]

    if not categories:
        return False, "no labels found to check alternation"

    for i in range(1, len(categories)):
        if categories[i] == categories[i - 1]:
            return False, f"labels do not alternate (two '{categories[i]}' turns in a row)"

    return True, None


def check_no_empty_turns_b(text):
    lines = text.splitlines()
    label_lines = find_label_lines(text)

    for pos, (category, line_idx) in enumerate(label_lines):
        next_label_idx = (
            label_lines[pos + 1][1]
            if pos + 1 < len(label_lines)
            else len(lines)
        )

        raw_line = clean_line(lines[line_idx])
        same_line_content = ""
        for sep in SEPARATORS:
            if sep in raw_line:
                same_line_content = raw_line.split(sep, 1)[1].strip()
                break

        following_lines = lines[line_idx + 1:next_label_idx]
        content = (same_line_content + "\n" + "\n".join(following_lines)).strip()
        if content == "":
            return False, f"empty turn found after label on line {line_idx + 1}"

    return True, None


def check_min_turn_count_b(text):
    total_turns = len(find_label_lines(text))
    if total_turns < MIN_TOTAL_TURNS:
        return False, f"only {total_turns} turn(s) found, expected at least {MIN_TOTAL_TURNS}"
    return True, None


INFO_CHECKS_FORMAT_A = [
    check_has_begin_marker,
    check_has_end_marker,
    check_turns_alternate,
    check_no_empty_turns,
    check_no_unresolved_continuation,
    check_min_turn_count,
]

INFO_CHECKS_FORMAT_B = [
    check_labels_alternate,
    check_no_empty_turns_b,
    check_min_turn_count_b,
]


# ---------------------------------------------------------------------------
# Step 5: Decide which format a file matches (matches v9's detect_format)
# ---------------------------------------------------------------------------

def detect_format(text):
    """
    Returns "A", "B", or "unrecognized".
    """
    if USER_MARKER in text or LLM_MARKER in text:
        return "A"

    if find_label_lines(text):
        return "B"

    return "unrecognized"


# ---------------------------------------------------------------------------
# Step 6: Run all checks on one file
# ---------------------------------------------------------------------------

def validate_file(filepath):
    """
    Runs the full validation pipeline on a single file.

    Returns a dict:
        {
            "filename": str,
            "format": "A" | "B" | "raw-dump" | "unrecognized",
            "passed": bool,
            "failed_checks": [str, ...],   # hard-fail reasons (mirrors v9)
            "info_flags": [str, ...],      # legacy checks, informational only
        }
    """
    filename = os.path.basename(filepath)
    failed_checks = []
    info_flags = []

    text, load_reason = load_file_text(filepath)
    if load_reason:
        failed_checks.append(load_reason)

    not_empty_passed, not_empty_reason = check_not_empty(text)
    if not not_empty_passed:
        failed_checks.append(not_empty_reason)
        return {
            "filename": filename,
            "format": "unrecognized",
            "passed": False,
            "failed_checks": failed_checks,
            "info_flags": info_flags,
        }

    # Raw chat-UI/export-tool dumps are checked first, before format
    # detection - matches v9's ordering.
    artifacts = find_artifacts(text)
    if artifacts:
        return {
            "filename": filename,
            "format": "raw-dump",
            "passed": False,
            "failed_checks": failed_checks + [ARTIFACT_MESSAGE] + artifacts,
            "info_flags": info_flags,
        }

    file_format = detect_format(text)

    if file_format == "unrecognized":
        failed_checks.append("unrecognized format: no known markers or labels found")
        return {
            "filename": filename,
            "format": "unrecognized",
            "passed": False,
            "failed_checks": failed_checks,
            "info_flags": info_flags,
        }

    checks = CHECKS_FORMAT_A if file_format == "A" else CHECKS_FORMAT_B
    for check_fn in checks:
        passed, reason = check_fn(text)
        if not passed:
            failed_checks.append(reason)

    info_checks = INFO_CHECKS_FORMAT_A if file_format == "A" else INFO_CHECKS_FORMAT_B
    for check_fn in info_checks:
        passed, reason = check_fn(text)
        if not passed:
            info_flags.append(reason)

    return {
        "filename": filename,
        "format": file_format,
        "passed": len(failed_checks) == 0,
        "failed_checks": failed_checks,
        "info_flags": info_flags,
    }


# ---------------------------------------------------------------------------
# Step 7: Run over a whole folder + write a report
# ---------------------------------------------------------------------------

def validate_folder(folder_path):
    results = []
    for filename in sorted(os.listdir(folder_path)):
        if not filename.lower().endswith(".txt"):
            continue
        filepath = os.path.join(folder_path, filename)
        results.append(validate_file(filepath))
    return results


def write_report(results, output_csv_path):
    with open(output_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "status", "format", "failed_checks", "info_flags"])
        for r in results:
            status = "pass" if r["passed"] else "fail"
            writer.writerow([
                r["filename"],
                status,
                r["format"],
                "; ".join(r["failed_checks"]),
                "; ".join(r["info_flags"]),
            ])


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate student-submitted transcript .txt files in a folder."
    )
    parser.add_argument("input_folder", help="Path to the folder of raw .txt transcript files")
    parser.add_argument(
        "-o", "--output",
        default="validation_report.csv",
        help="Path to write the CSV report (default: validation_report.csv)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    results = validate_folder(args.input_folder)
    write_report(results, args.output)

    passed = [r for r in results if r["passed"]]
    failed = [r for r in results if not r["passed"]]

    print(f"Checked {len(results)} files.")
    print(f"  Passed: {len(passed)}")
    print(f"  Failed: {len(failed)}")
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()