"""
Anti-Wildcards Extension for Stable Diffusion Reforge
======================================================
antiwildcards.txt   — add/remove terms from the negative prompt
wildcard_combos.txt — inject combo terms into the positive prompt

Both files are searched recursively under the sd-dynamic-prompts wildcards folder.
All operations run in process_before_every_sampling so wildcard expansion has
already occurred before we touch the prompts.
"""

import os
import gradio as gr
from modules import scripts, shared

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
_THIS_FILE      = os.path.abspath(__file__)
_SCRIPTS_DIR    = os.path.dirname(_THIS_FILE)          # extensions/antiwildcards/scripts/
_EXT_DIR        = os.path.dirname(_SCRIPTS_DIR)        # extensions/antiwildcards/
_EXTENSIONS_DIR = os.path.dirname(_EXT_DIR)            # extensions/
WILDCARDS_DIR   = os.path.join(_EXTENSIONS_DIR, "sd-dynamic-prompts", "wildcards")


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_file_in_wildcards_dir(filename: str) -> str:
    """
    Recursively search WILDCARDS_DIR for a file matching filename
    (case-insensitive). Returns the full path of the first match, or a
    root-level fallback path if not found.
    """
    if not os.path.isdir(WILDCARDS_DIR):
        return os.path.join(WILDCARDS_DIR, filename)

    filename_lower = filename.lower()
    for root, dirs, files in os.walk(WILDCARDS_DIR):
        dirs.sort()
        for f in sorted(files):
            if f.lower() == filename_lower:
                return os.path.join(root, f)

    return os.path.join(WILDCARDS_DIR, filename)


# ---------------------------------------------------------------------------
# antiwildcards.txt loader
# ---------------------------------------------------------------------------

def load_antiwildcards(verbose: bool = False) -> tuple:
    """
    Parse antiwildcards.txt.

    Valid line formats (whitespace around separators is ignored):
      trigger /// negative addition      -> ADD rule
      trigger ////// term to remove      -> REMOVE rule

    Blank/placeholder lines and lines with empty triggers or values are skipped.
    Lines starting with '#' are comments.

    verbose=True prints each rule as it loads (used at startup summary only).
    """
    add_rules: list    = []
    remove_rules: list = []

    filepath = find_file_in_wildcards_dir("antiwildcards.txt")

    if not os.path.isfile(filepath):
        return add_rules, remove_rules

    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, 1):
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            if "///" not in line:
                continue

            if "//////" in line:
                parts   = line.split("//////", 1)
                trigger = parts[0].strip().lower()
                terms   = parts[1].strip()
                if not trigger or not terms:
                    continue
                remove_rules.append((trigger, terms))
            else:
                parts   = line.split("///", 1)
                trigger = parts[0].strip().lower()
                terms   = parts[1].strip()
                if not trigger or not terms:
                    continue
                add_rules.append((trigger, terms))

    return add_rules, remove_rules


# ---------------------------------------------------------------------------
# wildcard_combos.txt loader
# ---------------------------------------------------------------------------

def load_wildcard_combos() -> list:
    """
    Parse wildcard_combos.txt.

    Valid line format:
        keyword one // keyword two // ... // keyword N /// combo term

    Minimum 2 non-empty keywords required.
    Blank/placeholder lines and lines with empty values are silently skipped.
    Lines starting with '#' are comments.
    """
    combo_rules: list = []

    filepath = find_file_in_wildcards_dir("wildcard_combos.txt")

    if not os.path.isfile(filepath):
        return combo_rules

    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, 1):
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            if "///" not in line:
                continue

            left, combo_term = line.split("///", 1)
            combo_term = combo_term.strip()

            if not combo_term:
                continue

            keywords = [kw.strip().lower() for kw in left.split("//") if kw.strip()]

            if len(keywords) < 2:
                continue

            combo_rules.append((keywords, combo_term))

    return combo_rules


