"""
Pre-proccessing Transcript file validation pipeline (v0)

Goal:
    Given a folder of student-submitted .txt files, flag which ones are
    usable (pass all checks) and which are faulty (fail one or more checks),
    along with WHY they failed.
"""

import argparse
import os
import csv

# --- Format A markers ---
USER_MARKER = "<<<USER_TURN>>>"
LLM_MARKER = "<<<LLM_TURN>>>"
BEGIN_MARKER = "BEGIN_LLM_TRANSCRIPT_"
END_MARKER = "END_LLM_TRANSCRIPT_"
CONTINUED_MARKER = "CONTINUED_IN_NEXT_RESPONSE"

# --- Format B labels ---
STUDENT_LABELS = ["User", "You", "You said", "אני", "משתמש", "סטודנט"]
MODEL_LABELS = ["ChatGPT", "ChatGPT said", "Gemini", "Model", "Assistant", "Chat", "מודל"]

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
# Step 2: Individual checks
# Each check takes the file's text and returns (passed: bool, reason: str|None)
# ---------------------------------------------------------------------------

def check_not_empty(text):
    if text.strip() == "":
        return False, "file is empty or whitespace-only"
    return True, None


# --- Format A checks ---

def check_has_begin_marker(text):
    if BEGIN_MARKER not in text:
        return False, f"missing '{BEGIN_MARKER}N' marker"
    return True, None


def check_has_end_marker(text):
    if END_MARKER not in text:
        return False, f"missing '{END_MARKER}N' marker"
    return True, None


def check_has_user_marker(text):
    if text.count(USER_MARKER) == 0:
        return False, f"no '{USER_MARKER}' markers found"
    return True, None


def check_has_llm_marker(text):
    if text.count(LLM_MARKER) == 0:
        return False, f"no '{LLM_MARKER}' markers found"
    return True, None


def check_turns_alternate(text):
    """
    Walk through the markers in the order they appear and make sure they
    alternate USER, LLM, USER, LLM, ... (two of the same type in a row
    means a turn is likely missing or duplicated).
    """
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
    """
    Make sure there's actual content between each marker and the next one.
    """
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
    """
    If the model said it would continue, make sure a follow-up transcript
    block actually exists in the file.
    """
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


# --- Format B checks ---

def line_starts_with_label(stripped_line, label):
    """
    Checks whether stripped_line starts with the given.
    """
    lower_line = stripped_line.lower()
    lower_label = label.lower()

    if not lower_line.startswith(lower_label):
        return None

    # Everything right after the label itself.
    rest = stripped_line[len(label):]
    rest_stripped_of_one_space = rest[1:] if rest.startswith(" ") else rest

    if rest_stripped_of_one_space.startswith(":"):
        used_space = 1 if rest.startswith(" ") else 0
        return len(label) + used_space + 1  # + 1 for the colon itself

    return None


def find_label_lines(text):
    """
    Walk through the file and find every line that STARTS WITH a known
    student or model label followed by ':' 

    Returns a list of (category, line_index, label_length) tuples, in the
    order the labels appear, where:
        category     is "student" or "model"
        label_length is how many characters of the STRIPPED line are the
                      label + colon (so callers can grab whatever comes
                      after it on that same line as same-line content).
    """
    label_lines = []
    for i, line in enumerate(text.splitlines()):
        stripped = line.strip()

        matched_length = None
        category = None
        for label in STUDENT_LABELS:
            matched_length = line_starts_with_label(stripped, label)
            if matched_length is not None:
                category = "student"
                break
        if matched_length is None:
            for label in MODEL_LABELS:
                matched_length = line_starts_with_label(stripped, label)
                if matched_length is not None:
                    category = "model"
                    break

        if matched_length is not None:
            label_lines.append((category, i, matched_length))

    return label_lines


def check_has_student_label(text):
    label_lines = find_label_lines(text)
    if not any(category == "student" for category, _, _ in label_lines):
        return False, "no known student label found (e.g. 'User:')"
    return True, None


def check_has_model_label(text):
    label_lines = find_label_lines(text)
    if not any(category == "model" for category, _, _ in label_lines):
        return False, "no known model label found (e.g. 'Gemini:')"
    return True, None


def check_labels_alternate(text):
    label_lines = find_label_lines(text)
    categories = [category for category, _, _ in label_lines]

    if not categories:
        return False, "no labels found to check alternation"

    for i in range(1, len(categories)):
        if categories[i] == categories[i - 1]:
            return False, f"labels do not alternate (two '{categories[i]}' turns in a row)"

    return True, None


def check_no_empty_turns_b(text):
    lines = text.splitlines()
    label_lines = find_label_lines(text)

    for pos, (category, line_idx, label_length) in enumerate(label_lines):
        next_label_idx = (
            label_lines[pos + 1][1]
            if pos + 1 < len(label_lines)
            else len(lines)
        )

        stripped_label_line = lines[line_idx].strip()
        same_line_content = stripped_label_line[label_length:].strip()
        following_lines = lines[line_idx + 1:next_label_idx]

        content = (same_line_content + "\n" + "\n".join(following_lines)).strip()
        if content == "":
            label_text = stripped_label_line[:label_length]
            return False, f"empty turn found after '{label_text}' (line {line_idx + 1})"

    return True, None


def check_min_turn_count_b(text):
    label_lines = find_label_lines(text)
    total_turns = len(label_lines)
    if total_turns < MIN_TOTAL_TURNS:
        return False, f"only {total_turns} turn(s) found, expected at least {MIN_TOTAL_TURNS}"
    return True, None


# --- Check registries, one per format ---

CHECKS_FORMAT_A = [
    check_has_begin_marker,
    check_has_end_marker,
    check_has_user_marker,
    check_has_llm_marker,
    check_turns_alternate,
    check_no_empty_turns,
    check_no_unresolved_continuation,
    check_min_turn_count,
]

CHECKS_FORMAT_B = [
    check_has_student_label,
    check_has_model_label,
    check_labels_alternate,
    check_no_empty_turns_b,
    check_min_turn_count_b,
]


# ---------------------------------------------------------------------------
# Step 2b: Decide which format a file matches
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
# Step 3: Run all checks on one file
# ---------------------------------------------------------------------------

def validate_file(filepath):
    """
    Runs the full validation pipeline on a single file.

    Returns a dict:
        {
            "filename": str,
            "format": "A" | "B" | "unrecognized",
            "passed": bool,
            "failed_checks": [str, ...]
        }
    """
    filename = os.path.basename(filepath)
    failed_checks = []

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
        }

    file_format = detect_format(text)

    if file_format == "unrecognized":
        failed_checks.append("unrecognized format: no known markers or labels found")
        return {
            "filename": filename,
            "format": "unrecognized",
            "passed": False,
            "failed_checks": failed_checks,
        }

    checks = CHECKS_FORMAT_A if file_format == "A" else CHECKS_FORMAT_B
    for check_fn in checks:
        passed, reason = check_fn(text)
        if not passed:
            failed_checks.append(reason)

    return {
        "filename": filename,
        "format": file_format,
        "passed": len(failed_checks) == 0,
        "failed_checks": failed_checks,
    }


# ---------------------------------------------------------------------------
# Step 4: Run over a whole folder + write a report
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
        writer.writerow(["filename", "status", "format", "failed_checks"])
        for r in results:
            status = "pass" if r["passed"] else "fail"
            writer.writerow([r["filename"], status, r["format"], "; ".join(r["failed_checks"])])


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
