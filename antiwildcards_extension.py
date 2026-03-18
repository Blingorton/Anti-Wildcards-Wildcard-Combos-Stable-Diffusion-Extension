"""
Anti-Wildcards Extension for Stable Diffusion Reforge
======================================================
antiwildcards.txt   — add/remove terms from the negative prompt
wildcard_combos.txt — inject combo terms into the positive prompt after the last keyword
combo_replace.txt   — same as wildcard_combos but replaces the last keyword instead
antidouble.txt      — remove duplicate phrases from the positive prompt

All files are searched recursively under the sd-dynamic-prompts wildcards folder.
All operations run in process_before_every_sampling so Dynamic Prompts wildcard
expansion has already occurred. Any __wildcard__ tokens injected by combo rules
are also resolved before generation.
"""

import os
import re
import random
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
    Recursively search WILDCARDS_DIR for filename (case-insensitive).
    Returns the full path of the first match, or a root-level fallback.
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
# Wildcard resolution
# ---------------------------------------------------------------------------

def resolve_wildcards(text: str) -> str:
    """
    Resolve any __wildcard_name__ tokens in text by looking up matching .txt
    files in WILDCARDS_DIR and picking a random non-empty, non-comment line.
    Resolves recursively so wildcards-within-wildcards work.
    Unresolvable tokens are left as-is.
    """
    pattern = re.compile(r"__([^_][^_]*?)__")
    max_passes = 10  # guard against infinite loops from circular wildcards

    for _ in range(max_passes):
        matches = pattern.findall(text)
        if not matches:
            break
        for token in set(matches):
            wc_path = find_file_in_wildcards_dir(token + ".txt")
            if not os.path.isfile(wc_path):
                continue
            with open(wc_path, "r", encoding="utf-8") as f:
                candidates = [
                    ln.strip() for ln in f
                    if ln.strip() and not ln.strip().startswith("#")
                ]
            if not candidates:
                continue
            replacement = random.choice(candidates)
            text = text.replace(f"__{token}__", replacement, 1)

    return text