# ---------------------------------------------------------------------------
# Startup summary (runs once when Reforge loads the extension)
# ---------------------------------------------------------------------------

def _print_startup_summary():
    if not os.path.isdir(WILDCARDS_DIR):
        print(f"[AntiWildcards] WARNING: wildcards directory not found: {WILDCARDS_DIR}")
        return

    aw_path = find_file_in_wildcards_dir("antiwildcards.txt")
    wc_path = find_file_in_wildcards_dir("wildcard_combos.txt")

    add_rules, remove_rules = load_antiwildcards()
    combo_rules = load_wildcard_combos()

    if os.path.isfile(aw_path):
        print(f"[AntiWildcards] antiwildcards.txt: {len(add_rules)} add, {len(remove_rules)} remove rule(s)")
    else:
        print(f"[AntiWildcards] antiwildcards.txt: not found (expected: {aw_path})")

    if os.path.isfile(wc_path):
        print(f"[AntiWildcards] wildcard_combos.txt: {len(combo_rules)} combo rule(s)")
    else:
        print(f"[AntiWildcards] wildcard_combos.txt: not found (expected: {wc_path})")

_print_startup_summary()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def split_terms(text: str) -> list:
    """Split a comma-separated string into a normalised list of terms."""
    return [t.strip().lower() for t in text.split(",") if t.strip()]


def find_last_keyword_end(prompt: str, keywords: list) -> int:
    """
    Return the index immediately after the last character of whichever required
    keyword ends latest in prompt (case-insensitive).
    Returns -1 if any keyword is absent.
    """
    prompt_lower = prompt.lower()
    last_end = -1

    for kw in keywords:
        pos = prompt_lower.find(kw)
        if pos == -1:
            return -1
        kw_end = pos + len(kw)
        if kw_end > last_end:
            last_end = kw_end

    return last_end


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def apply_antiwildcards(positive_prompt: str, negative_prompt: str) -> str:
    """
    1. Run remove rules — strip matched terms from the negative prompt.
    2. Run add rules    — append new terms to the negative prompt.
    Deduplication enforced at every stage.
    """
    add_rules, remove_rules = load_antiwildcards()
    prompt_lower = positive_prompt.lower()

    # --- Step 1: removals ---
    if remove_rules:
        seen_triggers: set   = set()
        terms_to_remove: set = set()

        for trigger, terms_str in remove_rules:
            if trigger in prompt_lower and trigger not in seen_triggers:
                seen_triggers.add(trigger)
                for term in split_terms(terms_str):
                    print(f"[AntiWildcards] Removed from negative prompt '{term}' (trigger: '{trigger}')")
                    terms_to_remove.add(term)

        if terms_to_remove:
            kept: list = [
                raw.strip() for raw in negative_prompt.split(",")
                if raw.strip() and raw.strip().lower() not in terms_to_remove
            ]
            negative_prompt = (", ".join(kept) + ",") if kept else ""

    # --- Step 2: additions ---
    if add_rules:
        seen_triggers2: set = set()
        raw_additions: list = []

        for trigger, addition in add_rules:
            if trigger in prompt_lower and trigger not in seen_triggers2:
                seen_triggers2.add(trigger)
                print(f"[AntiWildcards] Added to negative prompt '{addition}' (trigger: '{trigger}')")
                raw_additions.append(addition)

        if raw_additions:
            existing_terms: set = set(split_terms(negative_prompt))
            new_terms: list     = []
            seen_new: set       = set()

            for addition in raw_additions:
                for term in split_terms(addition):
                    if term not in existing_terms and term not in seen_new:
                        seen_new.add(term)
                        new_terms.append(term)

            if new_terms:
                base     = negative_prompt.rstrip().rstrip(",").rstrip()
                appended = ", ".join(new_terms) + ","
                negative_prompt = (base + ", " + appended) if base else appended

    return negative_prompt


def apply_wildcard_combos(positive_prompt: str) -> str:
    """
    For each combo rule whose required keywords ALL appear in positive_prompt,
    inject the combo term immediately after the last-occurring required keyword.
    """
    combo_rules = load_wildcard_combos()

    if not combo_rules:
        return positive_prompt

    prompt = positive_prompt

    for keywords, combo_term in combo_rules:
        if combo_term.strip().lower() in prompt.lower():
            continue

        insert_pos = find_last_keyword_end(prompt, keywords)
        if insert_pos == -1:
            continue

        print(f"[AntiWildcards] Combo inserted into prompt '{combo_term}' (keywords: {keywords})")

        before = prompt[:insert_pos].rstrip()
        after  = prompt[insert_pos:]

        if not before.endswith(","):
            before = before + ","

        prompt = before + " " + combo_term + "," + after

    return prompt


# ---------------------------------------------------------------------------
# Script class
# ---------------------------------------------------------------------------

class AntiWildcardsScript(scripts.Script):

    def title(self):
        return "Anti-Wildcards"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        with gr.Accordion("Anti-Wildcards", open=False):
            enabled = gr.Checkbox(
                label="Enable Anti-Wildcards",
                value=True,
                elem_id=f"antiwildcards_enabled_{'img2img' if is_img2img else 'txt2img'}"
            )
            with gr.Row():
                reload_btn = gr.Button("↺ Reload rule files", size="sm")
                status = gr.Textbox(
                    label="",
                    value=self._get_status_text(),
                    interactive=False,
                    max_lines=1,
                    elem_id=f"antiwildcards_status_{'img2img' if is_img2img else 'txt2img'}"
                )

            def on_reload():
                add_rules, remove_rules = load_antiwildcards()
                combo_rules = load_wildcard_combos()
                return (
                    f"✅ {len(add_rules)} add, {len(remove_rules)} remove, "
                    f"{len(combo_rules)} combo rule(s)"
                )

            reload_btn.click(fn=on_reload, inputs=[], outputs=[status])

        return [enabled]

    def _get_status_text(self) -> str:
        aw_ok = os.path.isfile(find_file_in_wildcards_dir("antiwildcards.txt"))
        wc_ok = os.path.isfile(find_file_in_wildcards_dir("wildcard_combos.txt"))
        if not aw_ok and not wc_ok:
            return "⚠️ Neither rule file found"
        add_rules, remove_rules = load_antiwildcards() if aw_ok else ([], [])
        combo_rules = load_wildcard_combos() if wc_ok else []
        return (
            f"✅ {len(add_rules)} add, {len(remove_rules)} remove, "
            f"{len(combo_rules)} combo rule(s)"
        )

    def process_before_every_sampling(self, p, *args, **kwargs):
        """
        Fires once per image, after all process() hooks (including Dynamic
        Prompts wildcard expansion) have completed.
        """
        enabled = args[0] if args else True
        if not enabled:
            return

        idx = getattr(p, "iteration", 0)

        def _get(attr_name, fallback):
            lst = getattr(p, attr_name, None)
            if isinstance(lst, list) and len(lst) > idx:
                return lst[idx]
            if isinstance(lst, list) and lst:
                return lst[0]
            if isinstance(lst, str):
                return lst
            val = getattr(p, fallback, "")
            return val if isinstance(val, str) else ""

        pos = _get("all_prompts",          "prompt")
        neg = _get("all_negative_prompts", "negative_prompt")

        new_pos = apply_wildcard_combos(pos)
        new_neg = apply_antiwildcards(new_pos, neg)

        all_p = getattr(p, "all_prompts", None)
        if isinstance(all_p, list) and len(all_p) > idx:
            p.all_prompts[idx] = new_pos
        else:
            p.prompt = new_pos

        all_n = getattr(p, "all_negative_prompts", None)
        if isinstance(all_n, list) and len(all_n) > idx:
            p.all_negative_prompts[idx] = new_neg
        else:
            p.negative_prompt = new_neg