def text_has_wildcards(text: str) -> bool:
    """Return True if text contains any __wildcard__ tokens."""
    return bool(re.search(r"__[^_][^_]*?__", text))


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_antiwildcards() -> tuple:
    """
    Parse antiwildcards.txt.
      trigger ///    terms  -> ADD rule  (append terms to negative)
      trigger //////  terms  -> REMOVE rule (strip terms from negative)
    Empty triggers/values and blank lines are silently skipped.
    """
    add_rules: list    = []
    remove_rules: list = []

    filepath = find_file_in_wildcards_dir("antiwildcards.txt")
    if not os.path.isfile(filepath):
        return add_rules, remove_rules

    with open(filepath, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "///" not in line:
                continue
            if "//////" in line:
                parts   = line.split("//////", 1)
                trigger = parts[0].strip().lower()
                terms   = parts[1].strip()
                if trigger and terms:
                    remove_rules.append((trigger, terms))
            else:
                parts   = line.split("///", 1)
                trigger = parts[0].strip().lower()
                terms   = parts[1].strip()
                if trigger and terms:
                    add_rules.append((trigger, terms))

    return add_rules, remove_rules


def load_wildcard_combos() -> list:
    """
    Parse wildcard_combos.txt.
      kw1 // kw2 // ... /// combo_term
    Injects combo_term after the last-occurring keyword. Min 2 keywords.
    """
    rules: list = []

    filepath = find_file_in_wildcards_dir("wildcard_combos.txt")
    if not os.path.isfile(filepath):
        return rules

    with open(filepath, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "///" not in line:
                continue
            left, combo_term = line.split("///", 1)
            combo_term = combo_term.strip()
            if not combo_term:
                continue
            keywords = [kw.strip().lower() for kw in left.split("//") if kw.strip()]
            if len(keywords) >= 2:
                rules.append((keywords, combo_term))

    return rules


def load_combo_replace() -> list:
    """
    Parse combo_replace.txt.
      kw1 // kw2 // ... /// replacement_term
    Same as wildcard_combos but replaces the last-occurring keyword with
    replacement_term instead of inserting after it. Min 2 keywords.
    """
    rules: list = []

    filepath = find_file_in_wildcards_dir("combo_replace.txt")
    if not os.path.isfile(filepath):
        return rules

    with open(filepath, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "///" not in line:
                continue
            left, replacement = line.split("///", 1)
            replacement = replacement.strip()
            if not replacement:
                continue
            keywords = [kw.strip().lower() for kw in left.split("//") if kw.strip()]
            if len(keywords) >= 2:
                rules.append((keywords, replacement))

    return rules


def load_antidouble() -> list:
    """
    Parse antidouble.txt.
    One phrase per line. After wildcard resolution, each phrase is allowed to
    appear only once in the positive prompt — all copies beyond the first are removed.
    """
    phrases: list = []

    filepath = find_file_in_wildcards_dir("antidouble.txt")
    if not os.path.isfile(filepath):
        return phrases

    with open(filepath, "r", encoding="utf-8") as f:
        for raw_line in f:
            phrase = raw_line.strip()
            if phrase and not phrase.startswith("#"):
                phrases.append(phrase)

    return phrases


# ---------------------------------------------------------------------------
# Startup summary
# ---------------------------------------------------------------------------

def _print_startup_summary():
    if not os.path.isdir(WILDCARDS_DIR):
        print(f"[AntiWildcards] WARNING: wildcards directory not found: {WILDCARDS_DIR}")
        return

    files = {
        "antiwildcards.txt":  "antiwildcards.txt",
        "wildcard_combos.txt": "wildcard_combos.txt",
        "combo_replace.txt":  "combo_replace.txt",
        "antidouble.txt":     "antidouble.txt",
    }

    add_rules, remove_rules = load_antiwildcards()
    combo_rules   = load_wildcard_combos()
    replace_rules = load_combo_replace()
    double_phrases = load_antidouble()

    def _found(name):
        return os.path.isfile(find_file_in_wildcards_dir(name))

    if _found("antiwildcards.txt"):
        print(f"[AntiWildcards] antiwildcards.txt:   {len(add_rules)} add, {len(remove_rules)} remove rule(s)")
    else:
        print(f"[AntiWildcards] antiwildcards.txt:   not found")

    if _found("wildcard_combos.txt"):
        print(f"[AntiWildcards] wildcard_combos.txt: {len(combo_rules)} combo rule(s)")
    else:
        print(f"[AntiWildcards] wildcard_combos.txt: not found")

    if _found("combo_replace.txt"):
        print(f"[AntiWildcards] combo_replace.txt:   {len(replace_rules)} replace rule(s)")
    else:
        print(f"[AntiWildcards] combo_replace.txt:   not found")

    if _found("antidouble.txt"):
        print(f"[AntiWildcards] antidouble.txt:      {len(double_phrases)} phrase(s)")
    else:
        print(f"[AntiWildcards] antidouble.txt:      not found")

_print_startup_summary()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def split_terms(text: str) -> list:
    """Split a comma-separated string into a normalised list of terms."""
    return [t.strip().lower() for t in text.split(",") if t.strip()]


def find_last_keyword_position(prompt: str, keywords: list):
    """
    Find the keyword that ends latest in the prompt (case-insensitive).
    Returns (start_idx, end_idx, matched_keyword_original_case) or None if
    any keyword is missing.
    """
    prompt_lower = prompt.lower()
    last_end   = -1
    last_start = -1
    last_kw    = ""

    for kw in keywords:
        pos = prompt_lower.find(kw)
        if pos == -1:
            return None
        kw_end = pos + len(kw)
        if kw_end > last_end:
            last_end   = kw_end
            last_start = pos
            last_kw    = kw

    return (last_start, last_end, last_kw)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def apply_antiwildcards(positive_prompt: str, negative_prompt: str) -> str:
    """Apply add/remove rules to the negative prompt."""
    add_rules, remove_rules = load_antiwildcards()
    prompt_lower = positive_prompt.lower()

    # Step 1: removals
    if remove_rules:
        seen: set           = set()
        to_remove: set      = set()
        for trigger, terms_str in remove_rules:
            if trigger in prompt_lower and trigger not in seen:
                seen.add(trigger)
                for term in split_terms(terms_str):
                    print(f"[AntiWildcards] Removed from negative prompt '{term}' (trigger: '{trigger}')")
                    to_remove.add(term)
        if to_remove:
            kept = [r.strip() for r in negative_prompt.split(",")
                    if r.strip() and r.strip().lower() not in to_remove]
            negative_prompt = (", ".join(kept) + ",") if kept else ""

    # Step 2: additions
    if add_rules:
        seen2: set          = set()
        raw_additions: list = []
        for trigger, addition in add_rules:
            if trigger in prompt_lower and trigger not in seen2:
                seen2.add(trigger)
                print(f"[AntiWildcards] Added to negative prompt '{addition}' (trigger: '{trigger}')")
                raw_additions.append(addition)
        if raw_additions:
            existing: set   = set(split_terms(negative_prompt))
            new_terms: list = []
            seen_new: set   = set()
            for addition in raw_additions:
                for term in split_terms(addition):
                    if term not in existing and term not in seen_new:
                        seen_new.add(term)
                        new_terms.append(term)
            if new_terms:
                base     = negative_prompt.rstrip().rstrip(",").rstrip()
                appended = ", ".join(new_terms) + ","
                negative_prompt = (base + ", " + appended) if base else appended

    return negative_prompt


def _apply_combo_rules(positive_prompt: str, rules: list, mode: str) -> str:
    """
    Shared engine for wildcard_combos and combo_replace.
    mode="insert"  — inject term after the last keyword
    mode="replace" — replace the last keyword with the term
    After applying each rule, resolves any __wildcards__ in the injected term.
    """
    prompt = positive_prompt

    for keywords, term in rules:
        # Resolve wildcards in the term before checking/inserting
        resolved_term = resolve_wildcards(term) if text_has_wildcards(term) else term
        if text_has_wildcards(term):
            print(f"[AntiWildcards] Resolved wildcard '{term}' -> '{resolved_term}'")

        if resolved_term.strip().lower() in prompt.lower():
            continue

        result = find_last_keyword_position(prompt, keywords)
        if result is None:
            continue

        start, end, last_kw = result

        if mode == "insert":
            print(f"[AntiWildcards] Combo inserted into prompt '{resolved_term}' (keywords: {keywords})")
            before = prompt[:end].rstrip()
            after  = prompt[end:]
            if not before.endswith(","):
                before = before + ","
            prompt = before + " " + resolved_term + "," + after

        elif mode == "replace":
            # Find the actual casing of the last keyword in the prompt
            original_kw = prompt[start:end]
            print(f"[AntiWildcards] Combo replaced '{original_kw}' with '{resolved_term}' (keywords: {keywords})")
            prompt = prompt[:start] + resolved_term + prompt[end:]

    return prompt


def apply_wildcard_combos(positive_prompt: str) -> str:
    """Insert combo terms after the last-occurring required keyword."""
    rules = load_wildcard_combos()
    if not rules:
        return positive_prompt
    return _apply_combo_rules(positive_prompt, rules, mode="insert")


def apply_combo_replace(positive_prompt: str) -> str:
    """Replace the last-occurring required keyword with the replacement term."""
    rules = load_combo_replace()
    if not rules:
        return positive_prompt
    return _apply_combo_rules(positive_prompt, rules, mode="replace")


def _phrase_to_pattern(phrase: str):
    """
    Convert a phrase from antidouble.txt into a (pattern, is_regex) tuple.

    If the phrase contains '#' as a literal character, it is treated as a
    wildcard that matches any numeric value (including negatives and decimals).
    This is specifically designed for LoRA weight wildcards, e.g.:
        <lora:loraname:#>  matches  <lora:loraname:0.8>, <lora:loraname:-0.6>, etc.

    Returns (compiled_regex, True) for wildcard phrases,
    or (lowercased_string, False) for plain phrases.
    """
    if "#" not in phrase:
        return (phrase.lower(), False)

    # Escape everything except '#', then replace '#' with a numeric pattern
    escaped = re.escape(phrase).replace(r"\#", r"[-+]?[0-9]*\.?[0-9]+")
    return (re.compile(escaped, re.IGNORECASE), True)


def apply_antidouble(positive_prompt: str) -> str:
    """
    For each phrase in antidouble.txt, remove all occurrences beyond the first
    from positive_prompt.

    Plain phrases: case-insensitive exact match.
    Phrases containing '#': '#' acts as a numeric wildcard, so
        <lora:loraname:#>
    will match and deduplicate any two instances of that LoRA regardless of
    their weight values, keeping the first occurrence as-is.

    Duplicates are excised as raw substrings; a cleanup pass then collapses
    any resulting double commas or extra whitespace.
    """
    phrases = load_antidouble()
    if not phrases:
        return positive_prompt

    prompt = positive_prompt

    for phrase in phrases:
        pattern, is_regex = _phrase_to_pattern(phrase)

        if is_regex:
            # Find all matches (start, end) pairs
            matches = [(m.start(), m.end()) for m in pattern.finditer(prompt)]
        else:
            # Plain string search
            matches = []
            search_from = 0
            while True:
                pos = prompt.lower().find(pattern, search_from)
                if pos == -1:
                    break
                matches.append((pos, pos + len(phrase)))
                search_from = pos + len(phrase)

        if len(matches) < 2:
            continue

        print(f"[AntiWildcards] Antidouble removed {len(matches) - 1} duplicate(s) of '{phrase}'")

        # Remove all but the first, back-to-front to preserve indices
        for start, end in reversed(matches[1:]):
            prompt = prompt[:start] + prompt[end:]

    # Collapse any double commas or extra whitespace left behind
    prompt = re.sub(r",\s*,+", ",", prompt)
    prompt = re.sub(r"\s{2,}", " ", prompt)
    prompt = prompt.strip().strip(",").strip()

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
                combo_rules   = load_wildcard_combos()
                replace_rules = load_combo_replace()
                double_phrases = load_antidouble()
                return (
                    f"✅ {len(add_rules)} add, {len(remove_rules)} remove, "
                    f"{len(combo_rules)} combo, {len(replace_rules)} replace, "
                    f"{len(double_phrases)} antidouble"
                )

            reload_btn.click(fn=on_reload, inputs=[], outputs=[status])

        return [enabled]

    def _get_status_text(self) -> str:
        add_rules, remove_rules = load_antiwildcards()
        combo_rules   = load_wildcard_combos()
        replace_rules = load_combo_replace()
        double_phrases = load_antidouble()
        return (
            f"✅ {len(add_rules)} add, {len(remove_rules)} remove, "
            f"{len(combo_rules)} combo, {len(replace_rules)} replace, "
            f"{len(double_phrases)} antidouble"
        )

    def process_before_every_sampling(self, p, *args, **kwargs):
        """
        Fires once per image, after all process() hooks (including Dynamic
        Prompts wildcard expansion) have completed.

        Pipeline:
          1. apply_wildcard_combos  — insert combo terms into positive
          2. apply_combo_replace    — replace keywords in positive
          3. apply_antidouble       — remove duplicate phrases from positive
          4. apply_antiwildcards    — modify negative based on final positive
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
        new_pos = apply_combo_replace(new_pos)
        new_pos = apply_antidouble(new_pos)
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
