"""
Spreeder - Rapid Serial Visual Presentation App
A speed reading tool that displays text word by word with fixation point highlighting.
Runs in background with system tray icon. Press F3 to activate.
"""

import customtkinter as ctk
import pyperclip
import keyboard
import threading
import time
import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

# System tray support
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    print("pystray not available - running without system tray icon")

# Load environment variables
load_dotenv()

# ==================== DEBUG LOGGING SYSTEM ====================

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debugging log.txt")
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

# Fallback log file in case main one is locked
_log_fallback_file = None
_log_write_failures = 0
_log_permission_warned = False  # Only warn once for permission errors

def debug_log(event_type: str, details: str, extra_data: dict = None):
    """
    Write extensive debug information to the log file.
    Every user interaction and system event is logged here.
    """
    global _log_fallback_file, _log_write_failures, _log_permission_warned
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    log_entry = f"[{timestamp}] [{event_type}] {details}"
    
    if extra_data:
        log_entry += f" | Data: {json.dumps(extra_data, default=str)}"
    
    log_entry += "\n"
    
    # Try main log file first
    log_file_to_use = _log_fallback_file if _log_fallback_file else LOG_FILE
    
    for attempt in range(3):
        try:
            with open(log_file_to_use, "a", encoding="utf-8") as f:
                f.write(log_entry)
            return  # Success
        except PermissionError:
            if attempt < 2:
                time.sleep(0.05)  # Brief wait before retry
                continue
            # After 3 failures, try fallback file
            if not _log_fallback_file:
                session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
                _log_fallback_file = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), 
                    f"debugging_log_{session_id}.txt"
                )
                log_file_to_use = _log_fallback_file
                _log_write_failures += 1
                if not _log_permission_warned:
                    _log_permission_warned = True
                    print(f"Log file locked, using fallback: {_log_fallback_file}")
            else:
                # Fallback file also failed - silently skip logging
                return
        except Exception as e:
            _log_write_failures += 1
            if _log_write_failures <= 1:
                print(f"Failed to write to log: {e}")
            return  # Don't keep retrying on other errors

# ==================== COMPREHENSIVE UI LOGGING ====================

def get_widget_info(widget, indent=0):
    """Get comprehensive info about a widget including position and visibility"""
    try:
        info = {
            "widget": str(widget),
            "class": widget.winfo_class(),
            "visible": widget.winfo_viewable(),
            "mapped": widget.winfo_ismapped(),
            "x": widget.winfo_x(),
            "y": widget.winfo_y(),
            "width": widget.winfo_width(),
            "height": widget.winfo_height(),
            "rootx": widget.winfo_rootx(),
            "rooty": widget.winfo_rooty(),
            "manager": widget.winfo_manager() if widget.winfo_ismapped() else "not_managed"
        }
        # Try to get text/label for identification
        try:
            if hasattr(widget, 'cget'):
                try:
                    info["text"] = widget.cget("text")
                except:
                    pass
        except:
            pass
        return info
    except Exception as e:
        return {"widget": str(widget), "error": str(e)}

def log_widget_tree(parent, window_name="Unknown", indent=0):
    """Recursively log all widgets in a window hierarchy"""
    try:
        widget_info = get_widget_info(parent, indent)
        widget_info["indent_level"] = indent
        widget_info["window_name"] = window_name
        debug_log("UI_WIDGET", f"{'  ' * indent}{parent.winfo_class()}", widget_info)
        
        # Get children
        for child in parent.winfo_children():
            log_widget_tree(child, window_name, indent + 1)
    except Exception as e:
        debug_log("UI_WIDGET_ERROR", f"Error logging widget: {str(e)}")

def log_all_windows(root):
    """Log all toplevel windows and their widget trees"""
    debug_log("UI_SNAPSHOT", "=" * 60)
    debug_log("UI_SNAPSHOT", "Starting comprehensive UI snapshot")
    
    # Log root window
    log_widget_tree(root, "Root")
    
    # Log all toplevels
    try:
        for toplevel in root.winfo_children():
            if toplevel.winfo_class() in ('Toplevel', 'CTkToplevel'):
                try:
                    title = toplevel.title() if hasattr(toplevel, 'title') else "Unknown"
                    log_widget_tree(toplevel, title)
                except:
                    log_widget_tree(toplevel, "Toplevel")
    except Exception as e:
        debug_log("UI_SNAPSHOT_ERROR", f"Error logging toplevels: {str(e)}")
    
    debug_log("UI_SNAPSHOT", "UI snapshot complete")
    debug_log("UI_SNAPSHOT", "=" * 60)

def setup_global_event_logging(window, window_name="Unknown"):
    """Set up comprehensive event logging for a window"""
    
    def log_key_press(event):
        debug_log("KEY_PRESS", f"{window_name}", {
            "keysym": event.keysym,
            "keycode": event.keycode,
            "char": repr(event.char),
            "state": event.state,
            "state_names": get_modifier_names(event.state),
            "widget": str(event.widget),
            "widget_class": event.widget.winfo_class() if hasattr(event.widget, 'winfo_class') else "unknown",
            "focus": str(window.focus_get())
        })
    
    def log_key_release(event):
        debug_log("KEY_RELEASE", f"{window_name}", {
            "keysym": event.keysym,
            "keycode": event.keycode,
            "widget": str(event.widget)
        })
    
    def log_mouse_click(event):
        debug_log("MOUSE_CLICK", f"{window_name}", {
            "button": event.num,
            "x": event.x,
            "y": event.y,
            "x_root": event.x_root,
            "y_root": event.y_root,
            "widget": str(event.widget),
            "widget_class": event.widget.winfo_class() if hasattr(event.widget, 'winfo_class') else "unknown"
        })
    
    def log_mouse_release(event):
        debug_log("MOUSE_RELEASE", f"{window_name}", {
            "button": event.num,
            "x": event.x,
            "y": event.y,
            "widget": str(event.widget)
        })
    
    def log_mouse_motion(event):
        # Only log every 100ms to avoid spam - use a simple throttle
        pass  # Disabled by default - too spammy
    
    def log_focus_in(event):
        debug_log("FOCUS_IN", f"{window_name}", {
            "widget": str(event.widget),
            "widget_class": event.widget.winfo_class() if hasattr(event.widget, 'winfo_class') else "unknown"
        })
    
    def log_focus_out(event):
        debug_log("FOCUS_OUT", f"{window_name}", {
            "widget": str(event.widget),
            "widget_class": event.widget.winfo_class() if hasattr(event.widget, 'winfo_class') else "unknown"
        })
    
    def log_enter(event):
        debug_log("MOUSE_ENTER", f"{window_name}", {
            "widget": str(event.widget),
            "widget_class": event.widget.winfo_class() if hasattr(event.widget, 'winfo_class') else "unknown",
            "x": event.x,
            "y": event.y
        })
    
    def log_leave(event):
        debug_log("MOUSE_LEAVE", f"{window_name}", {
            "widget": str(event.widget),
            "widget_class": event.widget.winfo_class() if hasattr(event.widget, 'winfo_class') else "unknown"
        })
    
    # Bind events to window (will propagate to children)
    window.bind("<KeyPress>", log_key_press, add="+")
    window.bind("<KeyRelease>", log_key_release, add="+")
    window.bind("<Button>", log_mouse_click, add="+")
    window.bind("<ButtonRelease>", log_mouse_release, add="+")
    window.bind("<FocusIn>", log_focus_in, add="+")
    window.bind("<FocusOut>", log_focus_out, add="+")
    window.bind("<Enter>", log_enter, add="+")
    window.bind("<Leave>", log_leave, add="+")
    
    debug_log("UI_LOGGING_SETUP", f"Global event logging enabled for {window_name}")

def get_modifier_names(state):
    """Convert event state bitmask to human-readable modifier names"""
    modifiers = []
    if state & 0x1:
        modifiers.append("Shift")
    if state & 0x4:
        modifiers.append("Control")
    if state & 0x8:
        modifiers.append("Alt")
    if state & 0x20000:
        modifiers.append("Alt_Gr")
    if state & 0x40000:
        modifiers.append("Num_Lock")
    if state & 0x2:
        modifiers.append("Caps_Lock")
    return modifiers if modifiers else ["None"]

def log_visible_elements(window, window_name="Unknown"):
    """Log only visible/mapped elements with their positions"""
    debug_log("UI_VISIBLE", f"=== Visible elements in {window_name} ===")
    
    def collect_visible(widget, results, indent=0):
        try:
            if widget.winfo_ismapped() and widget.winfo_viewable():
                info = get_widget_info(widget, indent)
                info["indent"] = indent
                results.append(info)
            for child in widget.winfo_children():
                collect_visible(child, results, indent + 1)
        except:
            pass
    
    visible = []
    collect_visible(window, visible)
    
    for elem in visible:
        indent_str = "  " * elem.get("indent", 0)
        text = elem.get("text", "")
        text_display = f" '{text}'" if text else ""
        debug_log("UI_VISIBLE", f"{indent_str}{elem['class']}{text_display} @ ({elem['x']},{elem['y']}) {elem['width']}x{elem['height']}", elem)
    
    debug_log("UI_VISIBLE", f"=== Total: {len(visible)} visible elements ===")
    return visible

def log_startup():
    """Log application startup with system info"""
    debug_log("STARTUP", "="*60)
    debug_log("STARTUP", "Spreeder Application Starting")
    debug_log("STARTUP", f"Log file: {LOG_FILE}")
    debug_log("STARTUP", f"Settings file: {SETTINGS_FILE}")
    debug_log("STARTUP", f"Working directory: {os.getcwd()}")
    debug_log("STARTUP", "="*60)

# ==================== SETTINGS MANAGEMENT ====================

def load_settings() -> dict:
    """Load user settings from JSON file"""
    debug_log("SETTINGS", "Attempting to load settings from file", {"path": SETTINGS_FILE})
    default_settings = {"wpm": 400, "pause_delay": 750}
    
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                settings = json.load(f)
                # Ensure all default keys exist
                for key, value in default_settings.items():
                    if key not in settings:
                        settings[key] = value
                debug_log("SETTINGS", "Settings loaded successfully", settings)
                return settings
        else:
            debug_log("SETTINGS", "No settings file found, using defaults", default_settings)
            return default_settings
    except Exception as e:
        debug_log("SETTINGS_ERROR", f"Failed to load settings: {str(e)}", {"exception": str(e)})
        return default_settings

def save_settings(settings: dict):
    """Save user settings to JSON file"""
    debug_log("SETTINGS", "Saving settings to file", settings)
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
        debug_log("SETTINGS", "Settings saved successfully")
    except Exception as e:
        debug_log("SETTINGS_ERROR", f"Failed to save settings: {str(e)}", {"exception": str(e)})

# ==================== OPENAI INTEGRATION ====================

# Default model for modifier system (highest quality synthesis)
DEFAULT_MODEL = "gpt-5.2"

# Model pricing per 1M tokens (input, output) - estimated rates
MODEL_PRICING = {
    "gpt-5.2": (2.50, 10.00),       # $2.50/1M input, $10.00/1M output
    "gpt-4o": (2.50, 10.00),        # $2.50/1M input, $10.00/1M output
    "gpt-4o-mini": (0.15, 0.60),    # $0.15/1M input, $0.60/1M output
}

def estimate_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    """Estimate API cost in USD based on token counts and model."""
    pricing = MODEL_PRICING.get(model, MODEL_PRICING.get("gpt-4o-mini"))
    input_cost = (input_tokens / 1_000_000) * pricing[0]
    output_cost = (output_tokens / 1_000_000) * pricing[1]
    return input_cost + output_cost

def format_cost(cost: float) -> str:
    """Format cost as string with appropriate precision."""
    if cost < 0.01:
        return f"${cost:.4f}"
    elif cost < 0.10:
        return f"${cost:.3f}"
    else:
        return f"${cost:.2f}"

# Token usage backup file
TOKEN_BACKUP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_responses_backup.txt")
AUGMENTATION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Augmentation")

# Ensure Augmentation directory exists
os.makedirs(AUGMENTATION_DIR, exist_ok=True)

# ==================== MODIFIER SYSTEM PROMPTS ====================

# Brain synthesis system prompt (constant - do not rebuild every click)
BRAIN_SYNTHESIS_SYSTEM_PROMPT = """You are an expert technical instructor and security engineering mentor. Your job is to transform the user's raw notes into ONE single continuous block of text that makes an adult learner meaningfully understand, remember, and be able to apply the material.

Adult learning (andragogy) requirements:
- Assume the learner is competent, busy, and goal-driven. Optimize for relevance, autonomy, and immediate application.
- Tie concepts to real work decisions, tradeoffs, and consequences.
- Activate prior knowledge: connect new ideas to what an experienced practitioner likely already knows.
- Prefer problem-centered teaching over topic-centered definitions.

Learning science requirements:
- Use elaboration: explain "why this matters" and "how it connects" (not just what it is).
- Use interleaving: weave related topics together (do not teach in isolated silos).
- Use retrieval practice inside the text: include quick self-check questions the learner can answer mentally.
- Use concrete scenarios and "worked examples": show what good looks like in practice.
- Use memory hooks: simple organizing metaphors, recurring structure, and a compact mental model.
- Emphasize common failure modes and how to avoid them.

Output constraints:
- Output MUST be exactly one single block of text: one paragraph, no headings, no bullet points, no numbered lists, no blank lines.
- Do not quote the notes verbatim at length; synthesize and integrate them.
- Do not invent tools, services, policies, or facts not present in the notes; if something is missing, make a clearly-labeled assumption in-line (e.g., "Assumption: …") and keep it minimal.
- Keep it crisp but thorough: aim for dense clarity, not fluff.
- The learner should finish with (1) a coherent mental map, (2) practical next actions, and (3) a sense of how the pieces reinforce each other in real engagements.

Required structure inside the single paragraph (do this without headings):
1) Start with a "why/goal" framing tied to real outcomes.
2) Build a mental model that unifies the domains covered in the notes.
3) Walk through one realistic end-to-end scenario, weaving in the notes as applied decisions.
4) Insert at least 6 short retrieval questions spread through the paragraph (formatted like: "Quick check: …?").
5) End with a compact action plan the learner could do in the next week (still within the same paragraph).

Tone:
- Confident, practical, calm, and motivating. No hype. No sarcasm.
- Assume the learner may interview for technical roles; keep examples aligned with that reality."""

INTERVIEW_DRILL_SYSTEM_PROMPT = """You are an interview coach for security engineering and automation roles with Amazon-style interview expectations. Create drills that force crisp STAR storytelling and measurable results.

Constraints:
- Output must be structured as:
  - Section A: 8–10 STAR story prompts (each includes Situation, Task, Action, Result as prompts, not answers).
  - Section B: For each story, include exactly 2 follow-up probes and exactly 1 metrics hook.
  - Section C: Provide a 60-second version guidance and a 3-minute version guidance (how to compress/expand).
- High-signal, no fluff. Optimize for speaking practice.
- Do not invent user experience. If needed, phrase prompts so the user can fill details.
- Use the notes to anchor realistic scenarios: engagement security, guardrails, threat modeling, AppSec reviews, metrics, incident response, and consulting dynamics.

Tone: direct, practical, bar-raiser."""

MINI_LAB_SYSTEM_PROMPT = """You are a pragmatic technical mentor. Convert the notes into hands-on mini-labs that build real credibility fast.

Constraints:
- Create exactly 3 labs.
- Each lab must include: Goal, Preconditions, Steps (5–12), Success checks (3–6), Failure modes + fixes (2–4), Deliverable artifact, Stretch goal.
- Labs must be doable by one person in under 2 hours each unless the user explicitly requests otherwise.
- Prefer tasks that produce evidence: screenshots, JSON reports, runbooks, policy packs, PR-style reviews.
- Use the notes as the content source. Do not invent services beyond those in the notes.
- Optimize for adult learners: clear why, immediate payoff, and real-world constraints.

Tone: crisp, motivating, engineering-real."""

FLASH_QUIZ_SYSTEM_PROMPT = """You are a learning-science-informed instructor. Create a flash-recall quiz that forces retrieval and applied reasoning.

Constraints:
- Exactly 20 questions, with this mix:
  - 8 short-answer
  - 6 scenario-based (choose best action)
  - 4 "find the flaw"
  - 2 synthesis questions combining 3+ concepts
- After the questions, include a complete answer key.
- Interleave topics: IAM/governance/network boundaries/encryption/secrets/logging/detection/config, plus threat modeling, AppSec review, metrics, and incident response.
- Questions must be answerable from the notes + reasonable security engineering judgment; do not require obscure trivia.
- Keep questions concise, but make scenarios realistic.
- End with a 4-point spaced repetition suggestion: Day 0, Day 2, Day 7, Day 14.

Tone: sharp, practical, no fluff."""

# ==================== MODIFIER REGISTRY ====================

import re
import hashlib

def _hash_text(text: str) -> str:
    """Create a short hash of text for logging (no raw content)"""
    return hashlib.md5(text.encode()).hexdigest()[:8]

def _log_modifier_invocation(modifier_id: str, chars_in: int, selected_text_used: bool,
                              model: str, latency_ms: int, retries: int, status: str, 
                              error_code: str = None, chars_out: int = 0):
    """Log modifier invocation without raw text content"""
    debug_log("MODIFIER_INVOKE", f"Modifier: {modifier_id}", {
        "modifier_id": modifier_id,
        "chars_in": chars_in,
        "chars_out": chars_out,
        "selected_text_used": selected_text_used,
        "model": model,
        "latency_ms": latency_ms,
        "retries": retries,
        "status": status,
        "error_code": error_code
    })

# Validator functions for each modifier
def _validate_brain(output: str) -> dict:
    """Validate Brain synthesis output"""
    errors = []
    
    # Check for single paragraph (no double newlines)
    if '\n\n' in output:
        errors.append("Multiple paragraphs detected")
    
    # Check for bullets/lists
    if re.search(r'^[\s]*[-•*]\s', output, re.MULTILINE):
        errors.append("Bullet points detected")
    if re.search(r'^[\s]*\d+[\.\)]\s', output, re.MULTILINE):
        errors.append("Numbered lists detected")
    
    # Check for Quick checks
    quick_count = output.lower().count("quick check:")
    if quick_count < 6:
        errors.append(f"Only {quick_count} Quick checks (need 6+)")
    
    return {"ok": len(errors) == 0, "errors": errors}

def _validate_interview_drill(output: str) -> dict:
    """Validate Interview Drill output"""
    errors = []
    
    # Gate A: 8-10 STAR prompts (look for "Story" or "STAR" numbered sections)
    story_matches = re.findall(r'(?:Story|STAR|Prompt)\s*#?\d+|Section A', output, re.IGNORECASE)
    star_count = len(re.findall(r'(?:Situation|SITUATION).*?(?:Task|TASK).*?(?:Action|ACTION).*?(?:Result|RESULT)', output, re.DOTALL | re.IGNORECASE))
    
    # Count by looking for numbered stories or STAR patterns
    story_count = len(re.findall(r'(?:^|\n)\s*(?:\d+[\.\)]\s*|Story\s*\d+|STAR\s*\d+)', output, re.IGNORECASE))
    if story_count < 8:
        # Try alternate detection
        story_count = len(re.findall(r'Situation:', output, re.IGNORECASE))
    
    if story_count < 8:
        errors.append(f"Only {story_count} STAR prompts detected (need 8-10)")
    
    # Gate B: Follow-up probes and metrics hooks
    probe_count = len(re.findall(r'(?:probe|follow-up|follow up)', output, re.IGNORECASE))
    metrics_count = len(re.findall(r'(?:metric|number|measure|quantif)', output, re.IGNORECASE))
    
    if probe_count < 16:  # 2 per story * 8 stories
        errors.append(f"Insufficient follow-up probes ({probe_count}, need ~16)")
    
    # Gate C: 60-second and 3-minute guidance
    has_60s = bool(re.search(r'60.?second|1.?minute|one.?minute', output, re.IGNORECASE))
    has_3min = bool(re.search(r'3.?minute|three.?minute', output, re.IGNORECASE))
    
    if not has_60s:
        errors.append("Missing 60-second version guidance")
    if not has_3min:
        errors.append("Missing 3-minute version guidance")
    
    return {"ok": len(errors) == 0, "errors": errors}

def _validate_mini_lab(output: str) -> dict:
    """Validate Mini-Lab output"""
    errors = []
    
    # Gate A: Exactly 3 labs
    lab_matches = re.findall(r'(?:Lab|LAB)\s*#?\d+|(?:^|\n)#{1,3}\s*Lab', output, re.IGNORECASE | re.MULTILINE)
    lab_count = len(lab_matches)
    if lab_count == 0:
        # Try alternate detection
        lab_count = len(re.findall(r'(?:^|\n)\s*(?:\d+[\.\)]\s*)?(?:Goal|GOAL):', output, re.IGNORECASE | re.MULTILINE))
    
    if lab_count != 3:
        errors.append(f"Found {lab_count} labs (need exactly 3)")
    
    # Gate B: Required fields per lab
    required_fields = ['goal', 'precondition', 'step', 'success', 'failure', 'deliverable', 'stretch']
    for field in required_fields:
        if not re.search(field, output, re.IGNORECASE):
            errors.append(f"Missing required field: {field}")
    
    # Gate C: Steps count (5-12) - rough check
    steps_sections = re.findall(r'Steps?:.*?(?=Success|Failure|$)', output, re.DOTALL | re.IGNORECASE)
    for i, section in enumerate(steps_sections):
        step_count = len(re.findall(r'(?:^|\n)\s*\d+[\.\)]', section))
        if step_count > 0 and (step_count < 5 or step_count > 12):
            errors.append(f"Lab {i+1} has {step_count} steps (need 5-12)")
    
    return {"ok": len(errors) == 0, "errors": errors}

def _validate_flash_quiz(output: str) -> dict:
    """Validate Flash Quiz output"""
    errors = []
    
    # Gate A: Exactly 20 questions
    question_matches = re.findall(r'(?:^|\n)\s*(?:Q\.?\s*)?\d+[\.\):]|\?(?:\s|$)', output)
    # Better: count lines ending with ?
    question_count = len(re.findall(r'\?(?:\s*$|\s*\n)', output, re.MULTILINE))
    
    # Also try numbered pattern
    numbered_qs = len(re.findall(r'(?:^|\n)\s*\d+[\.\)]', output[:output.find('Answer') if 'Answer' in output else len(output)]))
    question_count = max(question_count, numbered_qs)
    
    if question_count < 18 or question_count > 22:
        errors.append(f"Found ~{question_count} questions (need exactly 20)")
    
    # Gate B: Mix check (8/6/4/2) - simplified check for presence
    has_short_answer = bool(re.search(r'short.?answer', output, re.IGNORECASE))
    has_scenario = bool(re.search(r'scenario|choose|best action', output, re.IGNORECASE))
    has_flaw = bool(re.search(r'flaw|find the|spot the|what.?s wrong', output, re.IGNORECASE))
    has_synthesis = bool(re.search(r'synthesis|combin|integrat', output, re.IGNORECASE))
    
    # Gate C: Answer key
    has_answer_key = bool(re.search(r'answer\s*key|answers?:', output, re.IGNORECASE))
    if not has_answer_key:
        errors.append("Missing answer key")
    
    # Gate D: Spacing schedule
    has_day0 = bool(re.search(r'day\s*0', output, re.IGNORECASE))
    has_day2 = bool(re.search(r'day\s*2', output, re.IGNORECASE))
    has_day7 = bool(re.search(r'day\s*7', output, re.IGNORECASE))
    has_day14 = bool(re.search(r'day\s*14', output, re.IGNORECASE))
    
    if not (has_day0 and has_day2 and has_day7 and has_day14):
        errors.append("Missing spaced repetition schedule (Day 0/2/7/14)")
    
    return {"ok": len(errors) == 0, "errors": errors}

# Modifier Registry
MODIFIER_REGISTRY = {
    "brain": {
        "id": "brain",
        "label": "Brain",
        "icon": "🧠",
        "tooltip": "Teach me this as one integrated mental model",
        "system_prompt": BRAIN_SYNTHESIS_SYSTEM_PROMPT,
        "validate": _validate_brain,
        "max_tokens": 2000,
        "context_fields": ["target_role", "experience_level", "time_horizon", "preferred_emphasis"]
    },
    "drill": {
        "id": "drill",
        "label": "Drill",
        "icon": "🎯",
        "tooltip": "Turn notes into STAR practice prompts + probes",
        "system_prompt": INTERVIEW_DRILL_SYSTEM_PROMPT,
        "validate": _validate_interview_drill,
        "max_tokens": 3000,
        "context_fields": ["target_role", "seniority_target", "preferred_emphasis"]
    },
    "labs": {
        "id": "labs",
        "label": "Labs",
        "icon": "🧪",
        "tooltip": "Generate 3 hands-on mini-labs with success checks",
        "system_prompt": MINI_LAB_SYSTEM_PROMPT,
        "validate": _validate_mini_lab,
        "max_tokens": 3500,
        "context_fields": ["environment", "time_budget", "preferred_emphasis"]
    },
    "quiz": {
        "id": "quiz",
        "label": "Quiz",
        "icon": "🧩",
        "tooltip": "20-question flash recall quiz + answer key + spacing",
        "system_prompt": FLASH_QUIZ_SYSTEM_PROMPT,
        "validate": _validate_flash_quiz,
        "max_tokens": 3500,
        "context_fields": ["difficulty", "preferred_emphasis"]
    }
}

def build_user_prompt(modifier_id: str, notes_text: str, context: dict) -> str:
    """Build user prompt for a modifier based on its context fields"""
    
    if modifier_id == "brain":
        target_role = context.get("target_role", "Become fluent enough to apply these topics in real technical work and interviews")
        experience = context.get("experience_level", "Competent technical professional; wants integrated mental model")
        horizon = context.get("time_horizon", "Near-term learning + long-term retention")
        emphasis = context.get("preferred_emphasis", "")
        emphasis_line = f"- Preferred emphasis (optional): {emphasis}" if emphasis else "- Preferred emphasis (optional): (none specified)"
        
        return f"""Learner context:
- Target role or outcome: {target_role}
- Current experience level (1–2 lines): {experience}
- Time horizon: {horizon}
{emphasis_line}

Raw notes to synthesize:
{notes_text}"""

    elif modifier_id == "drill":
        target_role = context.get("target_role", "Security Engineering / Technical consulting")
        seniority = context.get("seniority_target", "mid-senior")
        emphasis = context.get("preferred_emphasis", "")
        
        return f"""Role target: {target_role}
Seniority target: {seniority}
Constraints: {emphasis if emphasis else "(none)"}

Raw notes:
{notes_text}"""

    elif modifier_id == "labs":
        environment = context.get("environment", "AWS account available")
        time_budget = context.get("time_budget", "2-3 hours per lab")
        emphasis = context.get("preferred_emphasis", "")
        
        return f"""Environment: {environment}
Time budget: {time_budget}
Preferred emphasis: {emphasis if emphasis else "(none)"}

Raw notes:
{notes_text}"""

    elif modifier_id == "quiz":
        difficulty = context.get("difficulty", "interview-ready")
        emphasis = context.get("preferred_emphasis", "")
        
        return f"""Difficulty: {difficulty}
Preferred emphasis: {emphasis if emphasis else "(none)"}

Raw notes:
{notes_text}"""
    
    return f"Raw notes:\n{notes_text}"

def run_modifier(modifier_id: str, notes_text: str, context: dict = None) -> tuple:
    """
    Run a modifier from the registry.
    Returns: (response_text, token_info_dict) or (error_message, None)
    """
    import time as time_module
    
    if modifier_id not in MODIFIER_REGISTRY:
        return f"Unknown modifier: {modifier_id}", None
    
    modifier = MODIFIER_REGISTRY[modifier_id]
    context = context or {}
    start_time = time_module.time()
    retries = 0
    
    debug_log("MODIFIER_RUN", f"Running modifier: {modifier_id}", {
        "notes_length": len(notes_text),
        "context_keys": list(context.keys())
    })
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or api_key == "your_openai_api_key_here":
        return "• API key not configured\n• Please add your OpenAI API key to .env file", None
    
    system_prompt = modifier["system_prompt"]
    user_prompt = build_user_prompt(modifier_id, notes_text, context)
    
    try:
        client = OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_completion_tokens=modifier["max_tokens"],
            temperature=0.4
        )
        
        answer = response.choices[0].message.content
        token_info = {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
            "model": DEFAULT_MODEL
        }
        
        # Validate output
        validation = modifier["validate"](answer)
        
        # If validation fails, retry once with correction
        if not validation["ok"] and retries < 1:
            retries += 1
            debug_log("MODIFIER_RETRY", f"Validation failed, retrying", {
                "errors": validation["errors"]
            })
            
            correction_suffix = "\n\nCORRECTION NEEDED:\n" + "\n".join(f"- {e}" for e in validation["errors"])
            
            retry_response = client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt + correction_suffix}
                ],
                max_completion_tokens=modifier["max_tokens"],
                temperature=0.3
            )
            
            answer = retry_response.choices[0].message.content
            token_info["input_tokens"] += retry_response.usage.prompt_tokens
            token_info["output_tokens"] += retry_response.usage.completion_tokens
            token_info["total_tokens"] += retry_response.usage.total_tokens
        
        # Special post-processing for Brain (collapse paragraphs)
        if modifier_id == "brain":
            answer = re.sub(r'\n\s*\n', ' ', answer)
            answer = re.sub(r'\s+', ' ', answer).strip()
        
        latency_ms = int((time_module.time() - start_time) * 1000)
        
        # Log invocation
        _log_modifier_invocation(
            modifier_id=modifier_id,
            chars_in=len(notes_text),
            chars_out=len(answer),
            selected_text_used=context.get("_selected_text_used", False),
            model=DEFAULT_MODEL,
            latency_ms=latency_ms,
            retries=retries,
            status="success"
        )
        
        # Save backup
        save_api_response_backup(
            f"MODIFIER_{modifier_id.upper()}",
            notes_text[:200],
            answer,
            token_info["input_tokens"],
            token_info["output_tokens"],
            token_info["total_tokens"],
            token_info["model"]
        )
        
        return answer, token_info
        
    except Exception as e:
        latency_ms = int((time_module.time() - start_time) * 1000)
        _log_modifier_invocation(
            modifier_id=modifier_id,
            chars_in=len(notes_text),
            selected_text_used=context.get("_selected_text_used", False),
            model=DEFAULT_MODEL,
            latency_ms=latency_ms,
            retries=retries,
            status="error",
            error_code=type(e).__name__
        )
        debug_log("MODIFIER_ERROR", f"Modifier failed: {str(e)}")
        return f"• Error: {str(e)}", None

def save_modifier_output(modifier_id: str, output: str) -> str:
    """Save modifier output to Augmentation folder"""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"{timestamp}_{modifier_id}.txt"
    filepath = os.path.join(AUGMENTATION_DIR, filename)
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(output)
        debug_log("MODIFIER_SAVE", f"Saved modifier output", {"path": filepath})
        return filepath
    except Exception as e:
        debug_log("MODIFIER_SAVE_ERROR", f"Failed to save: {str(e)}")
        return None


def save_api_response_backup(response_type: str, prompt_preview: str, response_text: str, 
                              input_tokens: int, output_tokens: int, total_tokens: int, model: str):
    """Save API response to backup file with token usage"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cost = estimate_cost(input_tokens, output_tokens, model)
    backup_entry = f"""
{'='*80}
TIMESTAMP: {timestamp}
TYPE: {response_type}
MODEL: {model}
TOKENS: Input={input_tokens} | Output={output_tokens} | Total={total_tokens} | Est. Cost: {format_cost(cost)}
PROMPT PREVIEW: {prompt_preview[:200]}...
{'='*80}
RESPONSE:
{response_text}
{'='*80}

"""
    try:
        with open(TOKEN_BACKUP_FILE, "a", encoding="utf-8") as f:
            f.write(backup_entry)
        debug_log("BACKUP", f"API response saved to backup file", {
            "type": response_type,
            "tokens": total_tokens,
            "cost": format_cost(cost)
        })
    except Exception as e:
        debug_log("BACKUP_ERROR", f"Failed to save backup: {str(e)}")


def brain_synthesis(notes_text: str, target_role: str = None, experience_level: str = None,
                    time_horizon: str = None, preferred_emphasis: str = None) -> tuple:
    """
    Call OpenAI API with Brain synthesis prompt to create learning-optimized single paragraph.
    
    Returns: (response_text, token_info_dict) or (error_message, None)
    """
    debug_log("BRAIN_SYNTHESIS", "Starting brain synthesis", {
        "notes_length": len(notes_text),
        "notes_preview": notes_text[:100] + "..." if len(notes_text) > 100 else notes_text
    })
    
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key or api_key == "your_openai_api_key_here":
        debug_log("BRAIN_ERROR", "No valid API key found in .env file")
        return "• API key not configured\n• Please add your OpenAI API key to .env file", None
    
    # Set defaults for learner context
    if not target_role:
        target_role = "Become fluent enough to apply these topics in real technical work and interviews"
    if not experience_level:
        experience_level = "Competent technical professional; wants integrated mental model"
    if not time_horizon:
        time_horizon = "Near-term learning + long-term retention"
    if not preferred_emphasis:
        preferred_emphasis = ""
    
    # Build user prompt
    emphasis_line = f"- Preferred emphasis (optional): {preferred_emphasis}" if preferred_emphasis else "- Preferred emphasis (optional): (none specified)"
    
    user_prompt = f"""Learner context:
- Target role or outcome: {target_role}
- Current experience level (1–2 lines): {experience_level}
- Time horizon: {time_horizon}
{emphasis_line}

Raw notes to synthesize:
{notes_text}"""
    
    try:
        debug_log("BRAIN_SYNTHESIS", "Sending request to OpenAI")
        client = OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": BRAIN_SYNTHESIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            max_completion_tokens=2000,
            temperature=0.4
        )
        
        answer = response.choices[0].message.content
        
        # Extract token usage
        token_info = {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
            "model": DEFAULT_MODEL
        }
        
        debug_log("BRAIN_SYNTHESIS", "Response received", {
            "response_length": len(answer),
            "tokens": token_info
        })
        
        # Apply correctness gates
        answer, retried = _apply_brain_correctness_gates(client, api_key, answer, user_prompt, token_info)
        
        # Save backup
        save_api_response_backup(
            "BRAIN_SYNTHESIS",
            notes_text[:200],
            answer,
            token_info["input_tokens"],
            token_info["output_tokens"],
            token_info["total_tokens"],
            token_info["model"]
        )
        
        return answer, token_info
        
    except Exception as e:
        debug_log("BRAIN_ERROR", f"API call failed: {str(e)}", {"exception": str(e)})
        return f"• Error: {str(e)}", None


def _apply_brain_correctness_gates(client, api_key: str, answer: str, user_prompt: str, token_info: dict) -> tuple:
    """
    Apply correctness gates to Brain synthesis output.
    Returns (corrected_answer, was_retried)
    """
    import re
    
    retried = False
    
    # Gate A: Output is one paragraph only (no blank lines)
    if '\n\n' in answer or '\n \n' in answer:
        debug_log("BRAIN_GATE", "Gate A failed: multiple paragraphs detected, collapsing")
        # Post-process: replace multiple whitespace line breaks with single spaces
        answer = re.sub(r'\n\s*\n', ' ', answer)
        answer = re.sub(r'\s+', ' ', answer).strip()
    
    # Gate B: No headings, bullets, or numbered lists
    has_bullets = bool(re.search(r'^[\s]*[-•*]\s', answer, re.MULTILINE))
    has_numbers = bool(re.search(r'^[\s]*\d+[\.\)]\s', answer, re.MULTILINE))
    has_headings = bool(re.search(r'^#{1,6}\s|^[A-Z][A-Z\s]+:$', answer, re.MULTILINE))
    
    if has_bullets or has_numbers or has_headings:
        debug_log("BRAIN_GATE", "Gate B failed: formatting detected, requesting correction")
        try:
            correction_response = client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": BRAIN_SYNTHESIS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt + "\n\nReminder: one paragraph only; no headings/bullets/lists."}
                ],
                max_completion_tokens=2000,
                temperature=0.3
            )
            answer = correction_response.choices[0].message.content
            token_info["input_tokens"] += correction_response.usage.prompt_tokens
            token_info["output_tokens"] += correction_response.usage.completion_tokens
            token_info["total_tokens"] += correction_response.usage.total_tokens
            retried = True
            # Re-apply Gate A
            answer = re.sub(r'\n\s*\n', ' ', answer)
            answer = re.sub(r'\s+', ' ', answer).strip()
        except Exception as e:
            debug_log("BRAIN_GATE_ERROR", f"Correction request failed: {str(e)}")
    
    # Gate C: At least 6 occurrences of "Quick check:"
    quick_check_count = answer.lower().count("quick check:")
    if quick_check_count < 6 and not retried:
        debug_log("BRAIN_GATE", f"Gate C failed: only {quick_check_count} Quick checks, requesting more")
        try:
            correction_response = client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": BRAIN_SYNTHESIS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt + "\n\nInclude at least 6 'Quick check: …?' prompts spread throughout."}
                ],
                max_completion_tokens=2000,
                temperature=0.3
            )
            answer = correction_response.choices[0].message.content
            token_info["input_tokens"] += correction_response.usage.prompt_tokens
            token_info["output_tokens"] += correction_response.usage.completion_tokens
            token_info["total_tokens"] += correction_response.usage.total_tokens
            retried = True
            # Re-apply Gate A
            answer = re.sub(r'\n\s*\n', ' ', answer)
            answer = re.sub(r'\s+', ' ', answer).strip()
        except Exception as e:
            debug_log("BRAIN_GATE_ERROR", f"Correction request failed: {str(e)}")
    
    return answer, retried


def ask_openai(prompt: str, response_format: str = "default") -> str:
    """
    Call OpenAI API with a user prompt and return response.
    
    response_format options:
    - "default": Concise answer optimized for comprehension
    - "single": Single sentence reply only
    - "headers": Headers and bullets format (max 10 words each)
    - "andragogy": Andragogy-optimized paragraph
    - "plain": Plain English explanation for comprehension
    - "detailed": Full headings/bullets format (legacy)
    """
    debug_log("OPENAI_ASK", "Starting quick question", {
        "prompt_length": len(prompt),
        "format": response_format,
        "prompt_preview": prompt[:100] + "..." if len(prompt) > 100 else prompt
    })
    
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key or api_key == "your_openai_api_key_here":
        debug_log("OPENAI_ERROR", "No valid API key found in .env file")
        return "• API key not configured\n• Please add your OpenAI API key to .env file"
    
    # Select system prompt based on format
    if response_format == "single":
        system_prompt = """Answer in exactly ONE sentence. Be accurate but extremely concise. No bullet points, no lists, no elaboration."""
        max_tokens = 100
    elif response_format == "context":
        system_prompt = """The user is studying and doesn't understand something. They likely missed or forgot prerequisite context from earlier in their lesson.

Your job is to:
1. Identify what prerequisite knowledge/concepts are needed to understand this
2. Briefly explain those prerequisites first (the "missing context")
3. Then explain the actual content, building on that foundation
4. Connect everything together so it makes sense

FORMAT:
📋 WHAT YOU NEED TO KNOW FIRST:
• [Prerequisite concept 1 - brief explanation]
• [Prerequisite concept 2 - brief explanation]

🔗 HOW IT CONNECTS:
[Explain how the prerequisites relate to what they're trying to understand]

✅ NOW THE ANSWER:
[Clear explanation that builds on the prerequisites]

RULES:
- Assume they're intelligent but missing context, not stupid
- Be thorough with prerequisites - this is the key value you provide
- Use plain language throughout
- Make connections explicit"""
        max_tokens = 800
    elif response_format == "headers":
        system_prompt = """Answer using headers and bullets. STRICT RULES:
- Each bullet: maximum 10 words
- Use clear section headers (3-5 words each)
- No paragraphs, only bullets under headers
- Be direct and scannable

Example format:
MAIN CONCEPT
• First key point (10 words max)
• Second key point (10 words max)

HOW IT WORKS
• Process step one (10 words max)
• Process step two (10 words max)"""
        max_tokens = 500
    elif response_format == "andragogy":
        system_prompt = """Create ONE paragraph optimized per andragogy (adult learning) principles:

ANDRAGOGY REQUIREMENTS:
- Connect to real-world application immediately
- Explain WHY before HOW (purpose drives adult learning)
- Use concrete examples adults can relate to
- Acknowledge prior knowledge/experience
- Show practical utility clearly
- Use plain language, avoid jargon (or define it)
- Structure: Problem → Solution → Application

Write a single, well-structured paragraph (5-8 sentences) that an adult learner can immediately understand and apply. Start with relevance, explain the concept, provide context, and end with actionable insight."""
        max_tokens = 400
    elif response_format == "plain":
        system_prompt = """Explain this in plain English for someone who wants to truly understand it.

RULES:
- Prioritize COMPREHENSION over brevity - take the space you need to explain clearly
- Use everyday words; if you must use a technical term, immediately define it in parentheses
- Use analogies and comparisons to familiar concepts
- Break complex ideas into simple, digestible pieces
- Explain the "why" and "how" - don't just state facts
- Assume intelligence but no prior knowledge of this specific topic
- Write like you're explaining to a curious friend over coffee
- It's okay to be a little longer if it means being understood

Your goal is understanding, not impressiveness. Make the reader feel smarter, not dumber."""
        max_tokens = 600
    elif response_format == "detailed":
        system_prompt = """You are a learning optimization assistant. Answer questions with structured, scannable responses.

OUTPUT STRUCTURE:

⚡ TL;DR
One sentence answer with the **key word** bolded.

🎯 KEY POINTS
• [Important point - 7 words max]
• [Another point - 7 words max]
• [Third point if needed]

📚 DETAILS
[TOPIC]
• Concise explanation
• Supporting detail

💡 SO WHAT?
• Why this matters
• How to apply it

🔤 GLOSSARY (if technical terms used)
• Term → Brief definition

RULES:
- Maximum 7 words per bullet
- Use fragments, not full sentences
- Skip filler content"""
        max_tokens = 800
    else:  # default
        system_prompt = """Answer concisely but completely. Optimize for quick comprehension:
- Lead with the direct answer
- Use bullet points for multiple items
- Keep explanations brief (1-2 sentences max)
- Bold **key terms** for scannability
- Skip unnecessary context or caveats"""
        max_tokens = 400
    
    try:
        debug_log("OPENAI_ASK", f"Sending request with format: {response_format}")
        client = OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_tokens=max_tokens,
            temperature=0.3
        )
        
        answer = response.choices[0].message.content
        
        # Token tracking and backup
        token_info = {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens
        }
        debug_log("OPENAI_ASK", "Response received", {
            "response_length": len(answer),
            "tokens": token_info
        })
        
        # Save backup
        save_api_response_backup(
            f"QUICK_QUESTION_{response_format.upper()}",
            prompt[:200],
            answer,
            token_info["input_tokens"],
            token_info["output_tokens"],
            token_info["total_tokens"],
            "gpt-4o-mini"
        )
        
        return answer
        
    except Exception as e:
        debug_log("OPENAI_ERROR", f"API call failed: {str(e)}", {"exception": str(e)})
        return f"• Error: {str(e)}"


def shorten_text(text: str, level: str = "shorten") -> tuple:
    """
    Shorten text using AI while preserving key information.
    
    level options:
    - "shorten": Reduce by ~25%, cover everything
    - "more": Reduce by ~50%, keep as much meaning as possible
    - "more!!!": Reduce by ~75%, bare minimum to get the message across
    
    Returns: (shortened_text, token_info) or (error_message, None)
    """
    debug_log("SHORTEN", f"Shortening text with level: {level}", {
        "text_length": len(text),
        "level": level
    })
    
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key or api_key == "your_openai_api_key_here":
        debug_log("SHORTEN_ERROR", "No valid API key found")
        return "• API key not configured\n• Please add your OpenAI API key to .env file", None
    
    # Select approach based on shortening level
    if level == "shorten":
        system_prompt = """You are a text condenser. Your job is to shorten text by approximately 25% while covering ALL the same information.

TECHNIQUES TO USE:
- Remove redundant words and phrases
- Combine related sentences
- Use more concise wording
- Remove filler phrases like "In fact," "Actually," "It's worth noting that"
- Convert verbose explanations to bullet points where appropriate

RULES:
- Cover ALL original points - nothing should be lost
- Keep the same meaning and tone
- Preserve key technical terms and important details
- Output should be ~75% the length of the input"""
        target_ratio = 0.75
    elif level == "more":
        system_prompt = """You are a text condenser. Your job is to shorten text by approximately 50% while preserving as much of the original meaning as possible.

TECHNIQUES TO USE:
- Convert paragraphs to concise bullet points
- Merge related ideas into single statements
- Remove examples that aren't essential (keep the best one if needed)
- Condense explanations to their core message
- Use shorter synonyms and tighter phrasing
- Remove any tangential information

RULES:
- Maintain the core message and key takeaways
- Keep essential technical details and terms
- Prioritize the most important information
- Output should be ~50% the length of the input"""
        target_ratio = 0.50
    else:  # more!!!
        system_prompt = """You are an extreme text condenser. Your job is to shorten text by approximately 75%, pulling out all the stops to get the message across in the shortest way possible.

TECHNIQUES TO USE:
- Convert everything to ultra-short bullet points (3-7 words each)
- Keep ONLY the absolutely essential information
- Use abbreviations where clear (e.g., "w/" for "with", "→" for "leads to")
- Strip all examples unless critical
- Remove all context that isn't essential
- Use fragments instead of full sentences
- Merge multiple related points into single bullets

RULES:
- Preserve the CORE message above all else
- No fluff, no filler, no politeness
- Technical accuracy must be maintained
- Every word must earn its place
- Output should be ~25% the length of the input
- Aim for maximum information density"""
        target_ratio = 0.25
    
    try:
        client = OpenAI(api_key=api_key)
        
        # Calculate target length
        word_count = len(text.split())
        target_words = int(word_count * target_ratio)
        
        user_prompt = f"""Shorten the following text to approximately {target_words} words (currently {word_count} words):

---
{text}
---

OUTPUT ONLY THE SHORTENED VERSION. No explanations or preamble."""
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=max(500, int(len(text.split()) * target_ratio * 2)),  # Allow some buffer
            temperature=0.3
        )
        
        shortened = response.choices[0].message.content
        
        token_info = {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
            "model": "gpt-4o-mini",
            "original_words": word_count,
            "shortened_words": len(shortened.split()),
            "reduction_percent": round((1 - len(shortened.split()) / word_count) * 100, 1) if word_count > 0 else 0
        }
        
        debug_log("SHORTEN_COMPLETE", f"Text shortened", token_info)
        
        # Save backup
        save_api_response_backup(
            f"SHORTEN_{level.upper().replace('!', '')}",
            text[:200],
            shortened,
            token_info["input_tokens"],
            token_info["output_tokens"],
            token_info["total_tokens"],
            "gpt-4o-mini"
        )
        
        return shortened, token_info
        
    except Exception as e:
        debug_log("SHORTEN_ERROR", f"API call failed: {str(e)}")
        return f"• Error: {str(e)}", None


def get_simplified_explanations(text: str) -> list:
    """
    Call OpenAI API to get three progressively simpler explanations of the text.
    Returns a list of 3 explanations: [simple, simpler, simplest].
    Only one API call is made for efficiency.
    """
    debug_log("SIMPLIFY", "Getting simplified explanations", {"text_length": len(text)})
    
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key or api_key == "your_openai_api_key_here":
        debug_log("SIMPLIFY_ERROR", "No valid API key found")
        return ["API key not configured. Please add your OpenAI API key to .env file."] * 3
    
    system_prompt = """You are a master teacher who can explain complex concepts at different levels of simplicity.

The user will provide text they don't understand. You must provide THREE different explanations, each progressively simpler and more thoroughly explained than the last.

Format your response EXACTLY like this (use these exact delimiters):

===EXPLANATION 1===
[First explanation - clear and accessible, using plain language]

===EXPLANATION 2===
[Second explanation - even simpler, breaking down concepts further, using analogies]

===EXPLANATION 3===
[Third explanation - the simplest possible version, as if explaining to someone with zero background knowledge, using everyday comparisons]

RULES:
- Each explanation should be a single paragraph (4-8 sentences)
- Use progressively simpler vocabulary
- Add more context and analogies with each level
- Never use jargon without immediately explaining it
- Focus on comprehension over brevity"""
    
    try:
        client = OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"The user does not understand the following text. Please explain it in three progressively simpler ways:\n\n{text}"}
            ],
            max_tokens=1500,
            temperature=0.5
        )
        
        answer = response.choices[0].message.content
        
        # Parse the three explanations
        explanations = []
        parts = answer.split("===EXPLANATION")
        for part in parts[1:]:  # Skip empty first split
            # Remove the number and delimiter
            if "===" in part:
                content = part.split("===", 1)[1].strip()
                explanations.append(content)
        
        # Ensure we have exactly 3 explanations
        while len(explanations) < 3:
            explanations.append(explanations[-1] if explanations else "Could not generate explanation.")
        explanations = explanations[:3]
        
        # Token tracking
        token_info = {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens
        }
        debug_log("SIMPLIFY", "Explanations generated", {
            "num_explanations": len(explanations),
            "tokens": token_info
        })
        
        # Save backup
        save_api_response_backup(
            "SIMPLIFIED_EXPLANATIONS",
            text[:200],
            answer,
            token_info["input_tokens"],
            token_info["output_tokens"],
            token_info["total_tokens"],
            "gpt-4o-mini"
        )
        
        return explanations
        
    except Exception as e:
        debug_log("SIMPLIFY_ERROR", f"API call failed: {str(e)}")
        return [f"Error: {str(e)}"] * 3


def get_summary(text: str) -> str:
    """Call OpenAI API to summarize text optimized for quick comprehension and learning"""
    debug_log("OPENAI", "Starting text summarization", {"text_length": len(text), "text_preview": text[:100] + "..."})
    
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key or api_key == "your_openai_api_key_here":
        debug_log("OPENAI_ERROR", "No valid API key found in .env file")
        return "• API key not configured\n• Please add your OpenAI API key to .env file"
    
    try:
        debug_log("OPENAI", "Initializing OpenAI client")
        client = OpenAI(api_key=api_key)
        
        debug_log("OPENAI", "Sending request to OpenAI API (gpt-4o-mini)")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """You are a learning optimization assistant. Create summaries that maximize retention and comprehension for exam preparation.

OUTPUT STRUCTURE (use exact format):

📌 TITLE: [Concise 4-6 word title capturing the main topic]

⚡ TL;DR
One sentence capturing the core insight.

🎯 KEY TAKEAWAYS
• [Most important point - 7 words max]
  → In plain English: [same idea explained simply, no jargon]
• [Second key point - 7 words max]
  → In plain English: [same idea explained simply, no jargon]
• [Third key point - 7 words max]
  → In plain English: [same idea explained simply, no jargon]

📚 TOPIC BREAKDOWN
[TOPIC NAME - expand any acronyms like "API (Application Programming Interface)"]
💭 Think of it like: [relatable metaphor/analogy using everyday objects]
🌍 Real example: [ACTUAL use case of THIS technology - e.g., "Netflix uses ECS to deploy microservices" or "Banks use S3 to store transaction logs"]
• HOW it works: [mechanism/process - be specific]
• WHY it matters: [purpose/benefit]
• KEY DETAIL: [specific fact, number, or distinction]

[NEXT TOPIC - expand any acronyms in parentheses]
💭 Think of it like: [relatable metaphor/analogy using everyday objects]
🌍 Real example: [ACTUAL use case of THIS technology - name real companies/industries that use it]
• HOW it works: [mechanism/process]
• WHY it matters: [purpose/benefit]
• KEY DETAIL: [distinguishing characteristic]

💡 SO WHAT?
• Why this matters to you
• How to apply this knowledge

🔤 GLOSSARY
• Term → Brief definition (8 words max)
• Acronym → Expansion and meaning

RULES:
- Start with a clear TITLE at the top
- Maximum 7 words per bullet
- Use fragments, not full sentences
- Prioritize actionable insights
- Skip filler content entirely
- Bold the single most important word in TL;DR using **word**
- Each topic MUST have both a metaphor (💭) AND a real-world example (🌍) for better comprehension
- Metaphors (💭) should be everyday analogies that make abstract concepts concrete (e.g., "like a filing cabinet")
- Real examples (🌍) must be ACTUAL uses of the technology itself - name specific companies, industries, or concrete use cases (e.g., "Spotify uses this for playlist recommendations" NOT "like a restaurant adjusting staff")
- NEVER use another metaphor for the real example - it must be a literal real-world application
- ALWAYS expand acronyms in parentheses when they appear in headings/topic names (e.g., "REST API (Representational State Transfer Application Programming Interface)")

CRITICAL FOR EXAM PREP:
- Always include HOW something works (the mechanism), not just WHAT it does
- Include specific numbers, percentages, timeframes when mentioned
- Capture decision criteria (when to use X vs Y)
- Note any limitations, caveats, or "catches"
- Include technical distinctions that could appear in exam questions
- Expand all acronyms in topic headings so readers immediately understand what's being discussed"""
                },
                {
                    "role": "user",
                    "content": f"Create a learning-optimized summary:\n\n{text}"
                }
            ],
            max_tokens=1000,
            temperature=0.3
        )
        
        summary = response.choices[0].message.content
        
        # Token tracking and backup
        token_info = {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens
        }
        debug_log("OPENAI", "Summary received successfully", {
            "summary_length": len(summary),
            "tokens": token_info
        })
        
        # Save backup
        save_api_response_backup(
            "SUMMARY",
            text[:200],
            summary,
            token_info["input_tokens"],
            token_info["output_tokens"],
            token_info["total_tokens"],
            "gpt-4o-mini"
        )
        
        return summary
        
    except Exception as e:
        debug_log("OPENAI_ERROR", f"API call failed: {str(e)}", {"exception": str(e)})
        return f"• Error getting summary: {str(e)}"

# ==================== FIXATION POINT CALCULATION ====================

def get_fixation_point(word: str) -> int:
    """
    Calculate the optimal fixation point for a word.
    This is typically slightly left of center, where the eye naturally focuses.
    """
    length = len(word)
    
    if length <= 1:
        fixation = 0
    elif length <= 4:
        fixation = 1
    elif length <= 8:
        fixation = 2
    else:
        fixation = length // 3
    
    debug_log("FIXATION", f"Calculated fixation point for word", {
        "word": word,
        "length": length,
        "fixation_index": fixation
    })
    
    return fixation


def setup_textbox_tab_navigation(textbox, next_widget, prev_widget=None, on_focus_next=None, on_focus_prev=None):
    """
    Set up Tab navigation for a CTkTextbox to properly move focus to buttons.
    
    Args:
        textbox: The CTkTextbox widget
        next_widget: Widget to focus on Tab
        prev_widget: Widget to focus on Shift+Tab (optional, defaults to next_widget)
        on_focus_next: Optional callback when moving to next widget
        on_focus_prev: Optional callback when moving to prev widget
    """
    if prev_widget is None:
        prev_widget = next_widget
    
    def on_tab(event):
        if on_focus_next:
            on_focus_next()
        next_widget.focus_set()
        return "break"
    
    def on_shift_tab(event):
        if on_focus_prev:
            on_focus_prev()
        prev_widget.focus_set()
        return "break"
    
    # Bind to the textbox - CTkTextbox forwards events to internal widget
    textbox.bind("<Tab>", on_tab)
    textbox.bind("<Shift-Tab>", on_shift_tab)
    
    # Also try to bind to the internal textbox widget if accessible
    try:
        internal = textbox._textbox
        internal.bind("<Tab>", on_tab)
        internal.bind("<Shift-Tab>", on_shift_tab)
    except AttributeError:
        pass


def setup_button_focus_visuals(buttons, default_colors=None):
    """
    Set up focus visual feedback for a list of buttons.
    
    Args:
        buttons: List of (button, identifier) tuples or just buttons
        default_colors: Dict mapping identifier to default fg_color, or single color string
    
    Returns:
        Functions (on_focus, clear_focus) to manage focus visuals
    """
    if default_colors is None:
        default_colors = "#4a4a4a"
    
    # Normalize to list of (button, color) tuples
    button_colors = []
    for item in buttons:
        if isinstance(item, tuple):
            btn, identifier = item
            if isinstance(default_colors, dict):
                color = default_colors.get(identifier, "#4a4a4a")
            else:
                color = default_colors
            button_colors.append((btn, color))
        else:
            color = default_colors if isinstance(default_colors, str) else "#4a4a4a"
            button_colors.append((item, color))
    
    def clear_all_focus():
        for btn, _ in button_colors:
            btn.configure(border_width=0)
    
    def set_focus(button):
        clear_all_focus()
        button.configure(border_width=2, border_color="#FFFFFF")
    
    return set_focus, clear_all_focus


# ==================== STRATEGY AI ANALYSIS SYSTEM ====================

# Stockbot directory path
STOCKBOT_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "Stockbot")

# Strategy Analysis Data Files - pointing to Stockbot directory
STRATEGY_CONFIG_FILE = os.path.join(STOCKBOT_DIR, "best_params.json")
STOCKBOT_SETTINGS_FILE = os.path.join(STOCKBOT_DIR, "stockbot_settings.json")
EFFECTIVE_PARAMS_FILE = os.path.join(STOCKBOT_DIR, "effective_params.json")
STRATEGY_ANALYSIS_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy_analysis_log.txt")

# Default Strategy Parameters
DEFAULT_STRATEGY_PARAMS = {
    "PROFIT_TARGET_PERCENT": 2.0,
    "STOP_LOSS_PERCENT": 1.0,
    "TRAILING_STOP_PERCENT": 0.5,
    "DEPLOYABLE_CAPITAL_PERCENT": 80.0,
    "MAX_POSITIONS": 5,
    "MEDIUM_CONFIDENCE_ALLOCATION": 0.5,
    "DAILY_LOSS_CIRCUIT_BREAKER_PCT": 3.0,
    "SMALL_CAP_MIN_PRICE": 5.0,
    "SMALL_CAP_MAX_PRICE": 50.0,
    "SMALL_CAP_MIN_VOLUME": 500000,
    "ATR_THRESHOLD_MIN": 0.5,
    "ATR_THRESHOLD_MAX": 5.0,
    "VOLATILITY_FILTER_MIN": 1.5,
    "VOLATILITY_FILTER_MAX": 8.0,
    "MIN_RELATIVE_VOLUME": 1.2,
    "GAP_THRESHOLD_PERCENT": 2.0
}

# Default Backtest Metrics Structure
DEFAULT_BACKTEST_METRICS = {
    "total_pnl": 0.0,
    "avg_daily_pnl": 0.0,
    "win_rate": 0.0,
    "avg_win": 0.0,
    "avg_loss": 0.0,
    "risk_reward_ratio": 0.0,
    "expectancy_per_trade": 0.0,
    "trades_per_day": 0.0,
    "exposure_percent": 0.0,
    "capital_efficiency_ratio": 0.0,
    "max_drawdown": 0.0,
    "profit_factor": 0.0,
    "stop_loss_exits": 0,
    "target_exits": 0,
    "trailing_stop_exits": 0,
    "backtest_days": 50
}

# Default Trade Ledger Metrics Structure
DEFAULT_TRADE_METRICS = {
    "avg_mfe": 0.0,
    "avg_mae": 0.0,
    "avg_time_in_trade_minutes": 0.0,
    "potential_captured_percent": 0.0,
    "exit_reasons": {"stop_loss": 0, "target": 0, "trailing": 0, "time": 0, "manual": 0},
    "avg_position_size": 0.0,
    "total_trades": 0
}

# Default Regime Metrics Structure
DEFAULT_REGIME_METRICS = {
    "avg_daily_atr": 0.0,
    "atr_percentile_25": 0.0,
    "atr_percentile_75": 0.0,
    "avg_volatility_percentile": 50.0,
    "avg_gap_size_percent": 0.0,
    "trend_days_percent": 50.0,
    "chop_days_percent": 50.0,
    "high_volume_days_percent": 50.0,
    "low_volume_days_percent": 50.0
}

# Default Capital Efficiency Metrics
DEFAULT_CAPITAL_METRICS = {
    "avg_deployed_capital_percent": 0.0,
    "avg_idle_capital_percent": 0.0,
    "exposure_pnl_correlation": 0.0,
    "first_trade_avg_pnl": 0.0,
    "later_trade_avg_pnl": 0.0,
    "position_rank_pnl_correlation": 0.0
}

STRATEGY_ANALYSIS_SYSTEM_PROMPT = """You are an elite quantitative trading strategist analyzing a live trading strategy that has been validated for structural parity between backtester and live execution.

OBJECTIVE:
Maximize daily P&L while maintaining realistic slippage, no commission modeling, no leverage, and no forward-looking bias.

REQUIRED ANALYSIS STEPS:

1. DECOMPOSE EXPECTANCY:
   - Win rate analysis
   - Average win/loss sizing
   - Risk:Reward ratio evaluation
   - Trades per day impact
   - Calculate expected value per trade

2. IDENTIFY STRUCTURAL BOTTLENECKS:
   - Are winners being cut too early?
   - Are stops too tight causing unnecessary losses?
   - Is the trailing stop truncating large trends?
   - Is trade frequency too high relative to edge?
   - Position sizing efficiency

3. PERFORM MFE/MAE ANALYSIS:
   - Percentage of potential captured
   - How much larger average winners could be
   - Whether widening stop increases expectancy
   - Optimal exit timing analysis

4. EVALUATE CAPITAL EFFICIENCY:
   - Is exposure limiting growth?
   - Is MAX_POSITIONS capping upside?
   - Are late trades (position 4-5) low expectancy?
   - Correlation between exposure and returns

5. SEGMENT BY VOLATILITY REGIME:
   - Which days drive profit?
   - Which days destroy profit?
   - Would dynamic parameter switching help?
   - ATR-based adjustments

6. RECOMMEND QUANTIFIED ADJUSTMENTS:
   - Suggested trailing stop % change (with math)
   - Suggested stop-loss change (with math)
   - Suggested target change (with math)
   - Suggested exposure adjustment
   - Suggested symbol filtering change
   - Suggested regime switching logic

7. ESTIMATE NEW PROJECTED DAILY P&L if adjustments applied

HARD RULES - DO NOT:
- Remove slippage modeling
- Remove settlement modeling
- Assume perfect fills
- Introduce data leakage
- Suggest unrealistic 2%+ daily returns without mathematical justification
- Recommend leverage or margin

OUTPUT FORMAT:
1. **Executive Summary** (3-4 sentences)
2. **Structural Weaknesses** (bulleted list with specific metrics)
3. **Missed Profit Opportunities** (quantified analysis)
4. **Ranked Adjustments** (numbered, with expected impact)
5. **Estimated Impact Per Adjustment** (table format)
6. **Risk Tradeoffs** (for each suggestion)
7. **Projected New Avg Daily P&L** (with confidence range)
8. **Implementation Priority** (what to change first)

Be specific with numbers. Show your math. Be conservative with projections."""


def _find_latest_stockbot_csv(pattern: str) -> str:
    """Find the most recent CSV file matching pattern in Stockbot directory"""
    import glob
    files = glob.glob(os.path.join(STOCKBOT_DIR, f"{pattern}*.csv"))
    if not files:
        return None
    # Sort by modification time, most recent first
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def load_strategy_config() -> dict:
    """Load strategy parameters from Stockbot's best_params.json"""
    try:
        if os.path.exists(STRATEGY_CONFIG_FILE):
            with open(STRATEGY_CONFIG_FILE, "r") as f:
                data = json.load(f)
                # Extract best_params if nested
                if "best_params" in data:
                    config = data["best_params"]
                else:
                    config = data
                debug_log("STRATEGY", f"Loaded strategy config from Stockbot: {STRATEGY_CONFIG_FILE}", 
                         {"params": list(config.keys())[:10]})
                return config
    except Exception as e:
        debug_log("STRATEGY_ERROR", f"Failed to load strategy config from Stockbot: {e}")
    return DEFAULT_STRATEGY_PARAMS.copy()


def save_strategy_config(config: dict):
    """Save strategy parameters - saves to local KISS directory to avoid modifying Stockbot"""
    local_config = os.path.join(os.path.dirname(os.path.abspath(__file__)), "suggested_params.json")
    try:
        with open(local_config, "w") as f:
            json.dump(config, f, indent=2)
        debug_log("STRATEGY", f"Saved suggested params to {local_config}")
    except Exception as e:
        debug_log("STRATEGY_ERROR", f"Failed to save strategy config: {e}")


def load_backtest_results() -> dict:
    """Load backtest results from Stockbot's daily CSV files"""
    try:
        # Find most recent daily CSV
        daily_csv = _find_latest_stockbot_csv("daily_")
        if not daily_csv:
            debug_log("STRATEGY", "No daily CSV found in Stockbot directory")
            return DEFAULT_BACKTEST_METRICS.copy()
        
        debug_log("STRATEGY", f"Loading backtest results from {daily_csv}")
        
        import csv
        daily_pnls = []
        total_trades = 0
        
        with open(daily_csv, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    pnl = float(row.get('pnl', 0))
                    trades = int(row.get('trades', 0))
                    daily_pnls.append(pnl)
                    total_trades += trades
                except (ValueError, TypeError):
                    continue
        
        if not daily_pnls:
            return DEFAULT_BACKTEST_METRICS.copy()
        
        # Calculate metrics
        total_pnl = sum(daily_pnls)
        avg_daily_pnl = total_pnl / len(daily_pnls) if daily_pnls else 0
        winning_days = [p for p in daily_pnls if p > 0]
        losing_days = [p for p in daily_pnls if p < 0]
        
        win_rate = (len(winning_days) / len(daily_pnls) * 100) if daily_pnls else 0
        avg_win = sum(winning_days) / len(winning_days) if winning_days else 0
        avg_loss = abs(sum(losing_days) / len(losing_days)) if losing_days else 0
        risk_reward = avg_win / avg_loss if avg_loss > 0 else 0
        
        # Calculate max drawdown
        cumulative = 0
        peak = 0
        max_drawdown = 0
        for pnl in daily_pnls:
            cumulative += pnl
            peak = max(peak, cumulative)
            drawdown = peak - cumulative
            max_drawdown = max(max_drawdown, drawdown)
        
        # Profit factor
        gross_profit = sum(winning_days) if winning_days else 0
        gross_loss = abs(sum(losing_days)) if losing_days else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        trades_per_day = total_trades / len(daily_pnls) if daily_pnls else 0
        expectancy = total_pnl / total_trades if total_trades > 0 else 0
        
        metrics = {
            "total_pnl": total_pnl,
            "avg_daily_pnl": avg_daily_pnl,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "risk_reward_ratio": risk_reward,
            "expectancy_per_trade": expectancy,
            "trades_per_day": trades_per_day,
            "exposure_percent": 0,  # Would need position data
            "capital_efficiency_ratio": total_pnl / 8000 if total_pnl else 0,  # Assuming $8k starting
            "max_drawdown": max_drawdown,
            "profit_factor": profit_factor,
            "stop_loss_exits": 0,  # Will be populated from ledger
            "target_exits": 0,
            "trailing_stop_exits": 0,
            "backtest_days": len(daily_pnls),
            "_source_file": os.path.basename(daily_csv)
        }
        
        debug_log("STRATEGY", f"Calculated backtest metrics from {len(daily_pnls)} days", metrics)
        return metrics
        
    except Exception as e:
        debug_log("STRATEGY_ERROR", f"Failed to load backtest results: {e}")
    return DEFAULT_BACKTEST_METRICS.copy()


def load_trade_ledger_metrics() -> dict:
    """Load trade ledger metrics from Stockbot's ledger CSV files"""
    try:
        # Find most recent ledger CSV
        ledger_csv = _find_latest_stockbot_csv("ledger_")
        if not ledger_csv:
            debug_log("STRATEGY", "No ledger CSV found in Stockbot directory")
            return DEFAULT_TRADE_METRICS.copy()
        
        debug_log("STRATEGY", f"Loading trade ledger from {ledger_csv}")
        
        import csv
        
        exit_reasons = {"stop_loss": 0, "target": 0, "trailing": 0, "time": 0, "manual": 0, "other": 0}
        position_sizes = []
        pnl_values = []
        sell_count = 0
        
        with open(ledger_csv, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    side = row.get('side', '').upper()
                    reason = row.get('reason', '').lower()
                    pnl = row.get('pnl', '')
                    qty = row.get('qty', 0)
                    price = row.get('price', 0)
                    
                    if side == 'SELL':
                        sell_count += 1
                        if pnl:
                            try:
                                pnl_values.append(float(pnl))
                            except:
                                pass
                        
                        # Categorize exit reason
                        if 'stop' in reason or 'adaptive_stop' in reason:
                            exit_reasons["stop_loss"] += 1
                        elif 'target' in reason or 'profit' in reason:
                            exit_reasons["target"] += 1
                        elif 'trail' in reason:
                            exit_reasons["trailing"] += 1
                        elif 'time' in reason or 'eod' in reason or 'late_day' in reason:
                            exit_reasons["time"] += 1
                        else:
                            exit_reasons["other"] += 1
                    
                    if side == 'BUY':
                        try:
                            pos_size = float(qty) * float(price)
                            position_sizes.append(pos_size)
                        except:
                            pass
                            
                except Exception as row_e:
                    continue
        
        # Calculate metrics
        avg_position_size = sum(position_sizes) / len(position_sizes) if position_sizes else 0
        winning_trades = [p for p in pnl_values if p > 0]
        losing_trades = [p for p in pnl_values if p < 0]
        
        metrics = {
            "total_trades": sell_count,
            "exit_reasons": exit_reasons,
            "avg_position_size": avg_position_size,
            "avg_mfe": 0,  # Would need intraday data
            "avg_mae": 0,  # Would need intraday data
            "avg_time_in_trade_minutes": 0,  # Would need timestamp parsing
            "potential_captured_percent": 0,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "avg_win_trade": sum(winning_trades) / len(winning_trades) if winning_trades else 0,
            "avg_loss_trade": abs(sum(losing_trades) / len(losing_trades)) if losing_trades else 0,
            "_source_file": os.path.basename(ledger_csv)
        }
        
        debug_log("STRATEGY", f"Calculated trade metrics from {sell_count} trades", metrics)
        return metrics
        
    except Exception as e:
        debug_log("STRATEGY_ERROR", f"Failed to load trade ledger: {e}")
    return DEFAULT_TRADE_METRICS.copy()


def load_regime_metrics() -> dict:
    """Load regime/market condition metrics - parsed from trade ledger ATR data"""
    try:
        # Try to extract ATR info from ledger entries
        ledger_csv = _find_latest_stockbot_csv("ledger_")
        if not ledger_csv:
            return DEFAULT_REGIME_METRICS.copy()
        
        import csv
        import re
        
        atr_values = []
        rvol_values = []
        
        with open(ledger_csv, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                reason = row.get('reason', '')
                # Parse ATR from reason like "Enhanced: Score=2.25, RVOL=2.0x, ATR=0.36%"
                atr_match = re.search(r'ATR=(\d+\.?\d*)%', reason)
                rvol_match = re.search(r'RVOL=(\d+\.?\d*)x', reason)
                
                if atr_match:
                    try:
                        atr_values.append(float(atr_match.group(1)))
                    except:
                        pass
                if rvol_match:
                    try:
                        rvol_values.append(float(rvol_match.group(1)))
                    except:
                        pass
        
        metrics = DEFAULT_REGIME_METRICS.copy()
        
        if atr_values:
            atr_values.sort()
            metrics["avg_daily_atr"] = sum(atr_values) / len(atr_values)
            idx_25 = int(len(atr_values) * 0.25)
            idx_75 = int(len(atr_values) * 0.75)
            metrics["atr_percentile_25"] = atr_values[idx_25] if idx_25 < len(atr_values) else 0
            metrics["atr_percentile_75"] = atr_values[idx_75] if idx_75 < len(atr_values) else 0
        
        if rvol_values:
            avg_rvol = sum(rvol_values) / len(rvol_values)
            high_vol = len([r for r in rvol_values if r > 2.0])
            metrics["high_volume_days_percent"] = (high_vol / len(rvol_values) * 100) if rvol_values else 50
            metrics["low_volume_days_percent"] = 100 - metrics["high_volume_days_percent"]
        
        debug_log("STRATEGY", f"Calculated regime metrics from {len(atr_values)} ATR samples")
        return metrics
        
    except Exception as e:
        debug_log("STRATEGY_ERROR", f"Failed to load regime data: {e}")
    return DEFAULT_REGIME_METRICS.copy()


def calculate_capital_efficiency() -> dict:
    """Calculate capital efficiency metrics from available data"""
    backtest = load_backtest_results()
    trades = load_trade_ledger_metrics()
    
    metrics = DEFAULT_CAPITAL_METRICS.copy()
    
    # Calculate from available data
    if backtest.get("exposure_percent", 0) > 0:
        metrics["avg_deployed_capital_percent"] = backtest["exposure_percent"]
        metrics["avg_idle_capital_percent"] = 100 - backtest["exposure_percent"]
    
    # Estimate from trade data
    if trades.get("avg_position_size", 0) > 0:
        starting_cash = 8000  # Default from Stockbot
        estimated_exposure = (trades["avg_position_size"] * 5) / starting_cash * 100  # Assuming avg 5 positions
        metrics["avg_deployed_capital_percent"] = min(estimated_exposure, 100)
        metrics["avg_idle_capital_percent"] = 100 - metrics["avg_deployed_capital_percent"]
    
    return metrics


def build_strategy_analysis_prompt(params: dict, backtest: dict, trades: dict, regime: dict, capital: dict) -> str:
    """Build the complete analysis prompt with all strategy data from Stockbot"""
    
    # Helper to safely format numbers
    def fmt(val, decimals=2):
        if val is None or val == 'N/A':
            return 'N/A'
        try:
            if isinstance(val, bool):
                return str(val)
            return f"{float(val):.{decimals}f}"
        except:
            return str(val)
    
    prompt = f"""You are analyzing a live trading strategy with the following data:

═══════════════════════════════════════════════════════════════
CURRENT STRATEGY PARAMETERS (from Stockbot best_params.json)
═══════════════════════════════════════════════════════════════

EXIT PARAMETERS:
• Profit Target: {fmt(params.get('PROFIT_TARGET_PERCENT'))}%
• Stop Loss: {fmt(params.get('STOP_LOSS_PERCENT'))}%
• Trailing Stop Enabled: {params.get('TRAILING_STOP_ENABLED', 'N/A')}
• Trailing Stop: {fmt(params.get('TRAILING_STOP_PERCENT'))}%
• Min Profit for Trailing: {fmt(params.get('MIN_PROFIT_FOR_TRAILING'))}%
• ATR Stop Enabled: {params.get('ATR_STOP_ENABLED', False)}
• ATR Stop Multiplier: {fmt(params.get('ATR_STOP_MULTIPLIER'))}
• Time Stop Enabled: {params.get('TIME_STOP_ENABLED', False)}
• Time Stop Minutes: {params.get('TIME_STOP_MINUTES', 'N/A')}
• Late Day Loss Cut Enabled: {params.get('LATE_DAY_LOSS_CUT_ENABLED', False)}
• Late Day Loss Cut Threshold: {fmt(params.get('LATE_DAY_LOSS_CUT_THRESHOLD'))}%

POSITION SIZING:
• Max Positions: {params.get('MAX_POSITIONS', 'N/A')}
• Deployable Capital: {fmt(params.get('DEPLOYABLE_CAPITAL_PERCENT', 0) * 100 if params.get('DEPLOYABLE_CAPITAL_PERCENT', 0) < 2 else params.get('DEPLOYABLE_CAPITAL_PERCENT', 0))}%
• Medium Confidence Allocation: {fmt(params.get('MEDIUM_CONFIDENCE_ALLOCATION'))}
• Starting Cash: ${params.get('STARTING_CASH', 8000):,.0f}
• Min Actual Deployed Dollars: ${params.get('MIN_ACTUAL_DEPLOYED_DOLLARS', 'N/A')}
• Small Cap Max Position %: {fmt(params.get('SMALL_CAP_MAX_POSITION_PCT', 0) * 100)}%
• Volatility Adjusted Sizing: {params.get('VOLATILITY_ADJUSTED_SIZING', False)}
• Target Volatility %: {fmt(params.get('TARGET_VOLATILITY_PCT'))}%

ENTRY FILTERS:
• RVOL Threshold: {fmt(params.get('RVOL_THRESHOLD'))}x
• True RVOL Threshold: {fmt(params.get('TRUE_RVOL_THRESHOLD'))}x
• Breakout Threshold: {fmt(params.get('BREAKOUT_THRESHOLD_PERCENT'))}%
• Gap Threshold: {fmt(params.get('GAP_THRESHOLD_PERCENT'))}%
• Min Price Volatility (ATR%): {fmt(params.get('MIN_PRICE_VOLATILITY_ATR_PCT'))}%
• Volume Surge Multiplier: {fmt(params.get('VOLUME_SURGE_MULTIPLIER'))}x
• Early Liquidity Threshold: {fmt(params.get('EARLY_LIQUIDITY_THRESHOLD'))}

PRICE FILTERS:
• Min Trade Price: ${fmt(params.get('MIN_TRADE_PRICE'))}
• Max Small Cap Price: ${fmt(params.get('MAX_SMALL_CAP_PRICE'))}
• Max Large Cap Price: ${params.get('MAX_LARGE_CAP_PRICE', 'N/A')}
• Max Trade Price Hard Cap: ${params.get('MAX_TRADE_PRICE_HARD_CAP', 'N/A')}
• Max Price for Standard Allocation: ${params.get('MAX_PRICE_FOR_STANDARD_ALLOCATION', 'N/A')}

SMALL-CAP SPECIFIC:
• Min ATR% for Small Caps: {fmt(params.get('MIN_ATR_PERCENT_SMALLCAP'))}%
• Max Spread %: {fmt(params.get('MAX_SPREAD_PERCENT'))}%
• Min Avg Volume Per Bar: {params.get('MIN_AVG_VOLUME_PER_BAR', 'N/A')}

RISK MANAGEMENT:
• Daily Loss Circuit Breaker: ${params.get('DAILY_LOSS_CIRCUIT_BREAKER', 'N/A')}
• Daily Loss Circuit Breaker %: {fmt(params.get('DAILY_LOSS_CIRCUIT_BREAKER_PCT'))}%
• Symbol Circuit Breaker Enabled: {params.get('SYMBOL_CIRCUIT_BREAKER_ENABLED', False)}
• Symbol Max Stopouts/Day: {params.get('SYMBOL_MAX_STOPOUTS_PER_DAY', 'N/A')}
• Symbol Max Loss/Day: ${params.get('SYMBOL_MAX_LOSS_PER_DAY', 'N/A')}
• Max Buys Per Symbol/Day: {params.get('MAX_BUYS_PER_SYMBOL_PER_DAY', 'N/A')}

EXECUTION:
• Slippage (BPS): {fmt(params.get('SLIPPAGE_BPS'))}
• Max Volume Ratio: {fmt(params.get('MAX_VOLUME_RATIO'))}
• Commission Per Order: ${fmt(params.get('COMMISSION_PER_ORDER'))}
• Min Shares Per Trade: {params.get('MIN_SHARES_PER_TRADE', 'N/A')}
• Adaptive Stop Cutoff Price: ${fmt(params.get('ADAPTIVE_STOP_CUTOFF_PRICE'))}

═══════════════════════════════════════════════════════════════
BACKTEST RESULTS ({backtest.get('backtest_days', 50)}-DAY)
Source: {backtest.get('_source_file', 'N/A')}
═══════════════════════════════════════════════════════════════
• Total P&L: ${backtest.get('total_pnl', 0):,.2f}
• Avg Daily P&L: ${backtest.get('avg_daily_pnl', 0):,.2f}
• Win Rate (days): {backtest.get('win_rate', 0):.1f}%
• Average Winning Day: ${backtest.get('avg_win', 0):,.2f}
• Average Losing Day: ${backtest.get('avg_loss', 0):,.2f}
• Risk:Reward Ratio: {backtest.get('risk_reward_ratio', 0):.2f}
• Expectancy Per Trade: ${backtest.get('expectancy_per_trade', 0):,.2f}
• Trades Per Day: {backtest.get('trades_per_day', 0):.1f}
• Capital Efficiency: {backtest.get('capital_efficiency_ratio', 0):.4f}
• Max Drawdown: ${backtest.get('max_drawdown', 0):,.2f}
• Profit Factor: {backtest.get('profit_factor', 0):.2f}

═══════════════════════════════════════════════════════════════
TRADE-LEVEL METRICS
Source: {trades.get('_source_file', 'N/A')}
═══════════════════════════════════════════════════════════════
• Total Trades Analyzed: {trades.get('total_trades', 0)}
• Winning Trades: {trades.get('winning_trades', 0)}
• Losing Trades: {trades.get('losing_trades', 0)}
• Avg Win (per trade): ${trades.get('avg_win_trade', 0):,.2f}
• Avg Loss (per trade): ${trades.get('avg_loss_trade', 0):,.2f}
• Avg Position Size: ${trades.get('avg_position_size', 0):,.2f}

Exit Reasons Distribution:
• Stop Loss: {trades.get('exit_reasons', {}).get('stop_loss', 0)}
• Target/Profit: {trades.get('exit_reasons', {}).get('target', 0)}
• Trailing Stop: {trades.get('exit_reasons', {}).get('trailing', 0)}
• Time-based/EOD: {trades.get('exit_reasons', {}).get('time', 0)}
• Other: {trades.get('exit_reasons', {}).get('other', 0)}

═══════════════════════════════════════════════════════════════
REGIME/VOLATILITY METRICS (from trade data)
═══════════════════════════════════════════════════════════════
• Avg ATR%: {regime.get('avg_daily_atr', 0):.2f}%
• ATR 25th Percentile: {regime.get('atr_percentile_25', 0):.2f}%
• ATR 75th Percentile: {regime.get('atr_percentile_75', 0):.2f}%
• High Volume Days: {regime.get('high_volume_days_percent', 50):.0f}%
• Low Volume Days: {regime.get('low_volume_days_percent', 50):.0f}%

═══════════════════════════════════════════════════════════════
CAPITAL EFFICIENCY METRICS
═══════════════════════════════════════════════════════════════
• Avg Deployed Capital: {capital.get('avg_deployed_capital_percent', 0):.1f}%
• Avg Idle Capital: {capital.get('avg_idle_capital_percent', 0):.1f}%

═══════════════════════════════════════════════════════════════

Based on this data, provide your complete analysis following the required format."""

    return prompt


def save_analysis_report(report: str, params: dict, timestamp: str):
    """Save the analysis report to the Augmentation folder"""
    try:
        filename = f"strategy_analysis_{timestamp.replace(':', '-').replace(' ', '_')}.md"
        filepath = os.path.join(AUGMENTATION_DIR, filename)
        
        content = f"""# AI Strategy Optimization Report
Generated: {timestamp}

## Parameters Analyzed
```json
{json.dumps(params, indent=2)}
```

## Analysis
{report}
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        
        debug_log("STRATEGY", f"Saved analysis report to {filepath}")
        return filepath
    except Exception as e:
        debug_log("STRATEGY_ERROR", f"Failed to save analysis report: {e}")
        return None


def parse_suggested_changes(report: str) -> dict:
    """Parse suggested parameter changes from the AI report"""
    import re
    
    changes = {}
    
    # Look for patterns like "trailing stop: X%" or "change stop loss to Y%"
    patterns = {
        "TRAILING_STOP_PERCENT": r"trailing\s*stop.*?(\d+\.?\d*)\s*%",
        "STOP_LOSS_PERCENT": r"stop[\s-]*loss.*?(\d+\.?\d*)\s*%",
        "PROFIT_TARGET_PERCENT": r"(?:profit\s*)?target.*?(\d+\.?\d*)\s*%",
        "MAX_POSITIONS": r"max\s*positions?.*?(\d+)",
        "DEPLOYABLE_CAPITAL_PERCENT": r"(?:deployable\s*)?capital.*?(\d+\.?\d*)\s*%",
    }
    
    for param, pattern in patterns.items():
        matches = re.findall(pattern, report.lower())
        if matches:
            try:
                # Take the last mentioned value as the suggested change
                value = float(matches[-1])
                changes[param] = value
            except ValueError:
                pass
    
    debug_log("STRATEGY", f"Parsed suggested changes: {changes}")
    return changes


# ==================== MAIN APPLICATION CLASS ====================

class SpreederApp:
    def __init__(self):
        debug_log("APP_INIT", "Initializing SpreederApp")
        
        self.window = None
        self.is_visible = False
        self.is_playing = False
        self.is_paused = False  # Distinguishes pause (space during playback) from stop
        self.current_text = ""
        self.words = []
        self.current_word_index = 0
        self.summary = ""
        self.summary_ready = False
        self.summary_thread = None
        self.play_thread = None
        self.stop_playback = False
        self.formatted_words = []  # Stores parsed words with formatting info
        self.summary_after_playback = False  # Only show summary if Shift+Space was used
        
        # Load settings
        self.settings = load_settings()
        self.wpm = self.settings.get("wpm", 400)
        self.pause_delay = self.settings.get("pause_delay", 750)  # milliseconds
        debug_log("APP_INIT", f"Loaded WPM setting: {self.wpm}")
        debug_log("APP_INIT", f"Loaded pause delay setting: {self.pause_delay}ms")
        
        # UI elements (will be initialized when window is created)
        self.word_label = None
        self.wpm_slider = None
        self.wpm_label = None
        self.pause_slider = None
        self.pause_label = None
        self.status_label = None
        self.summary_text = None
        self.progress_bar = None
        self.progress_label = None
        
        # Arrow key navigation state
        self.arrow_repeat_delay = 150  # ms between word changes when holding arrow
        self.arrow_repeat_job = None
        
        # Hyperstudy serial mode state
        self.quick_answer = ""
        self.quick_answer_mode = False
        self.pending_quick_answer = None  # For quick question serial reading flow
        self._on_quick_answer_complete = None  # Callback after quick answer playback
        
        # Summary cache - avoid re-calling API for same clipboard content
        self.last_clipboard_text = ""
        self.cached_summary = ""
        
        # Simplified explanation system (Ctrl+Space feature)
        self.simplified_explanations = []  # List of 3 explanations [simple, simpler, simplest]
        self.current_explanation_index = 0  # Which explanation we're showing (0, 1, or 2)
        self.simplify_source_text = ""  # The original text being simplified
        self.simplify_thread = None  # Thread for fetching explanations
        
        # Text view mode toggle (Ctrl+Alt+Space feature)
        self.full_text_view_mode = False  # False = serial reader, True = full text display
        
        # Notes system
        self.current_notes_file = "Notes.txt"
        self.current_summary_title = ""
        self.note_id_counter = self._get_next_note_id()  # Track note IDs
        
        # Quiz system
        self.quiz_questions = []
        self.current_quiz_index = 0
        self.quiz_score = {"correct": 0, "incorrect": 0}
        self.include_review = False
        self.quiz_topics_log_file = "QuizTopicsLog.txt"  # Log of covered/understood topics
        
        # Create the window immediately (hidden)
        self.create_window()
        self.window.withdraw()  # Hide initially
        
        # Setup global hotkey
        self.setup_hotkey()
        
        debug_log("APP_INIT", "SpreederApp initialization complete")
    
    def setup_hotkey(self):
        """Register global hotkeys"""
        debug_log("HOTKEY", "Setting up global hotkeys")
        try:
            keyboard.on_press_key("f3", self.on_f3_pressed)
            keyboard.add_hotkey("ctrl+alt+n", self.on_global_save_note)
            keyboard.add_hotkey("ctrl+alt+q", self.on_global_quiz)
            keyboard.add_hotkey("ctrl+alt+s", self.on_global_shorten)
            keyboard.add_hotkey("ctrl+shift+a", self.on_global_strategy_analysis)
            keyboard.add_hotkey("ctrl+alt+g", self.on_global_chat)
            debug_log("HOTKEY", "Global hotkeys registered successfully")
        except Exception as e:
            debug_log("HOTKEY_ERROR", f"Failed to register hotkey: {str(e)}")
    
    def on_global_strategy_analysis(self):
        """Handle global Ctrl+Shift+A press - AI Strategy Analysis"""
        debug_log("HOTKEY", "Global Ctrl+Shift+A pressed - Strategy Analysis")
        if self.window:
            self.window.after(0, self.open_strategy_analysis_window)
    
    def on_global_save_note(self):
        """Handle global Ctrl+Alt+N press"""
        debug_log("HOTKEY", "Global Ctrl+Alt+N pressed")
        if self.window:
            self.window.after(0, self.on_save_note)
    
    def on_global_quiz(self):
        """Handle global Ctrl+Alt+Q press"""
        debug_log("HOTKEY", "Global Ctrl+Alt+Q pressed")
        if self.window:
            self.window.after(0, self._show_quiz_file_selector)
    
    def on_global_shorten(self):
        """Handle global Ctrl+Alt+S press"""
        debug_log("HOTKEY", "Global Ctrl+Alt+S pressed")
        if self.window:
            self.window.after(0, self._show_shorten_dialog)
    
    def on_global_chat(self):
        """Handle global Ctrl+Alt+G press - Open ChatGPT window"""
        debug_log("HOTKEY", "Global Ctrl+Alt+G pressed - Chat Window")
        if self.window:
            self.window.after(0, self._show_chat_window)
    
    def on_f3_pressed(self, event):
        """Handle F3 key press - use after() to safely call from hotkey thread"""
        # Use a lock to prevent duplicate events (keyboard lib fires twice at same timestamp)
        if not hasattr(self, '_f3_lock'):
            self._f3_lock = threading.Lock()
        
        if not self._f3_lock.acquire(blocking=False):
            debug_log("KEYPRESS", "F3 debounced - lock held")
            return
        
        try:
            # Check modifier keys
            shift_held = keyboard.is_pressed('shift')
            ctrl_held = keyboard.is_pressed('ctrl')
            alt_held = keyboard.is_pressed('alt')
            
            debug_log("KEYPRESS", "F3 key pressed", {
                "event": str(event),
                "shift_held": shift_held,
                "ctrl_held": ctrl_held,
                "alt_held": alt_held
            })
            
            # Schedule the appropriate action on the main tkinter thread
            if self.window:
                if ctrl_held and alt_held:
                    # Ctrl+Alt+F3: Quick Question (new dialog with format buttons)
                    self.window.after(0, self._show_quick_question_dialog)
                elif ctrl_held and shift_held:
                    # Ctrl+Shift+F3: Open hyperstudy prompt
                    self.window.after(0, self._show_quick_question)
                elif shift_held:
                    # Shift+F3: Show summary immediately
                    self.window.after(0, lambda: self._toggle_window(shift_held=True))
                elif not ctrl_held and not alt_held:
                    # F3 alone: Normal toggle (only if no modifiers)
                    self.window.after(0, lambda: self._toggle_window(shift_held=False))
        finally:
            # Release lock after a delay to prevent rapid re-firing
            def release_lock():
                time.sleep(0.5)
                self._f3_lock.release()
            threading.Thread(target=release_lock, daemon=True).start()
    
    def _show_quick_question(self):
        """Show hyperstudy input dialog with modifier buttons"""
        # Debounce: prevent duplicate windows within 500ms
        current_time = time.time()
        if hasattr(self, '_last_hyperstudy_time') and current_time - self._last_hyperstudy_time < 0.5:
            debug_log("HYPERSTUDY", "Debounced duplicate hyperstudy dialog request")
            return
        self._last_hyperstudy_time = current_time
        
        debug_log("HYPERSTUDY", "Opening hyperstudy dialog")
        
        # Store original notes for restoration
        self._original_notes_buffer = ""
        self._selected_modifier = None
        
        # Create a new top-level window for the prompt
        self.question_window = ctk.CTkToplevel(self.window)
        self.question_window.title("Hyperstudy + Modifiers")
        self.question_window.geometry("600x420")
        self.question_window.configure(fg_color="#1a1a1a")
        self.question_window.attributes("-topmost", True)
        
        # Center the question window
        screen_width = self.question_window.winfo_screenwidth()
        screen_height = self.question_window.winfo_screenheight()
        x = (screen_width - 600) // 2
        y = (screen_height - 420) // 2
        self.question_window.geometry(f"600x420+{x}+{y}")
        
        # Instructions label
        instructions = ctk.CTkLabel(
            self.question_window,
            text="Enter → Read aloud | Ctrl+Enter → One sentence | Ctrl+Shift+Enter → Detailed",
            font=("Segoe UI", 10),
            text_color="#888888"
        )
        instructions.pack(pady=(10, 5))
        
        # Text input (larger for notes)
        self.question_entry = ctk.CTkTextbox(
            self.question_window,
            width=560,
            height=100,
            font=("Segoe UI", 12),
            fg_color="#2a2a2a",
            text_color="white",
            wrap="word"
        )
        self.question_entry.pack(pady=10)
        self.question_entry.focus()
        
        # Modifier buttons frame
        modifier_frame = ctk.CTkFrame(self.question_window, fg_color="#252525")
        modifier_frame.pack(fill="x", padx=20, pady=(5, 5))
        
        modifier_label = ctk.CTkLabel(
            modifier_frame,
            text="Modifiers:",
            font=("Segoe UI", 10),
            text_color="#888888"
        )
        modifier_label.pack(side="left", padx=(10, 5))
        
        # Create modifier buttons from registry
        self.modifier_buttons = {}
        for mod_id, mod_config in MODIFIER_REGISTRY.items():
            btn = ctk.CTkButton(
                modifier_frame,
                text=f"{mod_config['icon']} {mod_config['label']}",
                width=80,
                height=28,
                font=("Segoe UI Emoji", 10),
                fg_color="#2d5a27" if mod_id == "brain" else "#3a3a3a",
                hover_color="#3d7a37" if mod_id == "brain" else "#4a4a4a",
                command=lambda m=mod_id: self._run_modifier(m)
            )
            btn.pack(side="left", padx=3, pady=5)
            self.modifier_buttons[mod_id] = btn
            
            # Add tooltip on hover (using bind)
            btn.bind("<Enter>", lambda e, t=mod_config['tooltip']: self._show_tooltip(e, t))
            btn.bind("<Leave>", self._hide_tooltip)
        
        # Collapsible context panel
        self.context_expanded = False
        
        context_header = ctk.CTkFrame(self.question_window, fg_color="transparent")
        context_header.pack(fill="x", padx=20, pady=(5, 0))
        
        self.context_toggle_btn = ctk.CTkButton(
            context_header,
            text="▶ Context Options",
            width=140,
            height=22,
            font=("Segoe UI", 10),
            fg_color="transparent",
            hover_color="#2a2a2a",
            text_color="#888888",
            anchor="w",
            command=self._toggle_context_panel
        )
        self.context_toggle_btn.pack(side="left")
        
        # Context panel (initially hidden)
        self.context_panel = ctk.CTkFrame(self.question_window, fg_color="#252525")
        
        # Context fields
        self.context_fields = {}
        
        # Row 1: Target role + Experience
        row1 = ctk.CTkFrame(self.context_panel, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(row1, text="Target role:", font=("Segoe UI", 9), text_color="#888", width=80).pack(side="left")
        self.context_fields["target_role"] = ctk.CTkEntry(row1, width=180, height=24, font=("Segoe UI", 9), placeholder_text="e.g., Security Engineer")
        self.context_fields["target_role"].pack(side="left", padx=5)
        
        ctk.CTkLabel(row1, text="Experience:", font=("Segoe UI", 9), text_color="#888", width=70).pack(side="left")
        self.context_fields["experience_level"] = ctk.CTkEntry(row1, width=180, height=24, font=("Segoe UI", 9), placeholder_text="e.g., Mid-level")
        self.context_fields["experience_level"].pack(side="left", padx=5)
        
        # Row 2: Time horizon + Emphasis
        row2 = ctk.CTkFrame(self.context_panel, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(row2, text="Time horizon:", font=("Segoe UI", 9), text_color="#888", width=80).pack(side="left")
        self.context_fields["time_horizon"] = ctk.CTkEntry(row2, width=180, height=24, font=("Segoe UI", 9), placeholder_text="e.g., 2 weeks")
        self.context_fields["time_horizon"].pack(side="left", padx=5)
        
        ctk.CTkLabel(row2, text="Emphasis:", font=("Segoe UI", 9), text_color="#888", width=70).pack(side="left")
        self.context_fields["preferred_emphasis"] = ctk.CTkEntry(row2, width=180, height=24, font=("Segoe UI", 9), placeholder_text="e.g., AWS + AppSec")
        self.context_fields["preferred_emphasis"].pack(side="left", padx=5)
        
        # Row 3: Modifier-specific fields
        row3 = ctk.CTkFrame(self.context_panel, fg_color="transparent")
        row3.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(row3, text="Seniority:", font=("Segoe UI", 9), text_color="#888", width=80).pack(side="left")
        self.context_fields["seniority_target"] = ctk.CTkEntry(row3, width=100, height=24, font=("Segoe UI", 9), placeholder_text="mid/senior")
        self.context_fields["seniority_target"].pack(side="left", padx=5)
        
        ctk.CTkLabel(row3, text="Environment:", font=("Segoe UI", 9), text_color="#888", width=75).pack(side="left")
        self.context_fields["environment"] = ctk.CTkEntry(row3, width=100, height=24, font=("Segoe UI", 9), placeholder_text="AWS/local")
        self.context_fields["environment"].pack(side="left", padx=5)
        
        ctk.CTkLabel(row3, text="Difficulty:", font=("Segoe UI", 9), text_color="#888", width=60).pack(side="left")
        self.context_fields["difficulty"] = ctk.CTkEntry(row3, width=100, height=24, font=("Segoe UI", 9), placeholder_text="interview-ready")
        self.context_fields["difficulty"].pack(side="left", padx=5)
        
        # Row 4: Time budget
        row4 = ctk.CTkFrame(self.context_panel, fg_color="transparent")
        row4.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(row4, text="Time budget:", font=("Segoe UI", 9), text_color="#888", width=80).pack(side="left")
        self.context_fields["time_budget"] = ctk.CTkEntry(row4, width=200, height=24, font=("Segoe UI", 9), placeholder_text="e.g., 3 evenings this week")
        self.context_fields["time_budget"].pack(side="left", padx=5)
        
        # Bottom buttons frame
        bottom_frame = ctk.CTkFrame(self.question_window, fg_color="transparent")
        bottom_frame.pack(pady=(10, 10))
        
        # Shortcuts button
        shortcuts_btn = ctk.CTkButton(
            bottom_frame,
            text="⌨ Shortcuts",
            width=100,
            height=25,
            font=("Segoe UI", 10),
            fg_color="#3a3a3a",
            hover_color="#4a4a4a",
            command=self._show_shortcuts
        )
        shortcuts_btn.pack(side="left", padx=5)
        
        # Tooltip label (hidden initially)
        self.tooltip_label = ctk.CTkLabel(
            self.question_window,
            text="",
            font=("Segoe UI", 9),
            text_color="#aaaaaa",
            fg_color="#333333",
            corner_radius=4
        )
        
        # Bind keys for different submission modes
        self.question_entry.bind("<Return>", self._submit_question_serial_textbox)
        self.question_entry.bind("<Control-Return>", self._submit_question_single_textbox)
        self.question_entry.bind("<Control-Shift-Return>", self._submit_question_detailed_textbox)
        
        # Tab navigation from textbox to first modifier button
        first_modifier_btn = list(self.modifier_buttons.values())[0] if self.modifier_buttons else shortcuts_btn
        mod_btns = list(self.modifier_buttons.values())
        
        # Helper to find focused widget index
        def find_focused_index():
            current = self.question_window.focus_get()
            # Check textbox
            if current == self.question_entry or (hasattr(self.question_entry, '_textbox') and current == self.question_entry._textbox):
                return -1  # Special: textbox
            # Check buttons
            for i, btn in enumerate(mod_btns):
                if current == btn:
                    return i
                if hasattr(btn, '_canvas') and current == btn._canvas:
                    return i
                try:
                    if current and str(current).startswith(str(btn)):
                        return i
                except:
                    pass
            return -2  # Not found
        
        # Window-level Tab navigation for Hyperstudy
        def on_window_tab(e):
            idx = find_focused_index()
            if idx == -1:  # In textbox
                first_modifier_btn.focus_set()
            elif idx == -2:  # Not found
                self.question_entry.focus_set()
            else:  # In a button
                next_idx = (idx + 1) % len(mod_btns)
                mod_btns[next_idx].focus_set()
            return "break"
        
        def on_window_shift_tab(e):
            idx = find_focused_index()
            if idx == -1:  # In textbox
                mod_btns[-1].focus_set() if mod_btns else shortcuts_btn.focus_set()
            elif idx == -2:  # Not found
                self.question_entry.focus_set()
            elif idx == 0:  # First button, go back to textbox
                self.question_entry.focus_set()
            else:  # In a button
                prev_idx = (idx - 1) % len(mod_btns)
                mod_btns[prev_idx].focus_set()
            return "break"
        
        self.question_window.bind("<Tab>", on_window_tab)
        self.question_window.bind("<Shift-Tab>", on_window_shift_tab)
        
        # Bind Tab to each button directly
        for btn in mod_btns:
            btn.bind("<Tab>", on_window_tab)
            btn.bind("<Shift-Tab>", on_window_shift_tab)
        
        # Bind to internal textbox to prevent indent
        try:
            internal = self.question_entry._textbox
            internal.bind("<Tab>", on_window_tab)
            internal.bind("<Shift-Tab>", on_window_shift_tab)
        except AttributeError:
            pass
        
        self.question_window.bind("<Escape>", lambda e: self._close_question_window())
        
        debug_log("HYPERSTUDY", "Hyperstudy dialog created with modifier buttons")
    
    def _show_tooltip(self, event, text):
        """Show tooltip near cursor"""
        self.tooltip_label.configure(text=f"  {text}  ")
        self.tooltip_label.place(x=event.x_root - self.question_window.winfo_rootx() + 10,
                                  y=event.y_root - self.question_window.winfo_rooty() + 20)
    
    def _hide_tooltip(self, event=None):
        """Hide tooltip"""
        self.tooltip_label.place_forget()
    
    def _toggle_context_panel(self):
        """Toggle context panel visibility"""
        if self.context_expanded:
            self.context_panel.pack_forget()
            self.context_toggle_btn.configure(text="▶ Context Options")
            self.context_expanded = False
        else:
            self.context_panel.pack(fill="x", padx=20, pady=(0, 5))
            self.context_toggle_btn.configure(text="▼ Context Options")
            self.context_expanded = True
    
    def _get_context_values(self) -> dict:
        """Get all context field values"""
        return {key: field.get() for key, field in self.context_fields.items()}
    
    def _run_modifier(self, modifier_id: str):
        """Run a modifier from the registry"""
        notes_text = self.question_entry.get("1.0", "end-1c").strip()
        
        debug_log("MODIFIER_CLICK", f"Modifier clicked: {modifier_id}", {
            "notes_length": len(notes_text)
        })
        
        if not notes_text:
            debug_log("MODIFIER_CLICK", "No text provided, ignoring")
            return
        
        # Store original notes for restoration
        self._original_notes_buffer = notes_text
        self._selected_modifier = modifier_id
        
        # Disable all modifier buttons and show spinner
        for btn in self.modifier_buttons.values():
            btn.configure(state="disabled")
        self.modifier_buttons[modifier_id].configure(text=f"⏳ Working...")
        
        # Get context values
        context = self._get_context_values()
        context["_selected_text_used"] = False  # Could check for selection
        
        # Close question window
        self._close_question_window()
        
        # Show the main window with loading state
        self._show_window_minimal()
        mod_config = MODIFIER_REGISTRY[modifier_id]
        self.word_label.configure(text=f"{mod_config['icon']} Processing...")
        self.status_label.configure(text=f"Running {mod_config['label']} modifier...")
        
        # Run API call in background thread
        def run_api():
            start_time = time.time()
            result, token_info = run_modifier(modifier_id, notes_text, context)
            latency = time.time() - start_time
            
            debug_log("MODIFIER_COMPLETE", f"Modifier complete: {modifier_id}", {
                "latency_seconds": round(latency, 2),
                "tokens": token_info
            })
            
            # Update UI on main thread
            self.window.after(0, lambda: self._show_modifier_result(modifier_id, result, token_info))
        
        thread = threading.Thread(target=run_api, daemon=True)
        thread.start()
    
    def _show_modifier_result(self, modifier_id: str, result: str, token_info: dict):
        """Display modifier result in a result modal"""
        debug_log("MODIFIER_RESULT", f"Displaying {modifier_id} result", {
            "result_length": len(result),
            "tokens": token_info
        })
        
        # Store result for notes
        self.summary = result
        self.original_text = self._original_notes_buffer if hasattr(self, '_original_notes_buffer') else ""
        
        mod_config = MODIFIER_REGISTRY[modifier_id]
        
        # Create result window
        result_win = ctk.CTkToplevel(self.window)
        result_win.title(f"{mod_config['icon']} {mod_config['label']} Result")
        result_win.geometry("700x600")
        result_win.configure(fg_color="#1a1a1a")
        result_win.transient(self.window)
        result_win.attributes("-topmost", True)
        result_win.lift()
        
        # Bind Escape to close
        result_win.bind("<Escape>", lambda e: result_win.destroy())
        
        # Center the window
        screen_width = result_win.winfo_screenwidth()
        screen_height = result_win.winfo_screenheight()
        x = (screen_width - 700) // 2
        y = (screen_height - 600) // 2
        result_win.geometry(f"700x600+{x}+{y}")
        
        # Header with token info
        header_frame = ctk.CTkFrame(result_win, fg_color="transparent")
        header_frame.pack(fill="x", padx=20, pady=(15, 5))
        
        title_label = ctk.CTkLabel(
            header_frame,
            text=f"{mod_config['icon']} {mod_config['label']} Output",
            font=("Segoe UI", 16, "bold"),
            text_color="#FF6B00"
        )
        title_label.pack(side="left")
        
        if token_info:
            cost = estimate_cost(token_info['input_tokens'], token_info['output_tokens'], token_info.get('model', DEFAULT_MODEL))
            token_label = ctk.CTkLabel(
                header_frame,
                text=f"Tokens: {token_info['total_tokens']} (in:{token_info['input_tokens']} out:{token_info['output_tokens']}) ~{format_cost(cost)}",
                font=("Segoe UI", 10),
                text_color="#888888"
            )
            token_label.pack(side="right")
        
        # Result text area
        result_text = ctk.CTkTextbox(
            result_win,
            width=660,
            height=450,
            font=("Segoe UI", 12),
            fg_color="#2a2a2a",
            text_color="white",
            wrap="word"
        )
        result_text.pack(padx=20, pady=10)
        result_text.insert("1.0", result)
        
        # Apply markdown formatting if the method exists
        if hasattr(self, '_apply_markdown_formatting'):
            self._apply_markdown_formatting(result_text)
        
        # Store reference for copy/save
        self._current_result_text = result
        self._current_modifier_id = modifier_id
        
        # Button frame
        btn_frame = ctk.CTkFrame(result_win, fg_color="transparent")
        btn_frame.pack(pady=15)
        
        def copy_result():
            pyperclip.copy(result)
            copy_btn.configure(text="✓ Copied!")
            result_win.after(1500, lambda: copy_btn.configure(text="📋 Copy"))
        
        def save_result():
            filepath = save_modifier_output(modifier_id, result)
            if filepath:
                save_btn.configure(text="✓ Saved!")
                result_win.after(1500, lambda: save_btn.configure(text="💾 Save"))
        
        def restore_original():
            result_text.configure(state="normal")
            result_text.delete("1.0", "end")
            result_text.insert("1.0", self._original_notes_buffer)
            result_text.configure(state="disabled")
            restore_btn.configure(text="✓ Restored!")
            result_win.after(1500, lambda: restore_btn.configure(text="↩ Restore"))
        
        def close_result():
            result_win.destroy()
            self._hide_window()
        
        copy_btn = ctk.CTkButton(
            btn_frame,
            text="📋 Copy",
            width=90,
            height=30,
            font=("Segoe UI Emoji", 11),
            fg_color="#3a3a3a",
            hover_color="#4a4a4a",
            command=copy_result
        )
        copy_btn.pack(side="left", padx=5)
        
        save_btn = ctk.CTkButton(
            btn_frame,
            text="💾 Save",
            width=90,
            height=30,
            font=("Segoe UI Emoji", 11),
            fg_color="#2d5a27",
            hover_color="#3d7a37",
            command=save_result
        )
        save_btn.pack(side="left", padx=5)
        
        restore_btn = ctk.CTkButton(
            btn_frame,
            text="↩ Restore",
            width=90,
            height=30,
            font=("Segoe UI Emoji", 11),
            fg_color="#5a5a27",
            hover_color="#7a7a37",
            command=restore_original
        )
        restore_btn.pack(side="left", padx=5)
        
        note_btn = ctk.CTkButton(
            btn_frame,
            text="📝 Note",
            width=90,
            height=30,
            font=("Segoe UI Emoji", 11),
            fg_color="#3a3a3a",
            hover_color="#4a4a4a",
            command=self.on_save_note
        )
        note_btn.pack(side="left", padx=5)
        
        close_btn = ctk.CTkButton(
            btn_frame,
            text="✓ Done",
            width=90,
            height=30,
            font=("Segoe UI", 11),
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            command=close_result
        )
        close_btn.pack(side="left", padx=5)
        
        # List of focusable widgets for Tab navigation
        focusables = [result_text, copy_btn, save_btn, restore_btn, note_btn, close_btn]
        
        # Setup button focus visuals
        for btn in [copy_btn, save_btn, restore_btn, note_btn, close_btn]:
            btn.bind("<FocusIn>", lambda e, b=btn: b.configure(border_width=2, border_color="#FFFFFF"))
            btn.bind("<FocusOut>", lambda e, b=btn: b.configure(border_width=0))
            btn.bind("<Return>", lambda e, b=btn: b.invoke())
            btn.bind("<space>", lambda e, b=btn: b.invoke())
        
        # Helper to find which focusable widget contains the current focus
        def find_focused_index():
            current = result_win.focus_get()
            for i, widget in enumerate(focusables):
                # Check if current is the widget itself
                if current == widget:
                    return i
                # Check if current is inside a CTkTextbox
                if hasattr(widget, '_textbox') and current == widget._textbox:
                    return i
                # Check if current is inside a CTkButton (canvas or other internal widget)
                if hasattr(widget, '_canvas') and current == widget._canvas:
                    return i
                # Check by widget hierarchy - if current is a child of widget
                try:
                    if current and str(current).startswith(str(widget)):
                        return i
                except:
                    pass
            return -1
        
        # Window-level Tab navigation
        def on_window_tab(e):
            current_idx = find_focused_index()
            next_idx = (current_idx + 1) % len(focusables)
            focusables[next_idx].focus_set()
            return "break"
        
        def on_window_shift_tab(e):
            current_idx = find_focused_index()
            prev_idx = (current_idx - 1) % len(focusables)
            focusables[prev_idx].focus_set()
            return "break"
        
        # Bind Tab at window level
        result_win.bind("<Tab>", on_window_tab)
        result_win.bind("<Shift-Tab>", on_window_shift_tab)
        
        # Also bind Tab to each button directly (CTkButton internal widgets need this)
        for btn in [copy_btn, save_btn, restore_btn, note_btn, close_btn]:
            btn.bind("<Tab>", on_window_tab)
            btn.bind("<Shift-Tab>", on_window_shift_tab)
        
        # Bind to internal textbox to prevent indent
        try:
            internal = result_text._textbox
            internal.bind("<Tab>", on_window_tab)
            internal.bind("<Shift-Tab>", on_window_shift_tab)
        except AttributeError:
            pass
        
        # Update main window status
        self.word_label.configure(text=f"{mod_config['icon']} Done!")
        if token_info:
            cost = estimate_cost(token_info['input_tokens'], token_info['output_tokens'], token_info.get('model', DEFAULT_MODEL))
            token_str = f" | {token_info['total_tokens']} tokens ~{format_cost(cost)}"
        else:
            token_str = ""
        self.status_label.configure(text=f"{mod_config['label']} complete{token_str}")
    
    def _submit_question_serial_textbox(self, event):
        """Submit question and display via serial reader (textbox version)"""
        # Check if Ctrl is pressed (for Ctrl+Return)
        if event.state & 0x4:  # Control key
            return  # Let Ctrl+Return handler deal with it
        # Check if Shift is pressed (allow newline)
        if event.state & 0x1:  # Shift key
            return  # Let default behavior insert newline
        text = self.question_entry.get("1.0", "end-1c").strip()
        if text:
            self._original_notes_buffer = text
            self._submit_question_text("serial", text)
        return "break"
    
    def _submit_question_single_textbox(self, event):
        """Submit question with single sentence format (textbox version)"""
        text = self.question_entry.get("1.0", "end-1c").strip()
        if text:
            self._original_notes_buffer = text
            self._submit_question_text("single", text)
        return "break"
    
    def _submit_question_detailed_textbox(self, event):
        """Submit question with detailed format (textbox version)"""
        text = self.question_entry.get("1.0", "end-1c").strip()
        if text:
            self._original_notes_buffer = text
            self._submit_question_text("detailed", text)
        return "break"
    
    def _submit_question_text(self, response_format: str, text: str):
        """Submit the question text to OpenAI and show response"""
        debug_log("QUICK_QUESTION", f"Submitting question", {
            "format": response_format,
            "prompt_length": len(text)
        })
        
        if not text:
            debug_log("QUICK_QUESTION", "Empty prompt, ignoring")
            return
        
        # Close question window
        self._close_question_window()
        
        # Show the main window WITHOUT reading clipboard
        self._show_window_minimal()
        self.word_label.configure(text="Thinking...")
        self.status_label.configure(text=f"Asking: {text[:50]}..." if len(text) > 50 else f"Asking: {text}")
        
        # Run API call in background thread
        def get_answer():
            api_format = "default" if response_format == "serial" else response_format
            answer = ask_openai(text, api_format)
            if response_format == "serial":
                self.window.after(0, lambda: self._prepare_serial_answer(answer))
            else:
                self.window.after(0, lambda: self._show_answer(answer))
        
        thread = threading.Thread(target=get_answer, daemon=True)
        thread.start()
    
    def _submit_question_serial(self, event):
        """Submit question and display via serial reader"""
        self._submit_question("serial")
        return "break"
    
    def _submit_question_single(self, event):
        """Submit question with single sentence format"""
        self._submit_question("single")
        return "break"
    
    def _submit_question_detailed(self, event):
        """Submit question with detailed format"""
        self._submit_question("detailed")
        return "break"
    
    def _submit_question(self, response_format: str):
        """Submit the question to OpenAI and show response"""
        prompt = self.question_entry.get().strip()
        
        debug_log("QUICK_QUESTION", f"Submitting question", {
            "format": response_format,
            "prompt_length": len(prompt)
        })
        
        if not prompt:
            debug_log("QUICK_QUESTION", "Empty prompt, ignoring")
            return
        
        # Close question window
        self._close_question_window()
        
        # Show the main window WITHOUT reading clipboard (use _show_window_minimal)
        self._show_window_minimal()
        self.word_label.configure(text="Thinking...")
        self.status_label.configure(text=f"Asking: {prompt[:50]}..." if len(prompt) > 50 else f"Asking: {prompt}")
        
        # Run API call in background thread
        def get_answer():
            # For serial mode, use default format for readable answer
            api_format = "default" if response_format == "serial" else response_format
            answer = ask_openai(prompt, api_format)
            # Update UI on main thread
            if response_format == "serial":
                self.window.after(0, lambda: self._prepare_serial_answer(answer))
            else:
                self.window.after(0, lambda: self._show_answer(answer))
        
        thread = threading.Thread(target=get_answer, daemon=True)
        thread.start()
    
    def _show_window_minimal(self):
        """Show the window without reading clipboard - for hyperstudy mode"""
        debug_log("WINDOW_SHOW_MINIMAL", "Showing window (minimal, no clipboard)")
        
        # Reset UI state without touching current_text
        self.word_label.pack(expand=True)
        self.summary_text.pack_forget()
        
        # Show window
        self.window.deiconify()
        self.window.focus_force()
        self.is_visible = True
        debug_log("WINDOW_SHOW_MINIMAL", "Window is now visible (minimal)")
    
    def _prepare_serial_answer(self, answer: str):
        """Prepare answer for serial reading mode"""
        debug_log("QUICK_QUESTION", "Preparing answer for serial reading", {"answer_length": len(answer)})
        
        # Store the answer for display after playback
        self.quick_answer = answer
        self.quick_answer_mode = True
        
        # Set up the text for serial reading (like clipboard text)
        self.current_text = answer
        self.words = self.current_text.split()
        self.current_word_index = 0
        
        # Reset playback state
        self.is_playing = False
        self.is_paused = False
        self.stop_playback = False
        
        # Show ready state
        self.word_label.pack(expand=True)
        self.summary_text.pack_forget()
        self.word_label.configure(text="Ready")
        self.status_label.configure(text="Press SPACE to read | ENTER to skip to full answer")
        
        # Update progress bar
        if hasattr(self, 'progress_bar') and self.progress_bar:
            self.progress_bar.set(0)
        if hasattr(self, 'progress_label') and self.progress_label:
            self.progress_label.configure(text=f"0 / {len(self.words)} words")
        
        debug_log("QUICK_QUESTION", f"Serial answer ready with {len(self.words)} words")
    
    def _show_answer(self, answer: str):
        """Display the answer in the main window"""
        debug_log("QUICK_QUESTION", "Displaying answer", {"answer_length": len(answer)})
        
        # Clear quick answer mode flag
        self.quick_answer_mode = False
        
        # Hide word display, show summary text area
        self.word_label.pack_forget()
        self.summary_text.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Display the answer
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", answer)
        self._apply_markdown_formatting(self.summary_text)
        self.summary_text.configure(state="disabled")
        
        # Add note and clarify buttons if not already present
        if not hasattr(self, 'note_button_frame') or not self.note_button_frame.winfo_exists():
            self.note_button_frame = ctk.CTkFrame(self.window)
            self.note_button_frame.pack(side="bottom", pady=5)
            
            self.note_button = ctk.CTkButton(
                self.note_button_frame,
                text="📝",
                width=50,
                height=35,
                font=("Segoe UI Emoji", 18),
                command=self.on_save_note,
                fg_color="#2b2b2b",
                hover_color="#3b3b3b"
            )
            self.note_button.pack(side="left", padx=5)
            
            self.clarify_button = ctk.CTkButton(
                self.note_button_frame,
                text="❓",
                width=50,
                height=35,
                font=("Segoe UI Emoji", 18),
                command=self._show_clarify_prompt,
                fg_color="#2b2b2b",
                hover_color="#3b3b3b"
            )
            self.clarify_button.pack(side="left", padx=5)
        
        self.status_label.configure(text="Press SPACE or ENTER to close | Ctrl+Alt+N to save note")
    
    def _close_question_window(self):
        """Close the question input window"""
        if hasattr(self, 'question_window') and self.question_window:
            debug_log("QUICK_QUESTION", "Closing question window")
            self.question_window.destroy()
            self.question_window = None

    def _show_shortcuts(self):
        """Display shortcuts reference window"""
        debug_log("SHORTCUTS", "Opening shortcuts window")
        
        # Create shortcuts window
        shortcuts_win = ctk.CTkToplevel(self.window)
        shortcuts_win.title("Keyboard Shortcuts")
        shortcuts_win.geometry("400x580")
        shortcuts_win.configure(fg_color="#1a1a1a")
        shortcuts_win.transient(self.window)  # Make it appear on top of parent
        shortcuts_win.attributes("-topmost", True)
        shortcuts_win.lift()  # Bring to front
        
        # Center the window
        screen_width = shortcuts_win.winfo_screenwidth()
        screen_height = shortcuts_win.winfo_screenheight()
        x = (screen_width - 400) // 2
        y = (screen_height - 580) // 2
        shortcuts_win.geometry(f"400x580+{x}+{y}")
        
        # Title
        title = ctk.CTkLabel(
            shortcuts_win,
            text="⌨ Keyboard Shortcuts",
            font=("Segoe UI", 18, "bold"),
            text_color="#FF6B00"
        )
        title.pack(pady=(15, 10))
        
        # Shortcuts text
        shortcuts_text = """
GLOBAL HOTKEYS
─────────────────────────────
F3                    Open/close Spreeder
Shift + F3          Show summary immediately  
Ctrl + Shift + F3   Hyperstudy prompt
Ctrl + Alt + F3     Quick question

DURING PLAYBACK
─────────────────────────────
Space                Start / Pause / Resume
← →                  Navigate words (when paused)
Enter                Skip to summary/answer

WINDOW CONTROLS
─────────────────────────────
Ctrl + =             Reset width & expand vertically
Ctrl + Shift + =     Maximize window
Ctrl + Alt + =       Fullscreen toggle
Escape              Close window
F3                    Close window

QUICK QUESTION (Ctrl+Alt+F3)
─────────────────────────────
Three format options:
• One Sentence: Single-line answer
• Headers & Bullets: Structured (≤10 words/bullet)
• Andragogy ¶: Adult learning paragraph

HYPERSTUDY (Ctrl+Shift+F3)
─────────────────────────────
Enter                Serial read the answer
Ctrl + Enter        One sentence reply
Ctrl + Shift + Enter  Detailed format
Escape              Cancel

MODIFIER BUTTONS (paste notes first)
─────────────────────────────
🧠 Brain            Teach as integrated mental model
🎯 Drill            STAR interview practice prompts
🧪 Labs             3 hands-on mini-labs
🧩 Quiz             20-Q flash recall + answers

▶ Context Options   Expand for role/emphasis/etc

NOTES & QUIZ
─────────────────────────────
Ctrl + Alt + N      Save note (summary view)
Ctrl + Alt + Shift + N  Notes manager
Ctrl + Alt + Q      Start quiz mode

SUMMARY VIEW
─────────────────────────────
Space / Enter       Close and hide window
"""
        
        text_box = ctk.CTkTextbox(
            shortcuts_win,
            font=("Consolas", 11),
            fg_color="#2a2a2a",
            text_color="white",
            wrap="none",
            width=360,
            height=450
        )
        text_box.pack(padx=20, pady=10, fill="both", expand=True)
        text_box.insert("1.0", shortcuts_text)
        text_box.configure(state="disabled")
        
        # Close button
        close_btn = ctk.CTkButton(
            shortcuts_win,
            text="Close",
            width=100,
            command=shortcuts_win.destroy,
            fg_color="#FF6B00",
            hover_color="#FF8C00"
        )
        close_btn.pack(pady=(0, 15))
        
        # Button focus visuals
        close_btn.bind("<FocusIn>", lambda e: close_btn.configure(border_width=2, border_color="#FFFFFF"))
        close_btn.bind("<FocusOut>", lambda e: close_btn.configure(border_width=0))
        close_btn.bind("<Return>", lambda e: shortcuts_win.destroy())
        close_btn.bind("<space>", lambda e: shortcuts_win.destroy())
        
        # Window-level Tab navigation
        focusables = [text_box, close_btn]
        
        def find_focused_index():
            current = shortcuts_win.focus_get()
            for i, widget in enumerate(focusables):
                if current == widget:
                    return i
                if hasattr(widget, '_textbox') and current == widget._textbox:
                    return i
                if hasattr(widget, '_canvas') and current == widget._canvas:
                    return i
                try:
                    if current and str(current).startswith(str(widget)):
                        return i
                except:
                    pass
            return -1
        
        def on_window_tab(e):
            current_idx = find_focused_index()
            next_idx = (current_idx + 1) % len(focusables)
            focusables[next_idx].focus_set()
            return "break"
        
        def on_window_shift_tab(e):
            current_idx = find_focused_index()
            prev_idx = (current_idx - 1) % len(focusables)
            focusables[prev_idx].focus_set()
            return "break"
        
        shortcuts_win.bind("<Tab>", on_window_tab)
        shortcuts_win.bind("<Shift-Tab>", on_window_shift_tab)
        
        # Bind Tab to button directly
        close_btn.bind("<Tab>", on_window_tab)
        close_btn.bind("<Shift-Tab>", on_window_shift_tab)
        
        # Bind to internal textbox to prevent indent
        try:
            internal = text_box._textbox
            internal.bind("<Tab>", on_window_tab)
            internal.bind("<Shift-Tab>", on_window_shift_tab)
        except AttributeError:
            pass
        
        # Close on Escape
        shortcuts_win.bind("<Escape>", lambda e: shortcuts_win.destroy())
        
        debug_log("SHORTCUTS", "Shortcuts window displayed")
    
    def _apply_markdown_formatting(self, text_widget):
        """Apply markdown-style formatting to text in a CTkTextbox widget"""
        import re
        
        # Get the underlying tkinter text widget
        tk_text = text_widget._textbox
        
        # Configure tags for formatting
        tk_text.tag_configure("bold", font=("Segoe UI", 14, "bold"))
        tk_text.tag_configure("italic", font=("Segoe UI", 14, "italic"))
        tk_text.tag_configure("bold_italic", font=("Segoe UI", 14, "bold italic"))
        tk_text.tag_configure("heading", font=("Segoe UI", 16, "bold"), foreground="#FF6B00")
        tk_text.tag_configure("code", font=("Consolas", 13), background="#3a3a3a")
        
        content = tk_text.get("1.0", "end-1c")
        
        # Process bold italic (***text*** or ___text___)
        for match in re.finditer(r'\*\*\*(.+?)\*\*\*|___(.+?)___', content):
            text_match = match.group(1) or match.group(2)
            start_idx = tk_text.search(match.group(0), "1.0", "end")
            if start_idx:
                end_idx = f"{start_idx}+{len(match.group(0))}c"
                tk_text.delete(start_idx, end_idx)
                tk_text.insert(start_idx, text_match, "bold_italic")
        
        # Refresh content after modifications
        content = tk_text.get("1.0", "end-1c")
        
        # Process bold (**text** or __text__)
        for match in re.finditer(r'\*\*(.+?)\*\*|__(.+?)__', content):
            text_match = match.group(1) or match.group(2)
            start_idx = tk_text.search(match.group(0), "1.0", "end")
            if start_idx:
                end_idx = f"{start_idx}+{len(match.group(0))}c"
                tk_text.delete(start_idx, end_idx)
                tk_text.insert(start_idx, text_match, "bold")
        
        # Refresh content after modifications
        content = tk_text.get("1.0", "end-1c")
        
        # Process italic (*text* or _text_) - be careful not to match inside words
        for match in re.finditer(r'(?<![*_])\*([^*]+?)\*(?![*_])|(?<![*_])_([^_]+?)_(?![*_])', content):
            text_match = match.group(1) or match.group(2)
            start_idx = tk_text.search(match.group(0), "1.0", "end")
            if start_idx:
                end_idx = f"{start_idx}+{len(match.group(0))}c"
                tk_text.delete(start_idx, end_idx)
                tk_text.insert(start_idx, text_match, "italic")
        
        # Refresh content after modifications  
        content = tk_text.get("1.0", "end-1c")
        
        # Process inline code (`code`)
        for match in re.finditer(r'`([^`]+?)`', content):
            text_match = match.group(1)
            start_idx = tk_text.search(match.group(0), "1.0", "end")
            if start_idx:
                end_idx = f"{start_idx}+{len(match.group(0))}c"
                tk_text.delete(start_idx, end_idx)
                tk_text.insert(start_idx, text_match, "code")
        
        debug_log("FORMATTING", "Applied markdown formatting to text widget")
    
    def _show_clarify_prompt(self):
        """Show prompt for user to ask a clarifying question about the summary"""
        debug_log("CLARIFY", "Opening clarification prompt")
        
        # Create prompt window
        clarify_win = ctk.CTkToplevel(self.window)
        clarify_win.title("Question?")
        clarify_win.geometry("450x180")
        clarify_win.configure(fg_color="#1a1a1a")
        clarify_win.transient(self.window)
        clarify_win.attributes("-topmost", True)
        clarify_win.lift()
        
        # Center the window
        screen_width = clarify_win.winfo_screenwidth()
        screen_height = clarify_win.winfo_screenheight()
        x = (screen_width - 450) // 2
        y = (screen_height - 180) // 2
        clarify_win.geometry(f"450x180+{x}+{y}")
        
        # Title
        title = ctk.CTkLabel(
            clarify_win,
            text="❓ What would you like clarified?",
            font=("Segoe UI", 16, "bold"),
            text_color="#FF6B00"
        )
        title.pack(pady=(20, 10))
        
        # Question entry
        question_entry = ctk.CTkEntry(
            clarify_win,
            width=400,
            height=40,
            font=("Segoe UI", 14),
            placeholder_text="Type your question here..."
        )
        question_entry.pack(pady=10)
        question_entry.focus_set()
        
        def submit_question(event=None):
            # Ignore Shift+Enter
            if event and event.state & 0x1:
                return
            question = question_entry.get().strip()
            if question:
                clarify_win.destroy()
                self._get_clarification(question, attempt=1)
            return "break"
        
        question_entry.bind("<Return>", submit_question)
        
        # Submit button
        submit_btn = ctk.CTkButton(
            clarify_win,
            text="Ask",
            width=100,
            height=35,
            font=("Segoe UI", 13),
            fg_color="#FF6B00",
            hover_color="#FF8C00",
            command=submit_question
        )
        submit_btn.pack(pady=10)
        
        # Button focus visuals
        submit_btn.bind("<FocusIn>", lambda e: submit_btn.configure(border_width=2, border_color="#FFFFFF"))
        submit_btn.bind("<FocusOut>", lambda e: submit_btn.configure(border_width=0))
        submit_btn.bind("<Return>", lambda e: (submit_question(), "break")[-1])
        
        # Window-level Tab navigation
        focusables = [question_entry, submit_btn]
        
        def find_focused_index():
            current = clarify_win.focus_get()
            for i, widget in enumerate(focusables):
                if current == widget:
                    return i
                if hasattr(widget, '_canvas') and current == widget._canvas:
                    return i
                try:
                    if current and str(current).startswith(str(widget)):
                        return i
                except:
                    pass
            return -1
        
        def on_window_tab(e):
            current_idx = find_focused_index()
            next_idx = (current_idx + 1) % len(focusables)
            focusables[next_idx].focus_set()
            return "break"
        
        def on_window_shift_tab(e):
            current_idx = find_focused_index()
            prev_idx = (current_idx - 1) % len(focusables)
            focusables[prev_idx].focus_set()
            return "break"
        
        clarify_win.bind("<Tab>", on_window_tab)
        clarify_win.bind("<Shift-Tab>", on_window_shift_tab)
        
        # Bind Tab to button directly
        submit_btn.bind("<Tab>", on_window_tab)
        submit_btn.bind("<Shift-Tab>", on_window_shift_tab)
        
        clarify_win.bind("<Escape>", lambda e: clarify_win.destroy())
    
    def _get_clarification(self, question: str, attempt: int = 1, previous_explanations: list = None):
        """Get clarification from OpenAI API"""
        debug_log("CLARIFY", f"Getting clarification (attempt {attempt})", {"question": question})
        
        if previous_explanations is None:
            previous_explanations = []
        
        # Show loading window
        loading_win = ctk.CTkToplevel(self.window)
        loading_win.title("Thinking...")
        loading_win.geometry("300x100")
        loading_win.configure(fg_color="#1a1a1a")
        loading_win.transient(self.window)
        loading_win.attributes("-topmost", True)
        
        # Bind Escape to close
        loading_win.bind("<Escape>", lambda e: loading_win.destroy())
        
        screen_width = loading_win.winfo_screenwidth()
        screen_height = loading_win.winfo_screenheight()
        x = (screen_width - 300) // 2
        y = (screen_height - 100) // 2
        loading_win.geometry(f"300x100+{x}+{y}")
        
        loading_label = ctk.CTkLabel(
            loading_win,
            text="🤔 Thinking..." if attempt == 1 else "🔄 Trying a different approach...",
            font=("Segoe UI", 14),
            text_color="#FF6B00"
        )
        loading_label.pack(expand=True)
        
        def call_api():
            try:
                from openai import OpenAI
                client = OpenAI()
                
                # Build context about previous attempts
                previous_context = ""
                if previous_explanations:
                    previous_context = "\n\nPREVIOUS EXPLANATIONS THAT DIDN'T WORK:\n"
                    for i, exp in enumerate(previous_explanations, 1):
                        previous_context += f"\nAttempt {i}:\n{exp}\n"
                    previous_context += "\nThe user didn't understand those explanations. Try a COMPLETELY DIFFERENT approach."
                
                system_prompt = f"""You are a patient, adaptive tutor helping someone understand a topic they're studying.

CONTEXT:
- The user read some material and received a summary
- They have a specific question about something they don't understand
- Your job is to clarify in a way that creates an "aha!" moment

{"This is attempt " + str(attempt) + ". Previous explanations didn't click." if attempt > 1 else ""}

STRATEGIES FOR CLARIFICATION:
{"- Try a COMPLETELY DIFFERENT analogy or metaphor" if attempt > 1 else "- Use a relatable real-world analogy"}
{"- Simplify further - assume less background knowledge" if attempt > 2 else "- Break it down into smaller pieces"}
{"- Use a concrete example or story" if attempt > 1 else "- Connect it to something familiar"}
- Be conversational and encouraging
- Keep response focused and concise (2-4 short paragraphs max)
- End with a simple one-sentence summary

{previous_context}"""

                original_text = getattr(self, 'last_clipboard_text', '') or getattr(self, 'current_text', '')
                summary = getattr(self, 'summary', '')
                
                user_message = f"""ORIGINAL TEXT:
{original_text[:3000]}

SUMMARY PROVIDED:
{summary}

USER'S QUESTION:
{question}

Please clarify this for me in a way that helps me truly understand."""

                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.7 + (attempt * 0.1),  # Increase creativity with each attempt
                    max_tokens=800
                )
                
                answer = response.choices[0].message.content
                
                # Token tracking
                token_info = {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
                debug_log("CLARIFY", f"Received clarification (attempt {attempt})", {
                    "answer_length": len(answer),
                    "tokens": token_info
                })
                
                # Save backup
                save_api_response_backup(
                    f"CLARIFICATION_ATTEMPT_{attempt}",
                    question[:200],
                    answer,
                    token_info["input_tokens"],
                    token_info["output_tokens"],
                    token_info["total_tokens"],
                    "gpt-4o-mini"
                )
                
                # Show response on main thread
                self.window.after(0, lambda: self._show_clarification_response(
                    question, answer, attempt, previous_explanations + [answer], loading_win, token_info
                ))
                
            except Exception as e:
                debug_log("CLARIFY_ERROR", f"API call failed: {str(e)}")
                self.window.after(0, lambda: self._show_clarification_error(str(e), loading_win))
        
        threading.Thread(target=call_api, daemon=True).start()
    
    def _show_clarification_response(self, question: str, answer: str, attempt: int, all_explanations: list, loading_win, token_info: dict = None):
        """Show the clarification response with OK/Hmm buttons"""
        loading_win.destroy()
        
        debug_log("CLARIFY", f"Showing clarification response (attempt {attempt})")
        
        # Create response window
        response_win = ctk.CTkToplevel(self.window)
        
        # Build title with token info
        title = f"Clarification (Attempt {attempt})"
        if token_info:
            cost = estimate_cost(token_info['input_tokens'], token_info['output_tokens'], token_info.get('model', 'gpt-4o-mini'))
            title += f" | {token_info['total_tokens']} tokens ~{format_cost(cost)}"
        response_win.title(title)
        response_win.geometry("550x500")
        response_win.configure(fg_color="#1a1a1a")
        response_win.transient(self.window)
        response_win.attributes("-topmost", True)
        response_win.lift()
        
        # Center the window
        screen_width = response_win.winfo_screenwidth()
        screen_height = response_win.winfo_screenheight()
        x = (screen_width - 550) // 2
        y = (screen_height - 500) // 2
        response_win.geometry(f"550x500+{x}+{y}")
        
        # Question reminder
        q_label = ctk.CTkLabel(
            response_win,
            text=f"❓ {question[:60]}{'...' if len(question) > 60 else ''}",
            font=("Segoe UI", 12),
            text_color="#888888"
        )
        q_label.pack(pady=(15, 5))
        
        # Attempt indicator
        attempt_label = ctk.CTkLabel(
            response_win,
            text=f"Explanation #{attempt}",
            font=("Segoe UI", 11),
            text_color="#FF6B00"
        )
        attempt_label.pack(pady=(0, 10))
        
        # Answer text
        answer_text = ctk.CTkTextbox(
            response_win,
            width=500,
            height=320,
            font=("Segoe UI", 13),
            fg_color="#2a2a2a",
            text_color="white",
            wrap="word"
        )
        answer_text.pack(padx=20, pady=10)
        answer_text.insert("1.0", answer)
        self._apply_markdown_formatting(answer_text)
        answer_text.configure(state="disabled")
        
        # Buttons frame
        btn_frame = ctk.CTkFrame(response_win, fg_color="#1a1a1a")
        btn_frame.pack(pady=15)
        
        def on_ok():
            response_win.destroy()
            debug_log("CLARIFY", "User understood - closing")
        
        def on_hmm():
            response_win.destroy()
            debug_log("CLARIFY", "User needs different explanation")
            self._get_clarification(question, attempt + 1, all_explanations)
        
        # OK button
        ok_btn = ctk.CTkButton(
            btn_frame,
            text="OK! 👍",
            width=120,
            height=40,
            font=("Segoe UI", 14, "bold"),
            fg_color="#2E7D32",
            hover_color="#388E3C",
            command=on_ok
        )
        ok_btn.pack(side="left", padx=15)
        
        # Hmm button
        hmm_btn = ctk.CTkButton(
            btn_frame,
            text="Hmm.. 🤔",
            width=120,
            height=40,
            font=("Segoe UI", 14, "bold"),
            fg_color="#FF6B00",
            hover_color="#FF8C00",
            command=on_hmm
        )
        hmm_btn.pack(side="left", padx=15)
        
        # Button focus visuals
        for btn in [ok_btn, hmm_btn]:
            btn.bind("<FocusIn>", lambda e, b=btn: b.configure(border_width=2, border_color="#FFFFFF"))
            btn.bind("<FocusOut>", lambda e, b=btn: b.configure(border_width=0))
            btn.bind("<Return>", lambda e, b=btn: b.invoke())
        
        # Window-level Tab navigation
        focusables = [answer_text, ok_btn, hmm_btn]
        
        def find_focused_index():
            current = response_win.focus_get()
            for i, widget in enumerate(focusables):
                if current == widget:
                    return i
                if hasattr(widget, '_textbox') and current == widget._textbox:
                    return i
                if hasattr(widget, '_canvas') and current == widget._canvas:
                    return i
                try:
                    if current and str(current).startswith(str(widget)):
                        return i
                except:
                    pass
            return -1
        
        def on_window_tab(e):
            current_idx = find_focused_index()
            next_idx = (current_idx + 1) % len(focusables)
            focusables[next_idx].focus_set()
            return "break"
        
        def on_window_shift_tab(e):
            current_idx = find_focused_index()
            prev_idx = (current_idx - 1) % len(focusables)
            focusables[prev_idx].focus_set()
            return "break"
        
        response_win.bind("<Tab>", on_window_tab)
        response_win.bind("<Shift-Tab>", on_window_shift_tab)
        
        # Bind Tab to buttons directly
        for btn in [ok_btn, hmm_btn]:
            btn.bind("<Tab>", on_window_tab)
            btn.bind("<Shift-Tab>", on_window_shift_tab)
        
        # Bind to internal textbox to prevent indent
        try:
            internal = answer_text._textbox
            internal.bind("<Tab>", on_window_tab)
            internal.bind("<Shift-Tab>", on_window_shift_tab)
        except AttributeError:
            pass
        
        # Keyboard shortcuts
        def on_return(e):
            if e.state & 0x1:  # Shift key
                return
            on_ok()
            return "break"
        response_win.bind("<Return>", on_return)
        response_win.bind("<space>", lambda e: on_ok())
        response_win.bind("h", lambda e: on_hmm())
        response_win.bind("H", lambda e: on_hmm())
        response_win.bind("<Escape>", lambda e: on_ok())
        
        response_win.focus_set()
    
    def _show_clarification_error(self, error_msg: str, loading_win):
        """Show error if clarification fails"""
        loading_win.destroy()
        self.status_label.configure(text=f"Clarification error: {error_msg[:50]}")
    
    def _extract_title_from_summary(self, summary: str) -> str:
        """Extract title from summary text"""
        lines = summary.split('\n')
        for line in lines:
            if line.strip().startswith('📌 TITLE:'):
                title = line.replace('📌 TITLE:', '').strip()
                debug_log("NOTES", f"Extracted title: {title}")
                return title
                return title
        # Fallback: use first non-empty line
        for line in lines:
            if line.strip() and not line.strip().startswith('⚡'):
                return line.strip()[:50]
        return "Untitled Note"
    
    def _get_next_note_id(self):
        """Get the next available note ID by reading existing notes"""
        try:
            if os.path.exists("Notes.txt"):
                with open("Notes.txt", 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Find all IDs like [NOTE_123]
                    import re
                    ids = re.findall(r'\[NOTE_(\d+)\]', content)
                    if ids:
                        return max(int(i) for i in ids) + 1
        except Exception as e:
            debug_log("NOTES_ERROR", f"Error getting next note ID: {str(e)}")
        return 1
    
    def _save_note(self):
        """Save the current summary to notes file and original text to FullNotes.txt"""
        debug_log("NOTES", "Saving note to file", {"file": self.current_notes_file})
        
        # Get note ID
        note_id = self.note_id_counter
        self.note_id_counter += 1
        
        # Extract title
        title = self._extract_title_from_summary(self.summary)
        self.current_summary_title = title
        
        # Prepare note content with ID
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "-" * 80
        note_content = f"\n[NOTE_{note_id}] {title}\n{timestamp}\n{separator}\n{self.summary}\n{separator}\n\n"
        
        # Prepare full notes content (original text)
        original_text = getattr(self, 'last_clipboard_text', '') or getattr(self, 'current_text', '')
        full_note_content = f"\n[NOTE_{note_id}] {title}\n{timestamp}\n{separator}\n{original_text}\n{separator}\n\n"
        
        try:
            # Append to notes file (summary)
            with open(self.current_notes_file, 'a', encoding='utf-8') as f:
                f.write(note_content)
            
            # Append to FullNotes.txt (original text)
            full_notes_file = self.current_notes_file.replace("Notes", "FullNotes")
            with open(full_notes_file, 'a', encoding='utf-8') as f:
                f.write(full_note_content)
            
            debug_log("NOTES", "Note saved successfully", {"title": title, "id": note_id})
            
            # Show confirmation
            self.status_label.configure(text=f"✓ Saved [NOTE_{note_id}] to {self.current_notes_file}")
            self.window.after(2000, lambda: self.status_label.configure(text="Press ENTER or SPACE to close"))
            
        except Exception as e:
            debug_log("NOTES_ERROR", f"Failed to save note: {str(e)}")
            self.status_label.configure(text=f"✗ Error saving note: {str(e)}")
    
    def _show_notes_manager(self):
        """Show notes file management window (New/Switch)"""
        debug_log("NOTES_MANAGER", "Opening notes manager")
        
        # Create manager window
        manager_win = ctk.CTkToplevel(self.window)
        manager_win.title("Notes Manager")
        manager_win.geometry("350x200")
        manager_win.configure(fg_color="#1a1a1a")
        manager_win.attributes("-topmost", True)
        
        # Center the window
        screen_width = manager_win.winfo_screenwidth()
        screen_height = manager_win.winfo_screenheight()
        x = (screen_width - 350) // 2
        y = (screen_height - 200) // 2
        manager_win.geometry(f"350x200+{x}+{y}")
        
        # Title
        title = ctk.CTkLabel(
            manager_win,
            text="📝 Notes Manager",
            font=("Segoe UI", 18, "bold"),
            text_color="#FF6B00"
        )
        title.pack(pady=(15, 10))
        
        # Current file label
        current_label = ctk.CTkLabel(
            manager_win,
            text=f"Current: {self.current_notes_file}",
            font=("Segoe UI", 11),
            text_color="#888888"
        )
        current_label.pack(pady=(0, 15))
        
        # Buttons frame
        btn_frame = ctk.CTkFrame(manager_win, fg_color="#1a1a1a")
        btn_frame.pack(pady=10)
        
        # New button
        new_btn = ctk.CTkButton(
            btn_frame,
            text="📄 New Notes File",
            width=140,
            height=35,
            font=("Segoe UI", 12),
            fg_color="#4A90D9",
            hover_color="#5BA0E9",
            command=lambda: self._create_new_notes_file(manager_win)
        )
        new_btn.pack(side="left", padx=5)
        
        # Switch button
        switch_btn = ctk.CTkButton(
            btn_frame,
            text="🔄 Switch File",
            width=140,
            height=35,
            font=("Segoe UI", 12),
            fg_color="#FF6B00",
            hover_color="#FF8C00",
            command=lambda: self._show_notes_switcher(manager_win)
        )
        switch_btn.pack(side="left", padx=5)
        
        # Button focus visuals and Tab navigation
        buttons = [new_btn, switch_btn]
        for btn in buttons:
            btn.bind("<FocusIn>", lambda e, b=btn: b.configure(border_width=2, border_color="#FFFFFF"))
            btn.bind("<FocusOut>", lambda e, b=btn: b.configure(border_width=0))
            btn.bind("<Return>", lambda e, b=btn: b.invoke())
        
        def cycle_buttons():
            current = manager_win.focus_get()
            if current == new_btn:
                switch_btn.focus_set()
            else:
                new_btn.focus_set()
        
        manager_win.bind("<Tab>", lambda e: (cycle_buttons(), "break")[-1])
        manager_win.bind("<Shift-Tab>", lambda e: (cycle_buttons(), "break")[-1])
        new_btn.focus_set()
        
        # Close on Escape
        manager_win.bind("<Escape>", lambda e: manager_win.destroy())
        
        debug_log("NOTES_MANAGER", "Notes manager displayed")
    
    def _create_new_notes_file(self, parent_window):
        """Create a new incremented notes file"""
        import glob
        
        # Find existing Notes*.txt files
        existing_files = glob.glob("Notes*.txt")
        
        # Find highest number
        max_num = 0
        for f in existing_files:
            if f == "Notes.txt":
                max_num = max(max_num, 1)
            else:
                try:
                    num = int(f.replace("Notes_", "").replace(".txt", ""))
                    max_num = max(max_num, num)
                except:
                    pass
        
        # Create new file name
        if max_num == 0:
            new_file = "Notes.txt"
        else:
            new_file = f"Notes_{max_num + 1}.txt"
        
        self.current_notes_file = new_file
        debug_log("NOTES", f"Created new notes file: {new_file}")
        
        # Update parent window and close
        parent_window.destroy()
        
        # Show confirmation
        self.status_label.configure(text=f"✓ New notes file: {new_file}")
        self.window.after(2000, lambda: self.status_label.configure(text="Press ENTER or SPACE to close"))
    
    def _show_notes_switcher(self, parent_window):
        """Show list of available notes files to switch to"""
        import glob
        
        # Find all Notes*.txt files
        notes_files = sorted(glob.glob("Notes*.txt"))
        
        if not notes_files:
            debug_log("NOTES", "No notes files found")
            return
        
        parent_window.destroy()
        
        # Create switcher window
        switcher_win = ctk.CTkToplevel(self.window)
        switcher_win.title("Switch Notes File")
        switcher_win.geometry("300x400")
        switcher_win.configure(fg_color="#1a1a1a")
        switcher_win.attributes("-topmost", True)
        
        # Center the window
        screen_width = switcher_win.winfo_screenwidth()
        screen_height = switcher_win.winfo_screenheight()
        x = (screen_width - 300) // 2
        y = (screen_height - 400) // 2
        switcher_win.geometry(f"300x400+{x}+{y}")
        
        # Title
        title = ctk.CTkLabel(
            switcher_win,
            text="Select Notes File",
            font=("Segoe UI", 16, "bold"),
            text_color="#FF6B00"
        )
        title.pack(pady=(15, 10))
        
        # Scrollable frame for files
        scroll_frame = ctk.CTkScrollableFrame(
            switcher_win,
            width=260,
            height=300,
            fg_color="#2a2a2a"
        )
        scroll_frame.pack(padx=20, pady=10, fill="both", expand=True)
        
        # Track buttons for Tab navigation
        file_buttons = []
        
        # Create button for each file
        for notes_file in notes_files:
            is_current = notes_file == self.current_notes_file
            
            btn = ctk.CTkButton(
                scroll_frame,
                text=f"{'✓ ' if is_current else ''}{notes_file}",
                width=240,
                height=35,
                font=("Segoe UI", 11),
                fg_color="#FF6B00" if is_current else "#3a3a3a",
                hover_color="#FF8C00" if is_current else "#4a4a4a",
                command=lambda f=notes_file: self._switch_to_notes_file(f, switcher_win)
            )
            btn.pack(pady=5)
            # Button focus visuals
            btn.bind("<FocusIn>", lambda e, b=btn: b.configure(border_width=2, border_color="#FFFFFF"))
            btn.bind("<FocusOut>", lambda e, b=btn: b.configure(border_width=0))
            btn.bind("<Return>", lambda e, b=btn: b.invoke())
            file_buttons.append(btn)
        
        # Tab navigation between file buttons
        def on_tab(event):
            current = switcher_win.focus_get()
            try:
                idx = file_buttons.index(current)
                next_idx = (idx + 1) % len(file_buttons)
            except ValueError:
                next_idx = 0
            file_buttons[next_idx].focus_set()
            return "break"
        
        def on_shift_tab(event):
            current = switcher_win.focus_get()
            try:
                idx = file_buttons.index(current)
                prev_idx = (idx - 1) % len(file_buttons)
            except ValueError:
                prev_idx = 0
            file_buttons[prev_idx].focus_set()
            return "break"
        
        switcher_win.bind("<Tab>", on_tab)
        switcher_win.bind("<Shift-Tab>", on_shift_tab)
        
        # Focus first button (or current file button)
        if file_buttons:
            for i, notes_file in enumerate(notes_files):
                if notes_file == self.current_notes_file:
                    file_buttons[i].focus_set()
                    break
            else:
                file_buttons[0].focus_set()
        
        # Close on Escape
        switcher_win.bind("<Escape>", lambda e: switcher_win.destroy())
    
    def _switch_to_notes_file(self, notes_file, switcher_window):
        """Switch to a different notes file"""
        self.current_notes_file = notes_file
        debug_log("NOTES", f"Switched to notes file: {notes_file}")
        
        switcher_window.destroy()
        
        # Show confirmation
        self.status_label.configure(text=f"✓ Switched to {notes_file}")
        self.window.after(2000, lambda: self.status_label.configure(text="Press ENTER or SPACE to close"))

    def _toggle_window(self, shift_held=False):
        """Toggle window visibility - called on main thread"""
        debug_log("TOGGLE", "Toggling window visibility", {"current_visible": self.is_visible, "shift_held": shift_held})
        
        if self.is_visible:
            debug_log("TOGGLE", "Window is visible, hiding it")
            self.hide_window()
        else:
            if shift_held:
                debug_log("TOGGLE", "SHIFT+F3 pressed - showing summary immediately")
                self.show_window()
                self.show_summary_immediately()
            else:
                debug_log("TOGGLE", "Window is not visible, showing it")
                self.show_window()
    
    def create_window(self):
        """Create the CustomTkinter window"""
        debug_log("WINDOW", "Creating new window")
        
        # Set appearance mode
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        debug_log("WINDOW", "Set dark appearance mode and blue theme")
        
        # Create main window
        self.window = ctk.CTk()
        self.window.title("Spreeder")
        
        # Window dimensions
        window_width = 600
        window_height = 520  # Taller to accommodate both sliders and progress bar
        
        # Get screen dimensions and calculate center position
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        center_x = (screen_width - window_width) // 2
        center_y = (screen_height - window_height) // 2
        
        debug_log("WINDOW_CENTER", "Calculating center position", {
            "screen_width": screen_width,
            "screen_height": screen_height,
            "window_width": window_width,
            "window_height": window_height,
            "center_x": center_x,
            "center_y": center_y
        })
        
        # Set geometry with position
        self.window.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")
        self.window.configure(fg_color="#1a1a1a")  # Dark background
        
        # Configure title bar colors (Windows-specific workaround)
        try:
            self.window.wm_attributes("-topmost", True)
            debug_log("WINDOW", "Set window to always on top")
        except Exception as e:
            debug_log("WINDOW_ERROR", f"Could not set topmost: {str(e)}")
        
        # Set up global event logging for main window
        setup_global_event_logging(self.window, "Main Spreeder")
        
        # Bind window events
        self.window.bind("<FocusIn>", self.on_window_focus_in)
        self.window.bind("<FocusOut>", self.on_window_focus_out)
        self.window.bind("<Configure>", self.on_window_configure)
        self.window.protocol("WM_DELETE_WINDOW", self.on_window_close)
        debug_log("WINDOW", "Window events bound")
        
        # Bind keyboard events
        self.window.bind("<space>", self.on_space_pressed)
        # SHIFT+F3 now shows summary immediately (handled in on_f3_pressed)
        self.window.bind("<Return>", self.on_enter_pressed)
        self.window.bind("<Escape>", self.on_escape_pressed)
        self.window.bind("<Left>", self.on_left_arrow_pressed)
        self.window.bind("<Right>", self.on_right_arrow_pressed)
        self.window.bind("<KeyRelease-Left>", self.on_arrow_released)
        self.window.bind("<KeyRelease-Right>", self.on_arrow_released)
        self.window.bind("<KeyPress>", self.on_any_key_pressed)
        self.window.bind("<KeyRelease>", self.on_any_key_released)
        self.window.bind("<Control-equal>", self.on_expand_vertical)
        self.window.bind("<Control-plus>", self.on_expand_vertical)  # For numpad
        self.window.bind("<Control-Shift-equal>", self.on_maximize)
        self.window.bind("<Control-Shift-plus>", self.on_maximize)  # For numpad
        self.window.bind("<Control-Alt-equal>", self.on_fullscreen)
        self.window.bind("<Control-Alt-plus>", self.on_fullscreen)  # For numpad
        self.window.bind("<Control-Alt-n>", self.on_save_note)
        self.window.bind("<Control-Alt-N>", self.on_notes_manager)
        # Note: Ctrl+Alt+F3 is handled by keyboard library in on_f3_pressed (not tkinter binding)
        self.window.bind("<Control-space>", self.on_ctrl_space_pressed)
        self.window.bind("<Control-Alt-space>", self.on_ctrl_alt_space_pressed)
        debug_log("WINDOW", "Keyboard events bound")
        
        # Bind mouse events to window
        self.window.bind("<Button-1>", self.on_mouse_click)
        self.window.bind("<Button-2>", self.on_mouse_click)
        self.window.bind("<Button-3>", self.on_mouse_click)
        self.window.bind("<Motion>", self.on_mouse_motion)
        self.window.bind("<Enter>", self.on_mouse_enter_window)
        self.window.bind("<Leave>", self.on_mouse_leave_window)
        self.window.bind("<MouseWheel>", self.on_mouse_wheel)
        debug_log("WINDOW", "Mouse events bound to window")
        
        self.create_ui_elements()
        debug_log("WINDOW", "Window creation complete")
    
    def create_ui_elements(self):
        """Create all UI elements"""
        debug_log("UI", "Creating UI elements")
        
        # Main frame
        main_frame = ctk.CTkFrame(self.window, fg_color="#1a1a1a")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        main_frame.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "main_frame"))
        main_frame.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "main_frame"))
        main_frame.bind("<Button-1>", lambda e: self.on_widget_click(e, "main_frame"))
        
        # Status label at top
        self.status_label = ctk.CTkLabel(
            main_frame,
            text="Press SPACE to start | F3 to close | SHIFT+F3 for summary",
            font=("Segoe UI", 12),
            text_color="#888888"
        )
        self.status_label.pack(pady=(0, 20))
        self.status_label.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "status_label"))
        self.status_label.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "status_label"))
        self.status_label.bind("<Button-1>", lambda e: self.on_widget_click(e, "status_label"))
        debug_log("UI", "Created status label")
        
        # Word display area
        self.word_frame = ctk.CTkFrame(main_frame, fg_color="#2a2a2a", corner_radius=10)
        self.word_frame.pack(fill="both", expand=True, pady=10)
        self.word_frame.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "word_frame"))
        self.word_frame.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "word_frame"))
        self.word_frame.bind("<Button-1>", lambda e: self.on_widget_click(e, "word_frame"))
        
        # Word label (using Comic Sans as specified)
        self.word_label = ctk.CTkLabel(
            self.word_frame,
            text="Ready",
            font=("Comic Sans MS", 48, "bold"),
            text_color="white"
        )
        self.word_label.pack(expand=True)
        self.word_label.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "word_label"))
        self.word_label.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "word_label"))
        self.word_label.bind("<Button-1>", lambda e: self.on_widget_click(e, "word_label"))
        debug_log("UI", "Created word label with Comic Sans font")
        
        # Summary text area (initially hidden)
        self.summary_text = ctk.CTkTextbox(
            self.word_frame,
            font=("Segoe UI", 14),
            fg_color="#2a2a2a",
            text_color="white",
            wrap="word"
        )
        self.summary_text.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "summary_text"))
        self.summary_text.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "summary_text"))
        self.summary_text.bind("<Button-1>", lambda e: self.on_widget_click(e, "summary_text"))
        self.summary_text.bind("<KeyPress>", lambda e: self.on_widget_keypress(e, "summary_text"))
        debug_log("UI", "Created summary text area")
        
        # WPM control frame
        wpm_frame = ctk.CTkFrame(main_frame, fg_color="#1a1a1a")
        wpm_frame.pack(fill="x", pady=(20, 0))
        wpm_frame.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "wpm_frame"))
        wpm_frame.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "wpm_frame"))
        
        # WPM label
        self.wpm_label = ctk.CTkLabel(
            wpm_frame,
            text=f"WPM: {self.wpm}",
            font=("Segoe UI", 14),
            text_color="white"
        )
        self.wpm_label.pack(side="left", padx=(0, 10))
        self.wpm_label.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "wpm_label"))
        self.wpm_label.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "wpm_label"))
        self.wpm_label.bind("<Button-1>", lambda e: self.on_widget_click(e, "wpm_label"))
        debug_log("UI", "Created WPM label")
        
        # WPM slider
        self.wpm_slider = ctk.CTkSlider(
            wpm_frame,
            from_=100,
            to=1000,
            number_of_steps=90,
            command=self.on_wpm_change,
            fg_color="#3a3a3a",
            progress_color="#FF6B00",  # Orange
            button_color="#FF6B00",
            button_hover_color="#FF8C00"
        )
        self.wpm_slider.set(self.wpm)
        self.wpm_slider.pack(side="left", fill="x", expand=True)
        self.wpm_slider.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "wpm_slider"))
        self.wpm_slider.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "wpm_slider"))
        self.wpm_slider.bind("<Button-1>", lambda e: self.on_widget_click(e, "wpm_slider"))
        self.wpm_slider.bind("<ButtonRelease-1>", lambda e: self.on_slider_release(e))
        debug_log("UI", "Created WPM slider")
        
        # Shortcuts button
        shortcuts_btn = ctk.CTkButton(
            wpm_frame,
            text="⌨",
            width=30,
            height=28,
            font=("Segoe UI", 14),
            fg_color="#3a3a3a",
            hover_color="#4a4a4a",
            command=self._show_shortcuts
        )
        shortcuts_btn.pack(side="right", padx=(10, 0))
        shortcuts_btn.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "shortcuts_btn"))
        shortcuts_btn.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "shortcuts_btn"))
        debug_log("UI", "Created shortcuts button")
        
        debug_log("UI", "All UI elements created successfully")
    
    # ==================== EVENT HANDLERS ====================
    
    def on_window_focus_in(self, event):
        """Log when window gains focus"""
        debug_log("FOCUS", "Window gained focus", {"event": str(event)})
    
    def on_window_focus_out(self, event):
        """Log when window loses focus"""
        debug_log("FOCUS", "Window lost focus", {"event": str(event)})
    
    def on_window_configure(self, event):
        """Log window configuration changes (resize, move)"""
        if event.widget == self.window:
            debug_log("WINDOW_CONFIG", "Window configured", {
                "width": event.width,
                "height": event.height,
                "x": event.x,
                "y": event.y
            })
    
    def on_window_close(self):
        """Handle window close button click"""
        debug_log("WINDOW", "Window close button clicked")
        self.hide_window()
    
    def on_mouse_click(self, event):
        """Log all mouse clicks on window"""
        debug_log("MOUSE_CLICK", f"Mouse button {event.num} clicked on window", {
            "x": event.x,
            "y": event.y,
            "x_root": event.x_root,
            "y_root": event.y_root,
            "button": event.num
        })
    
    def on_widget_click(self, event, widget_name):
        """Log clicks on specific widgets"""
        debug_log("WIDGET_CLICK", f"Click on {widget_name}", {
            "x": event.x,
            "y": event.y,
            "widget": widget_name
        })
    
    def on_mouse_motion(self, event):
        """Log mouse movement (throttled to avoid spam)"""
        # Only log every 50 pixels of movement to reduce spam
        if not hasattr(self, '_last_motion_log'):
            self._last_motion_log = (0, 0)
        
        if abs(event.x - self._last_motion_log[0]) > 50 or abs(event.y - self._last_motion_log[1]) > 50:
            debug_log("MOUSE_MOTION", "Mouse moved significantly", {
                "x": event.x,
                "y": event.y
            })
            self._last_motion_log = (event.x, event.y)
    
    def on_mouse_enter_window(self, event):
        """Log when mouse enters window"""
        debug_log("MOUSE_ENTER", "Mouse entered window", {"x": event.x, "y": event.y})
    
    def on_mouse_leave_window(self, event):
        """Log when mouse leaves window"""
        debug_log("MOUSE_LEAVE", "Mouse left window", {"x": event.x, "y": event.y})
    
    def on_mouse_enter_widget(self, event, widget_name):
        """Log when mouse enters a widget (hover)"""
        debug_log("HOVER_ENTER", f"Mouse hovering over {widget_name}", {
            "widget": widget_name,
            "x": event.x,
            "y": event.y
        })
    
    def on_mouse_leave_widget(self, event, widget_name):
        """Log when mouse leaves a widget"""
        debug_log("HOVER_LEAVE", f"Mouse left {widget_name}", {
            "widget": widget_name,
            "x": event.x,
            "y": event.y
        })
    
    def on_mouse_wheel(self, event):
        """Log mouse wheel events"""
        direction = "up" if event.delta > 0 else "down"
        debug_log("MOUSE_WHEEL", f"Mouse wheel scrolled {direction}", {
            "delta": event.delta,
            "x": event.x,
            "y": event.y
        })
    
    def on_any_key_pressed(self, event):
        """Log all key presses"""
        debug_log("KEYPRESS", f"Key pressed: {event.keysym}", {
            "keysym": event.keysym,
            "keycode": event.keycode,
            "char": repr(event.char),
            "state": event.state
        })
    
    def on_any_key_released(self, event):
        """Log all key releases"""
        debug_log("KEYRELEASE", f"Key released: {event.keysym}", {
            "keysym": event.keysym,
            "keycode": event.keycode
        })
    
    def on_widget_keypress(self, event, widget_name):
        """Log keypress on specific widget"""
        debug_log("WIDGET_KEYPRESS", f"Key '{event.keysym}' pressed on {widget_name}", {
            "widget": widget_name,
            "keysym": event.keysym
        })
    
    def on_slider_release(self, event):
        """Log when slider is released"""
        debug_log("SLIDER_RELEASE", "WPM slider released", {"final_wpm": self.wpm})
    
    def on_wpm_change(self, value):
        """Handle WPM slider change"""
        self.wpm = int(value)
        debug_log("WPM_CHANGE", f"WPM changed to {self.wpm}", {"new_wpm": self.wpm})
        
        if self.wpm_label:
            self.wpm_label.configure(text=f"WPM: {self.wpm}")
        
        # Save settings
        self.settings["wpm"] = self.wpm
        save_settings(self.settings)
    
    def on_pause_slider_release(self, event):
        """Log when pause slider is released"""
        debug_log("SLIDER_RELEASE", "Pause delay slider released", {"final_pause_delay": self.pause_delay})
    
    def on_pause_change(self, value):
        """Handle pause delay slider change"""
        self.pause_delay = int(value)
        debug_log("PAUSE_CHANGE", f"Pause delay changed to {self.pause_delay}ms", {"new_pause_delay": self.pause_delay})
        
        if self.pause_label:
            self.pause_label.configure(text=f"Pause: {self.pause_delay}ms")
        
        # Save settings
        self.settings["pause_delay"] = self.pause_delay
        save_settings(self.settings)
    
    def on_space_pressed(self, event):
        """Handle spacebar press - start/pause/resume playback. Shift+Space = show summary after."""
        shift_held = bool(event.state & 0x1)
        debug_log("KEYPRESS_SPACE", "Spacebar pressed", {
            "is_playing": self.is_playing,
            "is_paused": self.is_paused,
            "shift_held": shift_held
        })
        
        if self.is_playing:
            # Pause playback (not stop)
            debug_log("PLAYBACK", "Pausing playback")
            self.is_paused = True
            self.stop_playback = True
            self.status_label.configure(text="PAUSED - Use ← → arrows to navigate | SPACE to resume")
        elif self.is_paused:
            # Resume from paused position
            debug_log("PLAYBACK", "Resuming playback from paused position")
            self.is_paused = False
            self.resume_playback()
        else:
            # Start fresh playback
            # Shift+Space = generate and show summary after playback completes
            self.summary_after_playback = shift_held
            if shift_held:
                debug_log("PLAYBACK", "Shift+Space: will show summary after playback")
                # Start background summary generation if not already done
                if not self.summary_ready and not (self.summary_thread and self.summary_thread.is_alive()):
                    self.summary_thread = threading.Thread(target=self.generate_summary_async, daemon=True)
                    self.summary_thread.start()
            self.start_playback()
        
        return "break"  # Prevent default handling
    
    def on_shift_space_pressed(self, event):
        """Deprecated - SHIFT+F3 now shows summary instead"""
        # Kept for compatibility but no longer bound
        debug_log("KEYPRESS_SHIFT_SPACE", "Shift+Space pressed (deprecated)", {})
        return "break"
    
    def on_ctrl_space_pressed(self, event):
        """Handle Ctrl+Space - simplify the current text with progressively simpler explanations."""
        debug_log("KEYPRESS_CTRL_SPACE", "Ctrl+Space pressed", {
            "is_playing": self.is_playing,
            "has_explanations": bool(self.simplified_explanations),
            "current_index": self.current_explanation_index,
            "has_text": bool(self.current_text)
        })
        
        # Only works at end of playback (not during playback or when paused)
        if self.is_playing or self.is_paused:
            debug_log("CTRL_SPACE", "Ignored - playback in progress or paused")
            return "break"
        
        # If we already have explanations and haven't used them all
        if self.simplified_explanations:
            if self.current_explanation_index < 2:
                # Show next simpler explanation
                self.current_explanation_index += 1
                next_explanation = self.simplified_explanations[self.current_explanation_index]
                debug_log("CTRL_SPACE", f"Showing explanation level {self.current_explanation_index + 1}")
                self._load_simplified_text(next_explanation)
            else:
                # Already at simplest explanation
                debug_log("CTRL_SPACE", "Already at simplest explanation (level 3)")
                self.status_label.configure(text="Already at simplest level! SPACE to replay | F3 to close")
            return "break"
        
        # No explanations yet - need to fetch them
        if not self.current_text:
            debug_log("CTRL_SPACE", "No text to simplify")
            return "break"
        
        # Store source text and reset state
        self.simplify_source_text = self.current_text
        self.simplified_explanations = []
        self.current_explanation_index = 0
        
        # Show loading status
        self.status_label.configure(text="Generating simpler explanations...")
        self.word_label.configure(text="⏳")
        
        # Fetch explanations in background thread
        def fetch_and_show():
            debug_log("CTRL_SPACE", "Fetching simplified explanations in background")
            explanations = get_simplified_explanations(self.simplify_source_text)
            self.simplified_explanations = explanations
            # Show first explanation on main thread
            self.window.after(0, lambda: self._load_simplified_text(explanations[0]))
        
        self.simplify_thread = threading.Thread(target=fetch_and_show, daemon=True)
        self.simplify_thread.start()
        
        return "break"
    
    def _load_simplified_text(self, text: str):
        """Load simplified text into the serial reader and auto-start playback."""
        debug_log("SIMPLIFY_LOAD", "Loading simplified text", {
            "text_length": len(text),
            "explanation_level": self.current_explanation_index + 1
        })
        
        # Update current text
        self.current_text = text
        self.words = text.split()
        self.current_word_index = 0
        
        # Update status based on remaining explanations
        level = self.current_explanation_index + 1
        if level < 3:
            self.status_label.configure(text=f"Explanation {level}/3 - Press SPACE to start | CTRL+SPACE for simpler")
        else:
            self.status_label.configure(text=f"Simplest explanation (3/3) - Press SPACE to start")
        
        # Show first word as preview
        if self.words:
            self.word_label.configure(text=self.words[0])
    
    def on_ctrl_alt_space_pressed(self, event):
        """Handle Ctrl+Alt+Space - toggle between serial reader and full text view."""
        debug_log("KEYPRESS_CTRL_ALT_SPACE", "Ctrl+Alt+Space pressed", {
            "full_text_view_mode": self.full_text_view_mode,
            "is_playing": self.is_playing,
            "has_text": bool(self.current_text)
        })
        
        # Must have text to toggle
        if not self.current_text:
            debug_log("CTRL_ALT_SPACE", "No text to display")
            return "break"
        
        # Stop any ongoing playback
        if self.is_playing:
            self.stop_playback = True
            self.is_playing = False
            self.is_paused = False
        
        # Toggle the view mode
        self.full_text_view_mode = not self.full_text_view_mode
        
        if self.full_text_view_mode:
            # Switch to full text view
            debug_log("CTRL_ALT_SPACE", "Switching to full text view")
            self._show_full_text_view()
        else:
            # Switch back to serial reader view
            debug_log("CTRL_ALT_SPACE", "Switching to serial reader view")
            self._show_serial_reader_view()
        
        return "break"
    
    def _show_full_text_view(self):
        """Display current text in full textbox view (like summary)."""
        debug_log("VIEW_TOGGLE", "Showing full text view", {"text_length": len(self.current_text)})
        
        # Hide word display elements, show summary text area
        self.word_label.pack_forget()
        if hasattr(self, 'word_canvas') and self.word_canvas:
            self.word_canvas.pack_forget()
        if hasattr(self, 'word_frame') and self.word_frame:
            self.word_frame.pack_forget()
        
        # Show summary text with current text
        self.summary_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", self.current_text)
        self._apply_markdown_formatting(self.summary_text)
        self.summary_text.configure(state="disabled")
        
        # Update status
        self.status_label.configure(text="Full text view | CTRL+ALT+SPACE to toggle back | F3 to close")
    
    def _show_serial_reader_view(self):
        """Switch back to serial reader view from full text view."""
        debug_log("VIEW_TOGGLE", "Showing serial reader view")
        
        # Hide summary text
        self.summary_text.pack_forget()
        
        # Show word display elements
        if hasattr(self, 'word_frame') and self.word_frame:
            self.word_frame.pack(fill="both", expand=True, pady=10)
        if hasattr(self, 'word_canvas') and self.word_canvas:
            self.word_canvas.pack(fill="both", expand=True)
        self.word_label.pack(expand=True)
        
        # Show current word or "Ready"
        if self.words and self.current_word_index < len(self.words):
            current_word = self.words[self.current_word_index]
            self.word_label.configure(text=current_word)
            if hasattr(self, 'draw_word_on_canvas'):
                self.draw_word_on_canvas(current_word, -1)
        else:
            self.word_label.configure(text="Ready")
            if hasattr(self, 'draw_word_on_canvas'):
                self.draw_word_on_canvas("Ready", -1)
        
        # Update status
        self.status_label.configure(text="Serial reader | SPACE to start | CTRL+ALT+SPACE for full text | F3 to close")
    
    def on_enter_pressed(self, event):
        """Handle Enter key - close summary view or skip to full answer"""
        debug_log("KEYPRESS_ENTER", "Enter key pressed", {
            "quick_answer_mode": getattr(self, 'quick_answer_mode', False),
            "is_playing": self.is_playing,
            "summary_visible": self.summary_text.winfo_viewable() if self.summary_text else False
        })
        
        # If in quick answer mode and not yet playing, skip to full answer
        if getattr(self, 'quick_answer_mode', False) and not self.is_playing:
            debug_log("QUICK_QUESTION", "Skipping serial reader, showing full answer")
            self._show_answer(self.quick_answer)
            return "break"
        
        # If summary is visible, close the window
        if self.summary_text.winfo_viewable():
            debug_log("SUMMARY", "Closing summary view on Enter")
            self.hide_window()
        
        return "break"
    
    def on_escape_pressed(self, event):
        """Handle Escape key - hide window"""
        debug_log("KEYPRESS_ESCAPE", "Escape key pressed")
        self.hide_window()
        return "break"
    
    def on_expand_vertical(self, event):
        """Handle Ctrl+= - reset to original width, expand vertically to fill screen"""
        debug_log("KEYPRESS_CTRL_EQUAL", "Ctrl+= pressed - resetting to original width, expanding vertically")
        
        # Exit fullscreen if active
        try:
            if self.window.attributes('-fullscreen'):
                self.window.attributes('-fullscreen', False)
                debug_log("WINDOW_EXPAND", "Exited fullscreen mode")
        except Exception:
            pass
        
        # Restore from maximized state if needed
        try:
            if self.window.state() == 'zoomed':
                self.window.state('normal')
                debug_log("WINDOW_EXPAND", "Restored from maximized state")
                # Small delay to let state change take effect
                self.window.update_idletasks()
        except Exception:
            pass
        
        # Get screen dimensions
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        
        # Use original window width (600)
        original_width = 600
        
        # Taskbar is typically 40px on Windows, use 48 for safety margin
        taskbar_height = 48
        new_height = screen_height - taskbar_height
        
        # Center horizontally
        center_x = (screen_width - original_width) // 2
        
        debug_log("WINDOW_EXPAND", "Resetting to original width, expanding vertically", {
            "screen_height": screen_height,
            "taskbar_height": taskbar_height,
            "new_height": new_height,
            "original_width": original_width,
            "x_position": center_x
        })
        
        # Set window geometry: width x height + x + y
        self.window.geometry(f"{original_width}x{new_height}+{center_x}+0")
        
        return "break"
    
    def on_maximize(self, event):
        """Handle Ctrl+Shift+= - maximize window"""
        debug_log("KEYPRESS_CTRL_SHIFT_EQUAL", "Ctrl+Shift+= pressed - maximizing window")
        
        # Toggle maximize state
        try:
            if self.window.state() == 'zoomed':
                self.window.state('normal')
                debug_log("WINDOW_MAXIMIZE", "Window restored to normal")
            else:
                self.window.state('zoomed')
                debug_log("WINDOW_MAXIMIZE", "Window maximized")
        except Exception as e:
            debug_log("WINDOW_MAXIMIZE_ERROR", f"Failed to maximize: {str(e)}")
        
        return "break"
    
    def on_fullscreen(self, event):
        """Handle Ctrl+Alt+= - toggle fullscreen"""
        debug_log("KEYPRESS_CTRL_ALT_EQUAL", "Ctrl+Alt+= pressed - toggling fullscreen")
        
        # Toggle fullscreen state
        try:
            current_fullscreen = self.window.attributes('-fullscreen')
            self.window.attributes('-fullscreen', not current_fullscreen)
            
            if not current_fullscreen:
                debug_log("WINDOW_FULLSCREEN", "Entered fullscreen mode")
            else:
                debug_log("WINDOW_FULLSCREEN", "Exited fullscreen mode")
        except Exception as e:
            debug_log("WINDOW_FULLSCREEN_ERROR", f"Failed to toggle fullscreen: {str(e)}")
        
        return "break"
    
    def on_save_note(self, event=None):
        """Handle Ctrl+Alt+N - save current summary to notes, or generate from clipboard if no summary visible"""
        debug_log("KEYPRESS_CTRL_ALT_N", "Ctrl+Alt+N pressed - saving note")
        
        if self.summary and self.summary_text and self.summary_text.winfo_viewable():
            # Summary is visible, save it directly
            self._save_note()
        else:
            # No summary visible - get clipboard, generate summary in background, save without showing windows
            debug_log("NOTES", "No summary visible - generating from clipboard silently")
            self._save_note_from_clipboard_silent()
        
        return "break"
    
    def _save_note_from_clipboard_silent(self):
        """Generate summary from clipboard and save to notes without showing windows"""
        try:
            clipboard_text = pyperclip.paste()
            if not clipboard_text or len(clipboard_text.strip()) < 10:
                debug_log("NOTES", "Clipboard empty or too short")
                self.status_label.configure(text="✗ Clipboard empty or too short")
                return
            
            # Store the clipboard text for saving
            self.last_clipboard_text = clipboard_text
            
            # Show brief status
            self.status_label.configure(text="📝 Generating summary...")
            
            def generate_and_save():
                try:
                    # Generate summary
                    summary = get_summary(clipboard_text)
                    
                    # Save on main thread
                    self.window.after(0, lambda: self._save_note_silent(summary, clipboard_text))
                except Exception as e:
                    debug_log("NOTES_ERROR", f"Failed to generate summary: {str(e)}")
                    self.window.after(0, lambda: self.status_label.configure(text=f"✗ Error: {str(e)}"))
            
            thread = threading.Thread(target=generate_and_save, daemon=True)
            thread.start()
            
        except Exception as e:
            debug_log("NOTES_ERROR", f"Failed to get clipboard: {str(e)}")
            self.status_label.configure(text=f"✗ Error: {str(e)}")
    
    def _save_note_silent(self, summary: str, original_text: str):
        """Save summary and original text to notes files without UI changes"""
        debug_log("NOTES", "Saving note silently", {"file": self.current_notes_file})
        
        # Get note ID
        note_id = self.note_id_counter
        self.note_id_counter += 1
        
        # Extract title
        title = self._extract_title_from_summary(summary)
        
        # Prepare note content with ID
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "-" * 80
        note_content = f"\n[NOTE_{note_id}] {title}\n{timestamp}\n{separator}\n{summary}\n{separator}\n\n"
        
        # Prepare full notes content (original text)
        full_note_content = f"\n[NOTE_{note_id}] {title}\n{timestamp}\n{separator}\n{original_text}\n{separator}\n\n"
        
        try:
            # Append to notes file (summary)
            with open(self.current_notes_file, 'a', encoding='utf-8') as f:
                f.write(note_content)
            
            # Append to FullNotes.txt (original text)
            full_notes_file = self.current_notes_file.replace("Notes", "FullNotes")
            with open(full_notes_file, 'a', encoding='utf-8') as f:
                f.write(full_note_content)
            
            debug_log("NOTES", "Note saved silently", {"title": title, "id": note_id})
            
            # Show fading toast notification
            self._show_fading_toast("✓ Saved notes!")
            
        except Exception as e:
            debug_log("NOTES_ERROR", f"Failed to save note: {str(e)}")
            self._show_fading_toast(f"✗ Error: {str(e)[:20]}")
    
    def _show_fading_toast(self, message: str):
        """Show a brief fading toast notification"""
        # Create small toast window
        toast = ctk.CTkToplevel()
        toast.overrideredirect(True)  # No window decorations
        toast.attributes("-topmost", True)
        toast.configure(fg_color="#2a2a2a")
        
        # Size and position (center of screen)
        width, height = 200, 50
        screen_width = toast.winfo_screenwidth()
        screen_height = toast.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        toast.geometry(f"{width}x{height}+{x}+{y}")
        
        # Message label
        label = ctk.CTkLabel(
            toast,
            text=message,
            font=("Segoe UI", 14, "bold"),
            text_color="#FF6B00"
        )
        label.pack(expand=True)
        
        # Start fully visible
        toast.attributes("-alpha", 1.0)
        
        # Fade out over 500ms (10 steps of 50ms each)
        def fade_step(alpha):
            if alpha <= 0:
                toast.destroy()
                return
            toast.attributes("-alpha", alpha)
            toast.after(50, lambda: fade_step(alpha - 0.1))
        
        # Start fading immediately
        toast.after(10, lambda: fade_step(1.0))
    
    def on_notes_manager(self, event):
        """Handle Ctrl+Alt+Shift+N - open notes manager"""
        debug_log("KEYPRESS_CTRL_ALT_SHIFT_N", "Ctrl+Alt+Shift+N pressed - opening notes manager")
        
        self._show_notes_manager()
        
        return "break"
    
    def on_quick_question(self, event=None):
        """Handle Ctrl+Q - open quick question prompt with format selection"""
        debug_log("KEYPRESS_CTRL_Q", "Ctrl+Q pressed - opening quick question")
        
        self._show_quick_question_dialog()
        
        return "break"
    
    def _show_quick_question_dialog(self):
        """Show quick question dialog with format buttons"""
        # Check if we're already in the process of creating a dialog
        if hasattr(self, '_qq_dialog_creating') and self._qq_dialog_creating:
            debug_log("QUICK_QUESTION", "Debounced - dialog creation in progress")
            return
        
        # Check if dialog window already exists and is visible
        if hasattr(self, '_qq_dialog_window') and self._qq_dialog_window:
            try:
                if self._qq_dialog_window.winfo_exists():
                    debug_log("QUICK_QUESTION", "Debounced - dialog window already exists")
                    self._qq_dialog_window.lift()
                    self._qq_dialog_window.focus_force()
                    return
            except:
                pass  # Window was destroyed, continue to create new one
        
        # Set sentinel FIRST to prevent concurrent creation
        self._qq_dialog_creating = True
        
        debug_log("QUICK_QUESTION", "Opening quick question dialog")
        
        # Create dialog window and store reference
        qq_window = ctk.CTkToplevel(self.window)
        self._qq_dialog_window = qq_window  # Store reference for duplicate check
        qq_window.title("Quick Question")
        qq_window.geometry("550x320")
        qq_window.configure(fg_color="#1a1a1a")
        qq_window.transient(self.window)
        qq_window.attributes("-topmost", True)
        qq_window.lift()
        
        # Clear sentinel after window is created
        self._qq_dialog_creating = False
        
        # Clear reference when window is closed
        def on_dialog_close():
            self._qq_dialog_window = None
            qq_window.destroy()
        
        qq_window.protocol("WM_DELETE_WINDOW", on_dialog_close)
        
        # Set up global event logging for this window
        setup_global_event_logging(qq_window, "Quick Question")
        
        # Bind Escape to close (also resets flag)
        qq_window.bind("<Escape>", lambda e: on_dialog_close())
        
        # Center the window
        screen_width = qq_window.winfo_screenwidth()
        screen_height = qq_window.winfo_screenheight()
        x = (screen_width - 550) // 2
        y = (screen_height - 320) // 2
        qq_window.geometry(f"550x320+{x}+{y}")
        
        # Title
        title_label = ctk.CTkLabel(
            qq_window,
            text="❓ Quick Question",
            font=("Segoe UI", 16, "bold"),
            text_color="#FF6B00"
        )
        title_label.pack(pady=(15, 10))
        
        # Input textbox
        input_text = ctk.CTkTextbox(
            qq_window,
            width=510,
            height=100,
            font=("Segoe UI", 12),
            fg_color="#2a2a2a",
            text_color="white",
            wrap="word"
        )
        input_text.pack(padx=20, pady=(0, 10))
        input_text.focus()
        
        # Format selection buttons frame
        format_frame = ctk.CTkFrame(qq_window, fg_color="transparent")
        format_frame.pack(pady=(0, 10))
        
        # Track selected format
        selected_format = {"value": "context"}  # Default to "I don't get it"
        all_format_buttons = []
        focused_button = {"current": None}
        
        def update_selection(fmt):
            selected_format["value"] = fmt
            # Update button colors (selected = orange, unselected = gray)
            for btn, btn_fmt in all_format_buttons:
                if fmt == btn_fmt:
                    btn.configure(fg_color="#FF6B00")
                else:
                    btn.configure(fg_color="#4a4a4a")
        
        def on_button_focus(btn, fmt):
            """Handle button focus - add border highlight"""
            focused_button["current"] = btn
            for b, _ in all_format_buttons:
                if b == btn:
                    b.configure(border_width=2, border_color="#FFFFFF")
                else:
                    b.configure(border_width=0)
            submit_btn.configure(border_width=0)
        
        def on_submit_focus():
            """Handle submit button focus"""
            focused_button["current"] = submit_btn
            for b, _ in all_format_buttons:
                b.configure(border_width=0)
            submit_btn.configure(border_width=2, border_color="#FFFFFF")
        
        # "I don't get it" button - DEFAULT option (leftmost)
        btn_context = ctk.CTkButton(
            format_frame,
            text="🤔 I don't get it",
            width=120,
            height=32,
            font=("Segoe UI", 11),
            fg_color="#FF6B00",
            hover_color="#ff8533",
            border_width=0,
            command=lambda: update_selection("context")
        )
        btn_context.pack(side="left", padx=3)
        all_format_buttons.append((btn_context, "context"))
        
        btn_single = ctk.CTkButton(
            format_frame,
            text="One Sentence",
            width=100,
            height=32,
            font=("Segoe UI", 11),
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            border_width=0,
            command=lambda: update_selection("single")
        )
        btn_single.pack(side="left", padx=3)
        all_format_buttons.append((btn_single, "single"))
        
        btn_headers = ctk.CTkButton(
            format_frame,
            text="Headers & Bullets",
            width=120,
            height=32,
            font=("Segoe UI", 11),
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            border_width=0,
            command=lambda: update_selection("headers")
        )
        btn_headers.pack(side="left", padx=3)
        all_format_buttons.append((btn_headers, "headers"))
        
        btn_plain = ctk.CTkButton(
            format_frame,
            text="Plain English",
            width=120,
            height=32,
            font=("Segoe UI", 11),
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            border_width=0,
            command=lambda: update_selection("plain")
        )
        btn_plain.pack(side="left", padx=3)
        all_format_buttons.append((btn_plain, "plain"))
        
        btn_andragogy = ctk.CTkButton(
            format_frame,
            text="Andragogy ¶",
            width=120,
            height=32,
            font=("Segoe UI", 11),
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            border_width=0,
            command=lambda: update_selection("andragogy")
        )
        btn_andragogy.pack(side="left", padx=3)
        all_format_buttons.append((btn_andragogy, "andragogy"))
        
        # Submit button
        def submit_question():
            question = input_text.get("1.0", "end-1c").strip()
            if not question:
                return
            
            qq_window.destroy()
            self._process_quick_question(question, selected_format["value"])
        
        submit_btn = ctk.CTkButton(
            qq_window,
            text="Ask →",
            width=510,
            height=36,
            font=("Segoe UI", 12, "bold"),
            fg_color="#2a7d2e",
            hover_color="#3a9d3e",
            border_width=0,
            command=submit_question
        )
        submit_btn.pack(padx=20, pady=(0, 15))
        
        # Build navigation order: input_text -> format buttons -> submit_btn -> back to input
        nav_order = [input_text] + [btn for btn, _ in all_format_buttons] + [submit_btn]
        nav_names = ["input_text", "btn_context", "btn_single", "btn_headers", "btn_plain", "btn_andragogy", "submit_btn"]
        
        def get_widget_name(widget):
            """Get human-readable name for a widget"""
            for i, w in enumerate(nav_order):
                if widget == w:
                    return nav_names[i]
                if hasattr(w, '_textbox') and widget == w._textbox:
                    return f"{nav_names[i]}._textbox"
                if hasattr(w, '_canvas') and widget == w._canvas:
                    return f"{nav_names[i]}._canvas"
            return str(widget)
        
        def log_interaction(event_type, event=None, extra_info=None):
            """Log comprehensive interaction details"""
            current_focus = qq_window.focus_get()
            focus_name = get_widget_name(current_focus) if current_focus else "None"
            idx = find_focused_index()
            
            log_data = {
                "window": "Quick Question",
                "event_type": event_type,
                "current_focus": focus_name,
                "current_focus_raw": str(current_focus),
                "nav_index": idx,
                "nav_order_len": len(nav_order)
            }
            
            if event:
                log_data["event_widget"] = str(event.widget)
                log_data["event_widget_name"] = get_widget_name(event.widget)
                log_data["event_keysym"] = getattr(event, 'keysym', None)
                log_data["event_state"] = getattr(event, 'state', None)
            
            if extra_info:
                log_data.update(extra_info)
            
            debug_log("QQ_INTERACTION", f"{event_type}", log_data)
        
        def navigate_to(widget):
            """Navigate to a widget and update visual feedback"""
            target_name = get_widget_name(widget)
            log_interaction("navigate_to_start", extra_info={"target": target_name})
            
            widget.focus_set()
            # Clear all borders first
            for b, _ in all_format_buttons:
                b.configure(border_width=0)
            submit_btn.configure(border_width=0)
            
            # Set border on focused button
            if widget == submit_btn:
                submit_btn.configure(border_width=2, border_color="#FFFFFF")
            elif widget in [b for b, _ in all_format_buttons]:
                widget.configure(border_width=2, border_color="#FFFFFF")
            
            log_interaction("navigate_to_complete", extra_info={"target": target_name, "new_focus": get_widget_name(qq_window.focus_get())})
        
        def on_button_enter(event):
            """Handle Enter on a format button - select it and submit"""
            log_interaction("Enter_key", event)
            widget = event.widget
            # Find if it's a format button and select it
            for btn, fmt in all_format_buttons:
                if btn == widget or btn._canvas == event.widget:
                    update_selection(fmt)
                    submit_question()
                    return "break"
            # If it's the submit button
            if widget == submit_btn or getattr(submit_btn, '_canvas', None) == event.widget:
                submit_question()
                return "break"
            return "break"
        
        # Helper to find focused widget index
        def find_focused_index():
            current = qq_window.focus_get()
            current_str = str(current) if current else ""
            for i, widget in enumerate(nav_order):
                if current == widget:
                    return i
                if hasattr(widget, '_textbox') and current == widget._textbox:
                    return i
                if hasattr(widget, '_canvas') and current == widget._canvas:
                    return i
                # Also check for _label internal widget (CTkButton has this too)
                if hasattr(widget, '_text_label') and current == widget._text_label:
                    return i
                # Check if current widget string matches exactly or is a child of this widget
                widget_str = str(widget)
                if current_str and widget_str:
                    # Check if current is exactly the widget or a direct child (e.g., .!ctkbutton2.!label)
                    if current_str == widget_str:
                        return i
                    # Check if it's a child widget - must have widget path followed by a dot
                    if current_str.startswith(widget_str + "."):
                        return i
            return -1
        
        # Window-level Tab navigation
        def on_window_tab(e):
            log_interaction("Tab_pressed_BEFORE", e)
            idx = find_focused_index()
            next_idx = (idx + 1) % len(nav_order)
            log_interaction("Tab_navigation", e, extra_info={
                "from_idx": idx, 
                "to_idx": next_idx, 
                "from_name": nav_names[idx] if idx >= 0 else "unknown",
                "to_name": nav_names[next_idx]
            })
            navigate_to(nav_order[next_idx]) if next_idx > 0 else input_text.focus_set()
            if next_idx == 0:
                for b, _ in all_format_buttons:
                    b.configure(border_width=0)
                submit_btn.configure(border_width=0)
            log_interaction("Tab_pressed_AFTER", e, extra_info={"final_focus": get_widget_name(qq_window.focus_get())})
            return "break"
        
        def on_window_shift_tab(e):
            log_interaction("ShiftTab_pressed_BEFORE", e)
            idx = find_focused_index()
            prev_idx = (idx - 1) % len(nav_order)
            log_interaction("ShiftTab_navigation", e, extra_info={
                "from_idx": idx,
                "to_idx": prev_idx,
                "from_name": nav_names[idx] if idx >= 0 else "unknown",
                "to_name": nav_names[prev_idx]
            })
            if prev_idx == 0 or idx == 0:
                input_text.focus_set()
                for b, _ in all_format_buttons:
                    b.configure(border_width=0)
                submit_btn.configure(border_width=0)
            else:
                navigate_to(nav_order[prev_idx])
            log_interaction("ShiftTab_pressed_AFTER", e, extra_info={"final_focus": get_widget_name(qq_window.focus_get())})
            return "break"
        
        # Log all focus events on buttons
        def on_focus_in(event, btn_name):
            log_interaction("FocusIn", event, extra_info={"button_name": btn_name})
        
        def on_focus_out(event, btn_name):
            log_interaction("FocusOut", event, extra_info={"button_name": btn_name})
        
        def on_click(event, btn_name):
            log_interaction("Click", event, extra_info={"button_name": btn_name})
        
        qq_window.bind("<Tab>", on_window_tab)
        qq_window.bind("<Shift-Tab>", on_window_shift_tab)
        
        # Bind Tab to each button directly AND their internal canvas widgets
        for i, (btn, _) in enumerate(all_format_buttons):
            btn_name = nav_names[i + 1]  # +1 because input_text is index 0
            btn.bind("<Tab>", on_window_tab)
            btn.bind("<Shift-Tab>", on_window_shift_tab)
            btn.bind("<FocusIn>", lambda e, n=btn_name: on_focus_in(e, n))
            btn.bind("<FocusOut>", lambda e, n=btn_name: on_focus_out(e, n))
            btn.bind("<Button-1>", lambda e, n=btn_name: on_click(e, n), add="+")
            # Also bind to internal canvas which actually receives focus
            try:
                if hasattr(btn, '_canvas'):
                    btn._canvas.bind("<Tab>", on_window_tab)
                    btn._canvas.bind("<Shift-Tab>", on_window_shift_tab)
                    btn._canvas.bind("<FocusIn>", lambda e, n=btn_name: on_focus_in(e, f"{n}._canvas"))
                    btn._canvas.bind("<FocusOut>", lambda e, n=btn_name: on_focus_out(e, f"{n}._canvas"))
                    btn._canvas.bind("<Button-1>", lambda e, n=btn_name: on_click(e, f"{n}._canvas"), add="+")
            except Exception as ex:
                debug_log("QQ_BIND_ERROR", f"Failed to bind canvas for {btn_name}", {"error": str(ex)})
            # Also bind to internal text label which can receive focus
            try:
                if hasattr(btn, '_text_label') and btn._text_label:
                    btn._text_label.bind("<Tab>", on_window_tab)
                    btn._text_label.bind("<Shift-Tab>", on_window_shift_tab)
                    btn._text_label.bind("<FocusIn>", lambda e, n=btn_name: on_focus_in(e, f"{n}._text_label"))
                    btn._text_label.bind("<FocusOut>", lambda e, n=btn_name: on_focus_out(e, f"{n}._text_label"))
            except Exception as ex:
                debug_log("QQ_BIND_ERROR", f"Failed to bind text_label for {btn_name}", {"error": str(ex)})
        
        submit_btn.bind("<Tab>", on_window_tab)
        submit_btn.bind("<Shift-Tab>", on_window_shift_tab)
        submit_btn.bind("<FocusIn>", lambda e: on_focus_in(e, "submit_btn"))
        submit_btn.bind("<FocusOut>", lambda e: on_focus_out(e, "submit_btn"))
        submit_btn.bind("<Button-1>", lambda e: on_click(e, "submit_btn"), add="+")
        try:
            if hasattr(submit_btn, '_canvas'):
                submit_btn._canvas.bind("<Tab>", on_window_tab)
                submit_btn._canvas.bind("<Shift-Tab>", on_window_shift_tab)
                submit_btn._canvas.bind("<FocusIn>", lambda e: on_focus_in(e, "submit_btn._canvas"))
                submit_btn._canvas.bind("<FocusOut>", lambda e: on_focus_out(e, "submit_btn._canvas"))
                submit_btn._canvas.bind("<Button-1>", lambda e: on_click(e, "submit_btn._canvas"), add="+")
        except Exception as ex:
            debug_log("QQ_BIND_ERROR", f"Failed to bind submit canvas", {"error": str(ex)})
        try:
            if hasattr(submit_btn, '_text_label') and submit_btn._text_label:
                submit_btn._text_label.bind("<Tab>", on_window_tab)
                submit_btn._text_label.bind("<Shift-Tab>", on_window_shift_tab)
                submit_btn._text_label.bind("<FocusIn>", lambda e: on_focus_in(e, "submit_btn._text_label"))
                submit_btn._text_label.bind("<FocusOut>", lambda e: on_focus_out(e, "submit_btn._text_label"))
        except Exception as ex:
            debug_log("QQ_BIND_ERROR", f"Failed to bind submit text_label", {"error": str(ex)})
        
        # Define on_return BEFORE binding it
        def on_return(e):
            if e.state & 0x1:  # Shift key - allow newline
                return
            submit_question()
            return "break"
        
        # Bind to internal textbox to prevent indent AND handle Return key
        try:
            internal = input_text._textbox
            internal.bind("<Tab>", on_window_tab)
            internal.bind("<Shift-Tab>", on_window_shift_tab)
            internal.bind("<FocusIn>", lambda e: on_focus_in(e, "input_text._textbox"))
            internal.bind("<FocusOut>", lambda e: on_focus_out(e, "input_text._textbox"))
            # Also bind Return key to internal textbox (focus is actually here)
            internal.bind("<Return>", on_return)
        except AttributeError:
            pass
        
        # Log button info at creation
        debug_log("QQ_SETUP", "Navigation order created", {
            "nav_names": nav_names,
            "nav_order_widgets": [str(w) for w in nav_order],
            "canvas_widgets": [str(getattr(btn, '_canvas', None)) for btn, _ in all_format_buttons] + [str(getattr(submit_btn, '_canvas', None))]
        })
        
        for btn, fmt in all_format_buttons:
            btn.bind("<Return>", on_button_enter)
            btn.bind("<space>", lambda e, f=fmt: (update_selection(f), "break")[-1])
        
        submit_btn.bind("<Return>", on_button_enter)
        
        # Also bind Enter to the wrapper textbox
        input_text.bind("<Return>", on_return)
        
        debug_log("QUICK_QUESTION", "Dialog created")
        
        # Log all visible elements after dialog is ready
        qq_window.after(100, lambda: log_visible_elements(qq_window, "Quick Question"))
    
    def _show_shorten_dialog(self):
        """Show shorten dialog with three shortening levels"""
        # Check if dialog window already exists
        if hasattr(self, '_shorten_dialog_window') and self._shorten_dialog_window:
            try:
                if self._shorten_dialog_window.winfo_exists():
                    debug_log("SHORTEN", "Debounced - dialog window already exists")
                    self._shorten_dialog_window.lift()
                    self._shorten_dialog_window.focus_force()
                    return
            except:
                pass
        
        debug_log("SHORTEN", "Opening shorten dialog")
        
        # Create dialog window
        shorten_win = ctk.CTkToplevel(self.window)
        self._shorten_dialog_window = shorten_win
        shorten_win.title("✂️ Shorten Text")
        shorten_win.geometry("600x400")
        shorten_win.configure(fg_color="#1a1a1a")
        shorten_win.transient(self.window)
        shorten_win.lift()
        shorten_win.attributes("-topmost", True)
        
        # Clear reference when window is closed
        def on_dialog_close():
            self._shorten_dialog_window = None
            shorten_win.destroy()
        
        shorten_win.protocol("WM_DELETE_WINDOW", on_dialog_close)
        shorten_win.bind("<Escape>", lambda e: on_dialog_close())
        
        # Center the window
        screen_width = shorten_win.winfo_screenwidth()
        screen_height = shorten_win.winfo_screenheight()
        x = (screen_width - 600) // 2
        y = (screen_height - 400) // 2
        shorten_win.geometry(f"600x400+{x}+{y}")
        
        # Title
        title_label = ctk.CTkLabel(
            shorten_win,
            text="✂️ Shorten Text",
            font=("Segoe UI", 16, "bold"),
            text_color="#FF6B00"
        )
        title_label.pack(pady=(15, 5))
        
        # Instruction
        instruction_label = ctk.CTkLabel(
            shorten_win,
            text="Paste or type text to shorten while preserving key information",
            font=("Segoe UI", 10),
            text_color="#888888"
        )
        instruction_label.pack(pady=(0, 10))
        
        # Input textbox
        input_text = ctk.CTkTextbox(
            shorten_win,
            width=560,
            height=200,
            font=("Segoe UI", 11),
            fg_color="#2a2a2a",
            text_color="white",
            wrap="word"
        )
        input_text.pack(padx=20, pady=(0, 15))
        input_text.focus()
        
        # Try to paste clipboard content if it looks like text
        try:
            clipboard = pyperclip.paste()
            if clipboard and len(clipboard) > 20 and len(clipboard) < 50000:
                input_text.insert("1.0", clipboard)
                input_text.mark_set("insert", "1.0")
        except:
            pass
        
        # Button frame
        btn_frame = ctk.CTkFrame(shorten_win, fg_color="transparent")
        btn_frame.pack(pady=(0, 15))
        
        def do_shorten(level: str):
            text = input_text.get("1.0", "end-1c").strip()
            if not text:
                return
            on_dialog_close()
            self._process_shorten_request(text, level)
        
        # Shorten button (25% reduction)
        btn_shorten = ctk.CTkButton(
            btn_frame,
            text="✂️ Shorten\n(~25% shorter)",
            width=150,
            height=50,
            font=("Segoe UI", 11),
            fg_color="#2a7d2e",
            hover_color="#3a9d3e",
            command=lambda: do_shorten("shorten")
        )
        btn_shorten.pack(side="left", padx=8)
        
        # More button (50% reduction)
        btn_more = ctk.CTkButton(
            btn_frame,
            text="📉 More\n(~50% shorter)",
            width=150,
            height=50,
            font=("Segoe UI", 11),
            fg_color="#7d6a2a",
            hover_color="#9d8a3a",
            command=lambda: do_shorten("more")
        )
        btn_more.pack(side="left", padx=8)
        
        # MORE!!! button (75% reduction)
        btn_more_extreme = ctk.CTkButton(
            btn_frame,
            text="⚡ MORE!!!\n(~75% shorter)",
            width=150,
            height=50,
            font=("Segoe UI", 11, "bold"),
            fg_color="#7d2a2a",
            hover_color="#9d3a3a",
            command=lambda: do_shorten("more!!!")
        )
        btn_more_extreme.pack(side="left", padx=8)
        
        # Tip label
        tip_label = ctk.CTkLabel(
            shorten_win,
            text="💡 Tip: Select text in any app, then use Ctrl+Alt+S to open this dialog",
            font=("Segoe UI", 9),
            text_color="#666666"
        )
        tip_label.pack(pady=(5, 10))
        
        debug_log("SHORTEN", "Dialog created")
    
    def _process_shorten_request(self, text: str, level: str):
        """Process shorten request with selected level"""
        debug_log("SHORTEN", f"Processing shorten request with level: {level}", {
            "text_length": len(text),
            "word_count": len(text.split())
        })
        
        # Show the main window with loading state
        self._show_window_minimal()
        
        level_names = {
            "shorten": "Shorten (~25%)",
            "more": "More (~50%)",
            "more!!!": "MORE!!! (~75%)"
        }
        
        self.word_label.configure(text="✂️ Shortening...")
        self.status_label.configure(text=f"Applying {level_names.get(level, level)}...")
        
        def do_shorten_api():
            result, token_info = shorten_text(text, level)
            self.window.after(0, lambda: self._show_shorten_result(text, result, token_info, level))
        
        thread = threading.Thread(target=do_shorten_api, daemon=True)
        thread.start()
    
    def _show_shorten_result(self, original: str, shortened: str, token_info: dict, level: str):
        """Display shortened text result"""
        debug_log("SHORTEN_RESULT", f"Displaying {level} result", {
            "original_length": len(original),
            "shortened_length": len(shortened),
            "tokens": token_info
        })
        
        level_emojis = {
            "shorten": "✂️",
            "more": "📉",
            "more!!!": "⚡"
        }
        level_names = {
            "shorten": "Shortened (~25%)",
            "more": "More (~50%)",
            "more!!!": "MORE!!! (~75%)"
        }
        
        # Create result window
        result_win = ctk.CTkToplevel(self.window)
        result_win.title(f"{level_emojis.get(level, '✂️')} {level_names.get(level, 'Shortened')} Result")
        result_win.geometry("750x650")
        result_win.configure(fg_color="#1a1a1a")
        result_win.transient(self.window)
        result_win.lift()
        
        # Bind Escape to close
        result_win.bind("<Escape>", lambda e: result_win.destroy())
        
        # Center the window
        screen_width = result_win.winfo_screenwidth()
        screen_height = result_win.winfo_screenheight()
        x = (screen_width - 750) // 2
        y = (screen_height - 650) // 2
        result_win.geometry(f"750x650+{x}+{y}")
        
        # Header with stats
        header_frame = ctk.CTkFrame(result_win, fg_color="transparent")
        header_frame.pack(fill="x", padx=20, pady=(15, 5))
        
        title_label = ctk.CTkLabel(
            header_frame,
            text=f"{level_emojis.get(level, '✂️')} {level_names.get(level, 'Shortened')}",
            font=("Segoe UI", 16, "bold"),
            text_color="#FF6B00"
        )
        title_label.pack(side="left")
        
        # Stats
        if token_info:
            orig_words = token_info.get('original_words', len(original.split()))
            short_words = token_info.get('shortened_words', len(shortened.split()))
            reduction = token_info.get('reduction_percent', round((1 - short_words / orig_words) * 100, 1) if orig_words > 0 else 0)
            
            stats_label = ctk.CTkLabel(
                header_frame,
                text=f"{orig_words} → {short_words} words ({reduction}% shorter)",
                font=("Segoe UI", 11),
                text_color="#4CAF50"
            )
            stats_label.pack(side="right")
        
        # Result text area
        result_text = ctk.CTkTextbox(
            result_win,
            width=710,
            height=450,
            font=("Segoe UI", 12),
            fg_color="#2a2a2a",
            text_color="white",
            wrap="word"
        )
        result_text.pack(padx=20, pady=10)
        result_text.insert("1.0", shortened)
        
        # Apply markdown formatting if available
        if hasattr(self, '_apply_markdown_formatting'):
            self._apply_markdown_formatting(result_text)
        
        # Store for actions
        self._shorten_original = original
        self._shorten_result = shortened
        
        # Button frame
        btn_frame = ctk.CTkFrame(result_win, fg_color="transparent")
        btn_frame.pack(pady=10)
        
        def copy_result():
            pyperclip.copy(shortened)
            copy_btn.configure(text="✓ Copied!")
            result_win.after(1500, lambda: copy_btn.configure(text="📋 Copy"))
        
        def show_comparison():
            """Show side-by-side comparison"""
            comp_win = ctk.CTkToplevel(result_win)
            comp_win.title("📊 Comparison: Original vs Shortened")
            comp_win.geometry("1000x600")
            comp_win.configure(fg_color="#1a1a1a")
            comp_win.transient(result_win)
            comp_win.lift()
            comp_win.bind("<Escape>", lambda e: comp_win.destroy())
            
            # Center
            cx = (result_win.winfo_screenwidth() - 1000) // 2
            cy = (result_win.winfo_screenheight() - 600) // 2
            comp_win.geometry(f"1000x600+{cx}+{cy}")
            
            # Side by side frames
            main_frame = ctk.CTkFrame(comp_win, fg_color="transparent")
            main_frame.pack(fill="both", expand=True, padx=15, pady=15)
            
            # Original side
            orig_frame = ctk.CTkFrame(main_frame, fg_color="#252525")
            orig_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
            
            orig_label = ctk.CTkLabel(
                orig_frame,
                text=f"📄 Original ({len(original.split())} words)",
                font=("Segoe UI", 12, "bold"),
                text_color="#888888"
            )
            orig_label.pack(pady=(10, 5))
            
            orig_text = ctk.CTkTextbox(
                orig_frame,
                font=("Segoe UI", 11),
                fg_color="#2a2a2a",
                text_color="white",
                wrap="word"
            )
            orig_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
            orig_text.insert("1.0", original)
            
            # Shortened side
            short_frame = ctk.CTkFrame(main_frame, fg_color="#252525")
            short_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))
            
            short_label = ctk.CTkLabel(
                short_frame,
                text=f"✂️ Shortened ({len(shortened.split())} words)",
                font=("Segoe UI", 12, "bold"),
                text_color="#4CAF50"
            )
            short_label.pack(pady=(10, 5))
            
            short_text = ctk.CTkTextbox(
                short_frame,
                font=("Segoe UI", 11),
                fg_color="#2a2a2a",
                text_color="white",
                wrap="word"
            )
            short_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
            short_text.insert("1.0", shortened)
        
        def close_result():
            result_win.destroy()
            self.hide_window()
        
        def shorten_again():
            """Open shorten dialog with the result pre-filled"""
            result_win.destroy()
            self.hide_window()
            self.window.after(100, lambda: self._show_shorten_dialog_with_text(shortened))
        
        copy_btn = ctk.CTkButton(
            btn_frame,
            text="📋 Copy",
            width=100,
            height=32,
            font=("Segoe UI", 11),
            fg_color="#3a3a3a",
            hover_color="#4a4a4a",
            command=copy_result
        )
        copy_btn.pack(side="left", padx=5)
        
        compare_btn = ctk.CTkButton(
            btn_frame,
            text="📊 Compare",
            width=100,
            height=32,
            font=("Segoe UI", 11),
            fg_color="#3a3a3a",
            hover_color="#4a4a4a",
            command=show_comparison
        )
        compare_btn.pack(side="left", padx=5)
        
        again_btn = ctk.CTkButton(
            btn_frame,
            text="✂️ Shorten More",
            width=120,
            height=32,
            font=("Segoe UI", 11),
            fg_color="#2a7d2e",
            hover_color="#3a9d3e",
            command=shorten_again
        )
        again_btn.pack(side="left", padx=5)
        
        close_btn = ctk.CTkButton(
            btn_frame,
            text="Close",
            width=80,
            height=32,
            font=("Segoe UI", 11),
            fg_color="#5a5a5a",
            hover_color="#6a6a6a",
            command=close_result
        )
        close_btn.pack(side="left", padx=5)
        
        # Token info at bottom
        if token_info:
            cost = estimate_cost(token_info.get('input_tokens', 0), token_info.get('output_tokens', 0), token_info.get('model', 'gpt-4o-mini'))
            token_label = ctk.CTkLabel(
                result_win,
                text=f"Tokens: {token_info.get('total_tokens', 0)} ~{format_cost(cost)}",
                font=("Segoe UI", 9),
                text_color="#666666"
            )
            token_label.pack(pady=(0, 10))
    
    def _show_shorten_dialog_with_text(self, prefill_text: str):
        """Show shorten dialog with pre-filled text"""
        # Similar to _show_shorten_dialog but with text pre-filled
        if hasattr(self, '_shorten_dialog_window') and self._shorten_dialog_window:
            try:
                if self._shorten_dialog_window.winfo_exists():
                    self._shorten_dialog_window.destroy()
            except:
                pass
        
        debug_log("SHORTEN", "Opening shorten dialog with prefilled text")
        
        # Create dialog window
        shorten_win = ctk.CTkToplevel(self.window)
        self._shorten_dialog_window = shorten_win
        shorten_win.title("✂️ Shorten Text")
        shorten_win.geometry("600x400")
        shorten_win.configure(fg_color="#1a1a1a")
        shorten_win.transient(self.window)
        shorten_win.lift()
        shorten_win.attributes("-topmost", True)
        
        def on_dialog_close():
            self._shorten_dialog_window = None
            shorten_win.destroy()
        
        shorten_win.protocol("WM_DELETE_WINDOW", on_dialog_close)
        shorten_win.bind("<Escape>", lambda e: on_dialog_close())
        
        screen_width = shorten_win.winfo_screenwidth()
        screen_height = shorten_win.winfo_screenheight()
        x = (screen_width - 600) // 2
        y = (screen_height - 400) // 2
        shorten_win.geometry(f"600x400+{x}+{y}")
        
        title_label = ctk.CTkLabel(
            shorten_win,
            text="✂️ Shorten Again",
            font=("Segoe UI", 16, "bold"),
            text_color="#FF6B00"
        )
        title_label.pack(pady=(15, 5))
        
        instruction_label = ctk.CTkLabel(
            shorten_win,
            text="Continue shortening the result",
            font=("Segoe UI", 10),
            text_color="#888888"
        )
        instruction_label.pack(pady=(0, 10))
        
        input_text = ctk.CTkTextbox(
            shorten_win,
            width=560,
            height=200,
            font=("Segoe UI", 11),
            fg_color="#2a2a2a",
            text_color="white",
            wrap="word"
        )
        input_text.pack(padx=20, pady=(0, 15))
        input_text.insert("1.0", prefill_text)
        input_text.focus()
        
        btn_frame = ctk.CTkFrame(shorten_win, fg_color="transparent")
        btn_frame.pack(pady=(0, 15))
        
        def do_shorten(level: str):
            text = input_text.get("1.0", "end-1c").strip()
            if not text:
                return
            on_dialog_close()
            self._process_shorten_request(text, level)
        
        btn_shorten = ctk.CTkButton(
            btn_frame,
            text="✂️ Shorten\n(~25% shorter)",
            width=150,
            height=50,
            font=("Segoe UI", 11),
            fg_color="#2a7d2e",
            hover_color="#3a9d3e",
            command=lambda: do_shorten("shorten")
        )
        btn_shorten.pack(side="left", padx=8)
        
        btn_more = ctk.CTkButton(
            btn_frame,
            text="📉 More\n(~50% shorter)",
            width=150,
            height=50,
            font=("Segoe UI", 11),
            fg_color="#7d6a2a",
            hover_color="#9d8a3a",
            command=lambda: do_shorten("more")
        )
        btn_more.pack(side="left", padx=8)
        
        btn_more_extreme = ctk.CTkButton(
            btn_frame,
            text="⚡ MORE!!!\n(~75% shorter)",
            width=150,
            height=50,
            font=("Segoe UI", 11, "bold"),
            fg_color="#7d2a2a",
            hover_color="#9d3a3a",
            command=lambda: do_shorten("more!!!")
        )
        btn_more_extreme.pack(side="left", padx=8)
    
    # ==================== CHAT WINDOW ====================
    
    def _show_chat_window(self):
        """Show the ChatGPT-style conversation window"""
        # Check if window already exists
        if hasattr(self, '_chat_window') and self._chat_window:
            try:
                if self._chat_window.winfo_exists():
                    self._chat_window.lift()
                    self._chat_window.focus_force()
                    return
            except:
                pass
        
        debug_log("CHAT", "Opening chat window")
        
        # Initialize chat state
        self._chat_messages = []  # Full message history: [{"role": "user/assistant", "content": "...", "timestamp": "..."}]
        self._chat_context_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_context.txt")
        self._chat_history_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_history.json")
        self._chat_history_expanded = False
        self._chat_quick_modifiers = {}  # Track which modifiers are active
        
        # Load existing history if any
        self._load_chat_history()
        
        # Create main chat window
        self._chat_window = ctk.CTkToplevel(self.window)
        self._chat_window.title("💬 Chat")
        self._chat_window.geometry("800x700")
        self._chat_window.configure(fg_color="#1a1a1a")
        self._chat_window.attributes("-topmost", True)
        
        # Center the window
        screen_width = self._chat_window.winfo_screenwidth()
        screen_height = self._chat_window.winfo_screenheight()
        x = (screen_width - 800) // 2
        y = (screen_height - 700) // 2
        self._chat_window.geometry(f"800x700+{x}+{y}")
        
        def on_close():
            self._save_chat_history()
            self._chat_window.destroy()
            self._chat_window = None
        
        self._chat_window.protocol("WM_DELETE_WINDOW", on_close)
        self._chat_window.bind("<Escape>", lambda e: on_close())
        
        # Title bar with context indicator
        title_frame = ctk.CTkFrame(self._chat_window, fg_color="#2a2a2a", height=50)
        title_frame.pack(fill="x", padx=10, pady=(10, 5))
        title_frame.pack_propagate(False)
        
        title_label = ctk.CTkLabel(
            title_frame,
            text="💬 Chat",
            font=("Segoe UI", 16, "bold"),
            text_color="#FF6B00"
        )
        title_label.pack(side="left", padx=15, pady=10)
        
        # Context file indicator/button
        self._chat_context_btn = ctk.CTkButton(
            title_frame,
            text="📋 Context",
            width=100,
            height=28,
            font=("Segoe UI", 10),
            fg_color="#3a5a3a" if os.path.exists(self._chat_context_file) else "#4a4a4a",
            hover_color="#4a6a4a",
            command=self._edit_chat_context
        )
        self._chat_context_btn.pack(side="right", padx=10, pady=10)
        
        # New chat button
        new_chat_btn = ctk.CTkButton(
            title_frame,
            text="🔄 New",
            width=70,
            height=28,
            font=("Segoe UI", 10),
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            command=self._new_chat
        )
        new_chat_btn.pack(side="right", padx=5, pady=10)
        
        # History toggle (collapsible for older messages)
        self._history_frame = ctk.CTkFrame(self._chat_window, fg_color="#252525")
        self._history_frame.pack(fill="x", padx=10, pady=(0, 5))
        
        self._history_toggle_btn = ctk.CTkButton(
            self._history_frame,
            text=f"📜 History ({max(0, len(self._chat_messages) - 20)} older messages) ▶",
            width=300,
            height=28,
            font=("Segoe UI", 10),
            fg_color="transparent",
            hover_color="#3a3a3a",
            text_color="#888888",
            command=self._toggle_chat_history
        )
        self._history_toggle_btn.pack(side="left", padx=10, pady=5)
        
        # Collapsible history content (hidden by default)
        self._history_content = ctk.CTkFrame(self._history_frame, fg_color="#1a1a1a")
        # Will be packed/unpacked when toggled
        
        self._history_text = ctk.CTkTextbox(
            self._history_content,
            height=150,
            font=("Segoe UI", 10),
            fg_color="#1a1a1a",
            text_color="#888888",
            wrap="word"
        )
        self._history_text.pack(fill="x", padx=10, pady=5)
        
        # Main message display area (last 20 messages)
        self._chat_display_frame = ctk.CTkScrollableFrame(
            self._chat_window,
            fg_color="#1a1a1a",
            scrollbar_button_color="#3a3a3a",
            scrollbar_button_hover_color="#4a4a4a"
        )
        self._chat_display_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Render existing messages
        self._render_chat_messages()
        
        # Quick modifier buttons frame
        modifier_frame = ctk.CTkFrame(self._chat_window, fg_color="#252525")
        modifier_frame.pack(fill="x", padx=10, pady=(5, 0))
        
        modifier_label = ctk.CTkLabel(
            modifier_frame,
            text="Quick:",
            font=("Segoe UI", 10),
            text_color="#666666"
        )
        modifier_label.pack(side="left", padx=(10, 5), pady=8)
        
        # Quick modifier buttons
        self._chat_mod_buttons = {}
        
        # Headings + bullet points
        btn_bullets = ctk.CTkButton(
            modifier_frame,
            text="📋 Headings + Bullets",
            width=140,
            height=26,
            font=("Segoe UI", 10),
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            command=lambda: self._toggle_chat_modifier("bullets")
        )
        btn_bullets.pack(side="left", padx=3, pady=8)
        self._chat_mod_buttons["bullets"] = btn_bullets
        
        # Concise
        btn_concise = ctk.CTkButton(
            modifier_frame,
            text="⚡ Concise",
            width=80,
            height=26,
            font=("Segoe UI", 10),
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            command=lambda: self._toggle_chat_modifier("concise")
        )
        btn_concise.pack(side="left", padx=3, pady=8)
        self._chat_mod_buttons["concise"] = btn_concise
        
        # Code focus
        btn_code = ctk.CTkButton(
            modifier_frame,
            text="💻 Code",
            width=70,
            height=26,
            font=("Segoe UI", 10),
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            command=lambda: self._toggle_chat_modifier("code")
        )
        btn_code.pack(side="left", padx=3, pady=8)
        self._chat_mod_buttons["code"] = btn_code
        
        # Input area
        input_frame = ctk.CTkFrame(self._chat_window, fg_color="#2a2a2a")
        input_frame.pack(fill="x", padx=10, pady=10)
        
        self._chat_input = ctk.CTkTextbox(
            input_frame,
            height=80,
            font=("Segoe UI", 11),
            fg_color="#1a1a1a",
            text_color="white",
            wrap="word"
        )
        self._chat_input.pack(fill="x", padx=10, pady=(10, 5), side="top")
        self._chat_input.focus()
        
        # Send button row
        send_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        send_frame.pack(fill="x", padx=10, pady=(0, 10))
        
        send_btn = ctk.CTkButton(
            send_frame,
            text="Send →",
            width=100,
            height=32,
            font=("Segoe UI", 11, "bold"),
            fg_color="#2a7d2e",
            hover_color="#3a9d3e",
            command=self._send_chat_message
        )
        send_btn.pack(side="right", padx=5)
        
        # Token counter
        self._chat_token_label = ctk.CTkLabel(
            send_frame,
            text="",
            font=("Segoe UI", 9),
            text_color="#666666"
        )
        self._chat_token_label.pack(side="left", padx=10)
        
        # Bind Enter to send (Shift+Enter for newline)
        def on_enter(e):
            if not (e.state & 0x1):  # Not Shift
                self._send_chat_message()
                return "break"
        self._chat_input.bind("<Return>", on_enter)
        
        # Bind Ctrl+Enter to send regardless
        self._chat_input.bind("<Control-Return>", lambda e: (self._send_chat_message(), "break")[-1])
        
        debug_log("CHAT", "Chat window created")
    
    def _load_chat_history(self):
        """Load chat history from file"""
        try:
            if os.path.exists(self._chat_history_file):
                with open(self._chat_history_file, 'r', encoding='utf-8') as f:
                    self._chat_messages = json.load(f)
                debug_log("CHAT", f"Loaded {len(self._chat_messages)} messages from history")
        except Exception as e:
            debug_log("CHAT_ERROR", f"Failed to load chat history: {e}")
            self._chat_messages = []
    
    def _save_chat_history(self):
        """Save chat history to file"""
        try:
            with open(self._chat_history_file, 'w', encoding='utf-8') as f:
                json.dump(self._chat_messages, f, indent=2, ensure_ascii=False)
            debug_log("CHAT", f"Saved {len(self._chat_messages)} messages to history")
        except Exception as e:
            debug_log("CHAT_ERROR", f"Failed to save chat history: {e}")
    
    def _get_chat_context(self) -> str:
        """Load the context file content"""
        try:
            if os.path.exists(self._chat_context_file):
                with open(self._chat_context_file, 'r', encoding='utf-8') as f:
                    return f.read().strip()
        except Exception as e:
            debug_log("CHAT_ERROR", f"Failed to load context: {e}")
        return ""
    
    def _edit_chat_context(self):
        """Open editor for chat context file"""
        debug_log("CHAT", "Opening context editor")
        
        # Create context editor window
        ctx_win = ctk.CTkToplevel(self._chat_window)
        ctx_win.title("📋 Edit Chat Context")
        ctx_win.geometry("600x500")
        ctx_win.configure(fg_color="#1a1a1a")
        ctx_win.transient(self._chat_window)
        ctx_win.lift()
        ctx_win.grab_set()
        
        # Center
        x = (ctx_win.winfo_screenwidth() - 600) // 2
        y = (ctx_win.winfo_screenheight() - 500) // 2
        ctx_win.geometry(f"600x500+{x}+{y}")
        
        # Title
        title = ctk.CTkLabel(
            ctx_win,
            text="📋 Chat Context",
            font=("Segoe UI", 14, "bold"),
            text_color="#FF6B00"
        )
        title.pack(pady=(15, 5))
        
        # Instructions
        instructions = ctk.CTkLabel(
            ctx_win,
            text="This context is sent with EVERY message.\nUse it for rules, preferences, or persistent information.",
            font=("Segoe UI", 10),
            text_color="#888888"
        )
        instructions.pack(pady=(0, 10))
        
        # Text area
        ctx_text = ctk.CTkTextbox(
            ctx_win,
            font=("Segoe UI", 11),
            fg_color="#2a2a2a",
            text_color="white",
            wrap="word"
        )
        ctx_text.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Load existing context
        existing = self._get_chat_context()
        if existing:
            ctx_text.insert("1.0", existing)
        else:
            # Default template
            ctx_text.insert("1.0", """# Chat Context
# Everything here is sent with every message.

## My Preferences
- 

## Rules
- 

## Important Info
- 
""")
        
        # Buttons
        btn_frame = ctk.CTkFrame(ctx_win, fg_color="transparent")
        btn_frame.pack(pady=15)
        
        def save_context():
            content = ctx_text.get("1.0", "end-1c")
            try:
                with open(self._chat_context_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                # Update button color to indicate context exists
                self._chat_context_btn.configure(fg_color="#3a5a3a")
                ctx_win.destroy()
                debug_log("CHAT", "Context saved")
            except Exception as e:
                debug_log("CHAT_ERROR", f"Failed to save context: {e}")
        
        save_btn = ctk.CTkButton(
            btn_frame,
            text="💾 Save",
            width=100,
            height=32,
            fg_color="#2a7d2e",
            hover_color="#3a9d3e",
            command=save_context
        )
        save_btn.pack(side="left", padx=10)
        
        cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=100,
            height=32,
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            command=ctx_win.destroy
        )
        cancel_btn.pack(side="left", padx=10)
        
        ctx_win.bind("<Escape>", lambda e: ctx_win.destroy())
    
    def _new_chat(self):
        """Start a new chat (clear messages but keep context)"""
        if self._chat_messages:
            # Save current chat to archive
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"chat_archive_{timestamp}.json")
            try:
                with open(archive_file, 'w', encoding='utf-8') as f:
                    json.dump(self._chat_messages, f, indent=2, ensure_ascii=False)
                debug_log("CHAT", f"Archived {len(self._chat_messages)} messages to {archive_file}")
            except Exception as e:
                debug_log("CHAT_ERROR", f"Failed to archive: {e}")
        
        self._chat_messages = []
        self._save_chat_history()
        self._render_chat_messages()
        self._update_history_toggle()
        debug_log("CHAT", "Started new chat")
    
    def _toggle_chat_history(self):
        """Toggle the expanded history view"""
        self._chat_history_expanded = not self._chat_history_expanded
        
        if self._chat_history_expanded:
            # Show older messages
            self._history_content.pack(fill="x", padx=5, pady=5)
            self._history_toggle_btn.configure(text=f"📜 History ({max(0, len(self._chat_messages) - 20)} older messages) ▼")
            self._render_history_messages()
        else:
            self._history_content.pack_forget()
            self._history_toggle_btn.configure(text=f"📜 History ({max(0, len(self._chat_messages) - 20)} older messages) ▶")
    
    def _update_history_toggle(self):
        """Update the history toggle button text"""
        older_count = max(0, len(self._chat_messages) - 20)
        arrow = "▼" if self._chat_history_expanded else "▶"
        self._history_toggle_btn.configure(text=f"📜 History ({older_count} older messages) {arrow}")
    
    def _render_history_messages(self):
        """Render older messages (before the last 20) in the history panel"""
        self._history_text.configure(state="normal")
        self._history_text.delete("1.0", "end")
        
        older_messages = self._chat_messages[:-20] if len(self._chat_messages) > 20 else []
        
        for msg in older_messages:
            role = "You" if msg["role"] == "user" else "GPT"
            timestamp = msg.get("timestamp", "")
            content = msg["content"][:200] + "..." if len(msg["content"]) > 200 else msg["content"]
            self._history_text.insert("end", f"[{timestamp}] {role}: {content}\n\n")
        
        if not older_messages:
            self._history_text.insert("end", "(No older messages)")
        
        self._history_text.configure(state="disabled")
    
    def _render_chat_messages(self):
        """Render the last 20 messages in the main display"""
        # Clear existing message widgets
        for widget in self._chat_display_frame.winfo_children():
            widget.destroy()
        
        # Get last 20 messages
        recent_messages = self._chat_messages[-20:] if len(self._chat_messages) > 20 else self._chat_messages
        
        if not recent_messages:
            # Show placeholder
            placeholder = ctk.CTkLabel(
                self._chat_display_frame,
                text="💬 Start a conversation!\n\nYour messages and GPT responses will appear here.\nUse the Context button to set persistent rules.",
                font=("Segoe UI", 12),
                text_color="#666666"
            )
            placeholder.pack(expand=True, pady=50)
            return
        
        for msg in recent_messages:
            self._add_message_bubble(msg)
    
    def _add_message_bubble(self, msg: dict):
        """Add a message bubble to the display"""
        is_user = msg["role"] == "user"
        
        # Message container
        msg_frame = ctk.CTkFrame(
            self._chat_display_frame,
            fg_color="#2d5a27" if is_user else "#2a2a2a",
            corner_radius=10
        )
        msg_frame.pack(
            fill="x",
            padx=(60 if is_user else 10, 10 if is_user else 60),
            pady=5,
            anchor="e" if is_user else "w"
        )
        
        # Header with role and timestamp
        header_frame = ctk.CTkFrame(msg_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=10, pady=(8, 2))
        
        role_label = ctk.CTkLabel(
            header_frame,
            text="You" if is_user else "GPT",
            font=("Segoe UI", 10, "bold"),
            text_color="#90EE90" if is_user else "#FF6B00"
        )
        role_label.pack(side="left")
        
        timestamp = msg.get("timestamp", "")
        if timestamp:
            time_label = ctk.CTkLabel(
                header_frame,
                text=timestamp,
                font=("Segoe UI", 9),
                text_color="#666666"
            )
            time_label.pack(side="right")
        
        # Message content
        content_label = ctk.CTkLabel(
            msg_frame,
            text=msg["content"],
            font=("Segoe UI", 11),
            text_color="white",
            wraplength=650,
            justify="left",
            anchor="w"
        )
        content_label.pack(fill="x", padx=10, pady=(2, 10))
        
        # Copy button for assistant messages
        if not is_user:
            copy_btn = ctk.CTkButton(
                msg_frame,
                text="📋",
                width=30,
                height=20,
                font=("Segoe UI", 9),
                fg_color="transparent",
                hover_color="#3a3a3a",
                command=lambda c=msg["content"]: pyperclip.copy(c)
            )
            copy_btn.pack(anchor="e", padx=10, pady=(0, 5))
    
    def _toggle_chat_modifier(self, modifier: str):
        """Toggle a quick modifier on/off"""
        if modifier in self._chat_quick_modifiers and self._chat_quick_modifiers[modifier]:
            # Turn off
            self._chat_quick_modifiers[modifier] = False
            self._chat_mod_buttons[modifier].configure(fg_color="#4a4a4a")
        else:
            # Turn on
            self._chat_quick_modifiers[modifier] = True
            self._chat_mod_buttons[modifier].configure(fg_color="#FF6B00")
    
    def _get_modifier_instructions(self) -> str:
        """Get instructions based on active modifiers"""
        instructions = []
        
        if self._chat_quick_modifiers.get("bullets"):
            instructions.append("FORMAT YOUR RESPONSE WITH: Headings and bullet points. Each bullet point should be <10 words. Use clear section headers.")
        
        if self._chat_quick_modifiers.get("concise"):
            instructions.append("BE CONCISE: Keep your response brief and to the point. No unnecessary elaboration.")
        
        if self._chat_quick_modifiers.get("code"):
            instructions.append("FOCUS ON CODE: Prioritize code examples and technical implementation details.")
        
        return "\n".join(instructions)
    
    def _send_chat_message(self):
        """Send the current message to GPT"""
        message = self._chat_input.get("1.0", "end-1c").strip()
        if not message:
            return
        
        debug_log("CHAT", f"Sending message", {"length": len(message)})
        
        # Clear input
        self._chat_input.delete("1.0", "end")
        
        # Add user message to history
        timestamp = datetime.now().strftime("%H:%M")
        user_msg = {
            "role": "user",
            "content": message,
            "timestamp": timestamp
        }
        self._chat_messages.append(user_msg)
        
        # Update display
        self._render_chat_messages()
        self._update_history_toggle()
        
        # Scroll to bottom
        self._chat_display_frame._parent_canvas.yview_moveto(1.0)
        
        # Show thinking indicator
        thinking_frame = ctk.CTkFrame(
            self._chat_display_frame,
            fg_color="#2a2a2a",
            corner_radius=10
        )
        thinking_frame.pack(fill="x", padx=(10, 60), pady=5, anchor="w")
        thinking_label = ctk.CTkLabel(
            thinking_frame,
            text="⏳ Thinking...",
            font=("Segoe UI", 11),
            text_color="#888888"
        )
        thinking_label.pack(padx=15, pady=10)
        
        # Call API in background
        def call_api():
            try:
                response = self._call_chat_api(message)
                self._chat_window.after(0, lambda: self._handle_chat_response(response, thinking_frame))
            except Exception as e:
                self._chat_window.after(0, lambda: self._handle_chat_error(str(e), thinking_frame))
        
        thread = threading.Thread(target=call_api, daemon=True)
        thread.start()
    
    def _call_chat_api(self, user_message: str) -> dict:
        """Call the OpenAI API with chat history and context"""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or api_key == "your_openai_api_key_here":
            return {"error": "API key not configured"}
        
        # Build messages array
        messages = []
        
        # System message with context
        context = self._get_chat_context()
        modifier_instructions = self._get_modifier_instructions()
        
        system_content = "You are a helpful assistant."
        if context:
            system_content += f"\n\n## USER'S PERSISTENT CONTEXT:\n{context}"
        if modifier_instructions:
            system_content += f"\n\n## RESPONSE FORMAT INSTRUCTIONS:\n{modifier_instructions}"
        
        messages.append({"role": "system", "content": system_content})
        
        # Add conversation history (for API context, not just display)
        for msg in self._chat_messages[:-1]:  # Exclude the just-added user message
            messages.append({"role": msg["role"], "content": msg["content"]})
        
        # Add current message
        messages.append({"role": "user", "content": user_message})
        
        debug_log("CHAT_API", f"Calling API with {len(messages)} messages")
        
        try:
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=messages,
                max_tokens=2000,
                temperature=0.7
            )
            
            answer = response.choices[0].message.content
            token_info = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }
            
            debug_log("CHAT_API", "Response received", token_info)
            
            return {"answer": answer, "tokens": token_info}
            
        except Exception as e:
            debug_log("CHAT_API_ERROR", f"API call failed: {e}")
            return {"error": str(e)}
    
    def _handle_chat_response(self, response: dict, thinking_frame):
        """Handle successful API response"""
        # Remove thinking indicator
        thinking_frame.destroy()
        
        if "error" in response:
            self._handle_chat_error(response["error"], None)
            return
        
        # Add assistant message to history
        timestamp = datetime.now().strftime("%H:%M")
        assistant_msg = {
            "role": "assistant",
            "content": response["answer"],
            "timestamp": timestamp
        }
        self._chat_messages.append(assistant_msg)
        
        # Save history
        self._save_chat_history()
        
        # Update display
        self._render_chat_messages()
        self._update_history_toggle()
        
        # Scroll to bottom
        self._chat_display_frame._parent_canvas.yview_moveto(1.0)
        
        # Update token counter
        if "tokens" in response:
            cost = estimate_cost(response["tokens"]["input_tokens"], response["tokens"]["output_tokens"], DEFAULT_MODEL)
            self._chat_token_label.configure(
                text=f"Last: {response['tokens']['total_tokens']} tokens ~{format_cost(cost)}"
            )
    
    def _handle_chat_error(self, error: str, thinking_frame):
        """Handle API error"""
        if thinking_frame:
            thinking_frame.destroy()
        
        # Show error in chat
        error_frame = ctk.CTkFrame(
            self._chat_display_frame,
            fg_color="#5a2a2a",
            corner_radius=10
        )
        error_frame.pack(fill="x", padx=(10, 60), pady=5, anchor="w")
        error_label = ctk.CTkLabel(
            error_frame,
            text=f"❌ Error: {error}",
            font=("Segoe UI", 11),
            text_color="#ff6666"
        )
        error_label.pack(padx=15, pady=10)
        
        debug_log("CHAT_ERROR", f"Displayed error: {error}")
    
    # ==================== END CHAT WINDOW ====================
    
    def _process_quick_question(self, question: str, format_type: str):
        """Process quick question with selected format"""
        debug_log("QUICK_QUESTION", f"Processing question with format: {format_type}")
        
        self.word_label.configure(text="Thinking...")
        self.status_label.configure(text=f"Asking: {question[:50]}...")
        
        def get_answer():
            answer = ask_openai(question, response_format=format_type)
            self.window.after(0, lambda: self._serial_read_quick_answer(question, answer, format_type))
        
        thread = threading.Thread(target=get_answer, daemon=True)
        thread.start()
    
    def _serial_read_quick_answer(self, question: str, answer: str, format_type: str):
        """Serial read the quick answer, then show full textbox on completion"""
        debug_log("QUICK_QUESTION", "Starting serial read of answer")
        
        # Store the answer info for showing textbox after playback
        self.pending_quick_answer = {
            "question": question,
            "answer": answer,
            "format_type": format_type
        }
        
        # Set up the text for serial reading
        self.current_text = answer
        self.words = answer.split()
        self.current_word_index = 0
        
        # Reset simplified explanations state (fresh context for quick answer)
        self.simplified_explanations = []
        self.current_explanation_index = 0
        self.simplify_source_text = ""
        
        # Reset text view mode to serial reader
        self.full_text_view_mode = False
        
        # Reset any playback state
        self.stop_playback = True
        self.is_playing = False
        self.is_paused = False
        
        # Show window and ensure it's properly reset
        self.window.deiconify()
        self.window.focus_force()
        self.is_visible = True
        
        # Reset UI for reading - ensure word display is shown and summary is hidden
        self.summary_text.pack_forget()
        
        # Handle both base and enhanced UI (word_canvas vs word_label)
        if hasattr(self, 'word_canvas') and self.word_canvas:
            # Enhanced mode - use canvas
            try:
                self.word_label.pack_forget()
            except:
                pass
            if hasattr(self, 'word_frame') and self.word_frame:
                self.word_frame.pack(fill="both", expand=True, pady=10)
            self.word_canvas.pack(fill="both", expand=True)
            if hasattr(self, 'draw_word_on_canvas'):
                self.draw_word_on_canvas("Ready", -1)
        else:
            # Base mode - use label
            self.word_label.pack(expand=True)
            self.word_label.configure(text="Ready")
        
        self.status_label.configure(text="Press SPACE to read answer | ESC to skip to full text")
        
        # Reset progress bar
        if self.progress_bar:
            self.progress_bar.set(0)
        if self.progress_label:
            self.progress_label.configure(text=f"0/{len(self.words)}")
        
        # Bind Escape to skip directly to textbox
        def skip_to_textbox(e):
            self.stop_playback = True
            self.is_playing = False
            self.pending_quick_answer = None
            self._show_quick_answer(question, answer, format_type)
            return "break"
        
        self.window.bind("<Escape>", skip_to_textbox)
        
        # Override space behavior temporarily for quick answer mode
        self._quick_answer_space_handler = lambda e: self._start_quick_answer_playback(question, answer, format_type)
        self.window.bind("<space>", self._quick_answer_space_handler)
    
    def _start_quick_answer_playback(self, question: str, answer: str, format_type: str):
        """Start playback for quick answer"""
        debug_log("QUICK_QUESTION", "Starting quick answer playback")
        
        # Unbind the temporary space handler
        self.window.unbind("<space>")
        self.window.bind("<space>", self.on_space_pressed)
        
        # Set up for playback completion callback
        self._on_quick_answer_complete = lambda: self._show_quick_answer(question, answer, format_type)
        
        # Start normal playback
        self.is_playing = True
        self.is_paused = False
        self.stop_playback = False
        self.current_word_index = 0
        self.formatted_words = self.parse_text_with_formatting(answer)
        
        self.status_label.configure(text="Reading answer... Press SPACE to pause")
        
        # Start playback in separate thread with completion callback
        def playback_with_callback():
            self._quick_answer_playback_loop()
        
        self.play_thread = threading.Thread(target=playback_with_callback, daemon=True)
        self.play_thread.start()
        
        return "break"
    
    def _quick_answer_playback_loop(self):
        """Playback loop for quick answer - shows textbox on completion"""
        debug_log("QUICK_ANSWER_PLAYBACK", "Quick answer playback started")
        
        base_delay = 60.0 / self.wpm
        
        while self.current_word_index < len(self.formatted_words) and not self.stop_playback:
            word, is_line_break, is_headline = self.formatted_words[self.current_word_index]
            
            # Display the word using the same method as regular playback
            self.window.after(0, lambda w=word: self.display_word(w))
            
            # Update progress bar
            self.window.after(0, self.update_progress_bar)
            
            # Force UI update to ensure word displays immediately
            self.window.after(0, lambda: self.window.update_idletasks())
            
            # Calculate delay
            word_multiplier = self.get_word_length_multiplier(word)
            total_delay = base_delay * word_multiplier
            if is_line_break:
                total_delay += self.pause_delay / 1000
            
            self.current_word_index += 1
            time.sleep(total_delay)
        
        self.is_playing = False
        
        # On completion, show the full answer textbox
        if not self.stop_playback and self.current_word_index >= len(self.formatted_words):
            debug_log("QUICK_ANSWER_PLAYBACK", "Playback complete, showing full textbox")
            self.window.after(0, lambda: self.status_label.configure(text="Press SPACE/ENTER to see full answer"))
            
            # Wait for space/enter to show textbox
            def show_textbox_on_key(e):
                self.window.unbind("<space>")
                self.window.unbind("<Return>")
                self.window.bind("<space>", self.on_space_pressed)
                if hasattr(self, '_on_quick_answer_complete') and self._on_quick_answer_complete:
                    self._on_quick_answer_complete()
                    self._on_quick_answer_complete = None
                return "break"
            
            self.window.after(0, lambda: self.window.bind("<space>", show_textbox_on_key))
            self.window.after(0, lambda: self.window.bind("<Return>", show_textbox_on_key))
    
    def _show_quick_answer(self, question: str, answer: str, format_type: str):
        """Show quick question answer in a modal"""
        debug_log("QUICK_QUESTION", "Showing answer")
        
        # Restore main window Escape binding
        self.window.bind("<Escape>", self.on_escape_pressed)
        
        # Clear pending quick answer state
        self.pending_quick_answer = None
        
        # Create answer window
        answer_win = ctk.CTkToplevel(self.window)
        answer_win.title(f"Answer ({format_type})")
        answer_win.geometry("600x500")
        answer_win.configure(fg_color="#1a1a1a")
        answer_win.transient(self.window)
        answer_win.attributes("-topmost", True)
        answer_win.lift()
        
        # Bind Escape to close
        answer_win.bind("<Escape>", lambda e: answer_win.destroy())
        
        # Center the window
        screen_width = answer_win.winfo_screenwidth()
        screen_height = answer_win.winfo_screenheight()
        x = (screen_width - 600) // 2
        y = (screen_height - 500) // 2
        answer_win.geometry(f"600x500+{x}+{y}")
        
        # Question header
        q_label = ctk.CTkLabel(
            answer_win,
            text=f"❓ {question[:70]}{'...' if len(question) > 70 else ''}",
            font=("Segoe UI", 12),
            text_color="#888888",
            wraplength=560
        )
        q_label.pack(pady=(15, 5), padx=20)
        
        # Answer text
        answer_text = ctk.CTkTextbox(
            answer_win,
            width=560,
            height=360,
            font=("Segoe UI", 12),
            fg_color="#2a2a2a",
            text_color="white",
            wrap="word"
        )
        answer_text.pack(padx=20, pady=10)
        answer_text.insert("1.0", answer)
        
        # Button frame
        btn_frame = ctk.CTkFrame(answer_win, fg_color="transparent")
        btn_frame.pack(pady=(0, 15))
        
        def copy_answer():
            pyperclip.copy(answer)
            self.status_label.configure(text="Answer copied to clipboard")
        
        copy_btn = ctk.CTkButton(
            btn_frame,
            text="📋 Copy",
            width=100,
            height=32,
            font=("Segoe UI", 11),
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            command=copy_answer
        )
        copy_btn.pack(side="left", padx=5)
        
        def show_followup():
            answer_win.destroy()
            self._show_followup_question_dialog(question, answer, format_type)
        
        followup_btn = ctk.CTkButton(
            btn_frame,
            text="❓",
            width=40,
            height=32,
            font=("Segoe UI", 14),
            fg_color="#FF6B00",
            hover_color="#ff8533",
            command=show_followup
        )
        followup_btn.pack(side="left", padx=5)
        
        close_btn = ctk.CTkButton(
            btn_frame,
            text="✓ Done",
            width=100,
            height=32,
            font=("Segoe UI", 11),
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            command=answer_win.destroy
        )
        close_btn.pack(side="left", padx=5)
        
        # Button focus visuals
        for btn in [copy_btn, followup_btn, close_btn]:
            btn.bind("<FocusIn>", lambda e, b=btn: b.configure(border_width=2, border_color="#FFFFFF"))
            btn.bind("<FocusOut>", lambda e, b=btn: b.configure(border_width=0))
            btn.bind("<Return>", lambda e, b=btn: b.invoke())
        
        # Window-level Tab navigation
        focusables = [answer_text, copy_btn, followup_btn, close_btn]
        
        def find_focused_index():
            current = answer_win.focus_get()
            for i, widget in enumerate(focusables):
                if current == widget:
                    return i
                if hasattr(widget, '_textbox') and current == widget._textbox:
                    return i
                if hasattr(widget, '_canvas') and current == widget._canvas:
                    return i
                try:
                    if current and str(current).startswith(str(widget)):
                        return i
                except:
                    pass
            return -1
        
        def on_window_tab(e):
            current_idx = find_focused_index()
            next_idx = (current_idx + 1) % len(focusables)
            focusables[next_idx].focus_set()
            return "break"
        
        def on_window_shift_tab(e):
            current_idx = find_focused_index()
            prev_idx = (current_idx - 1) % len(focusables)
            focusables[prev_idx].focus_set()
            return "break"
        
        answer_win.bind("<Tab>", on_window_tab)
        answer_win.bind("<Shift-Tab>", on_window_shift_tab)
        
        # Bind Tab to buttons directly
        for btn in [copy_btn, followup_btn, close_btn]:
            btn.bind("<Tab>", on_window_tab)
            btn.bind("<Shift-Tab>", on_window_shift_tab)
        
        # Bind to internal textbox to prevent indent
        try:
            internal = answer_text._textbox
            internal.bind("<Tab>", on_window_tab)
            internal.bind("<Shift-Tab>", on_window_shift_tab)
        except AttributeError:
            pass
        
        # Bind Enter to close (but not Shift+Enter)
        def on_return(e):
            if e.state & 0x1:  # Shift key
                return
            answer_win.destroy()
            return "break"
        answer_win.bind("<Return>", on_return)
        
        # Update main window status
        self.word_label.configure(text="✓ Done")
        self.status_label.configure(text=f"Quick answer delivered ({format_type})")
    
    def _show_followup_question_dialog(self, original_question: str, previous_answer: str, format_type: str):
        """Show dialog for follow-up question with context"""
        debug_log("QUICK_QUESTION", "Opening follow-up question dialog")
        
        # Create dialog window
        followup_win = ctk.CTkToplevel(self.window)
        followup_win.title("Follow-up Question")
        followup_win.geometry("500x200")
        followup_win.configure(fg_color="#1a1a1a")
        followup_win.transient(self.window)
        followup_win.attributes("-topmost", True)
        followup_win.lift()
        
        # Bind Escape to close
        followup_win.bind("<Escape>", lambda e: followup_win.destroy())
        
        # Center the window
        screen_width = followup_win.winfo_screenwidth()
        screen_height = followup_win.winfo_screenheight()
        x = (screen_width - 500) // 2
        y = (screen_height - 200) // 2
        followup_win.geometry(f"500x200+{x}+{y}")
        
        # Context reminder
        context_label = ctk.CTkLabel(
            followup_win,
            text=f"Following up on: {original_question[:50]}...",
            font=("Segoe UI", 10),
            text_color="#888888"
        )
        context_label.pack(pady=(15, 5))
        
        # Input textbox
        input_text = ctk.CTkTextbox(
            followup_win,
            width=460,
            height=80,
            font=("Segoe UI", 12),
            fg_color="#2a2a2a",
            text_color="white",
            wrap="word"
        )
        input_text.pack(padx=20, pady=(0, 10))
        input_text.focus()
        
        def submit_followup():
            followup_question = input_text.get("1.0", "end-1c").strip()
            if not followup_question:
                return
            
            followup_win.destroy()
            self._process_followup_question(original_question, previous_answer, followup_question, format_type)
        
        submit_btn = ctk.CTkButton(
            followup_win,
            text="Ask Follow-up →",
            width=460,
            height=36,
            font=("Segoe UI", 12, "bold"),
            fg_color="#FF6B00",
            hover_color="#ff8533",
            border_width=0,
            command=submit_followup
        )
        submit_btn.pack(padx=20, pady=(0, 15))
        
        # Button focus visuals
        submit_btn.bind("<FocusIn>", lambda e: submit_btn.configure(border_width=2, border_color="#FFFFFF"))
        submit_btn.bind("<FocusOut>", lambda e: submit_btn.configure(border_width=0))
        submit_btn.bind("<Return>", lambda e: (submit_followup(), "break")[-1])
        
        # Window-level Tab navigation
        focusables = [input_text, submit_btn]
        
        def find_focused_index():
            current = followup_win.focus_get()
            for i, widget in enumerate(focusables):
                if current == widget:
                    return i
                if hasattr(widget, '_textbox') and current == widget._textbox:
                    return i
                if hasattr(widget, '_canvas') and current == widget._canvas:
                    return i
                try:
                    if current and str(current).startswith(str(widget)):
                        return i
                except:
                    pass
            return -1
        
        def on_window_tab(e):
            current_idx = find_focused_index()
            next_idx = (current_idx + 1) % len(focusables)
            focusables[next_idx].focus_set()
            return "break"
        
        def on_window_shift_tab(e):
            current_idx = find_focused_index()
            prev_idx = (current_idx - 1) % len(focusables)
            focusables[prev_idx].focus_set()
            return "break"
        
        followup_win.bind("<Tab>", on_window_tab)
        followup_win.bind("<Shift-Tab>", on_window_shift_tab)
        
        # Bind Tab to button directly
        submit_btn.bind("<Tab>", on_window_tab)
        submit_btn.bind("<Shift-Tab>", on_window_shift_tab)
        
        # Bind to internal textbox to prevent indent
        try:
            internal = input_text._textbox
            internal.bind("<Tab>", on_window_tab)
            internal.bind("<Shift-Tab>", on_window_shift_tab)
        except AttributeError:
            pass
        
        # Bind Enter (but not Shift+Enter)
        def on_return(e):
            if e.state & 0x1:  # Shift key - allow newline
                return
            submit_followup()
            return "break"
        input_text.bind("<Return>", on_return)
    
    def _process_followup_question(self, original_question: str, previous_answer: str, followup_question: str, format_type: str):
        """Process follow-up question with context from previous answer"""
        debug_log("QUICK_QUESTION", f"Processing follow-up question: {followup_question[:50]}")
        
        self.word_label.configure(text="Thinking...")
        self.status_label.configure(text=f"Follow-up: {followup_question[:40]}...")
        
        def get_answer():
            # Build context-aware prompt
            context_prompt = f"""Previous question: {original_question}

Previous answer: {previous_answer}

Follow-up question: {followup_question}"""
            
            answer = ask_openai(context_prompt, response_format=format_type)
            self.window.after(0, lambda: self._show_quick_answer(followup_question, answer, format_type))
        
        thread = threading.Thread(target=get_answer, daemon=True)
        thread.start()
    
    def on_quiz_start(self, event=None):
        """Handle Ctrl+Alt+Q - start quiz mode"""
        debug_log("KEYPRESS_CTRL_ALT_Q", "Ctrl+Alt+Q pressed - starting quiz")
        
        self._show_quiz_file_selector()
        
        return "break"
    
    def _show_quiz_file_selector(self):
        """Show window to select which notes file to quiz from"""
        import glob
        
        debug_log("QUIZ", "Opening quiz file selector")
        
        # Find all FullNotes*.txt files
        full_notes_files = sorted(glob.glob("FullNotes*.txt"))
        
        if not full_notes_files:
            debug_log("QUIZ", "No FullNotes files found")
            self.status_label.configure(text="No notes files found. Save some notes first!")
            return
        
        # Create selector window
        selector_win = ctk.CTkToplevel(self.window)
        selector_win.title("Quiz Mode")
        selector_win.geometry("400x500")
        selector_win.configure(fg_color="#1a1a1a")
        selector_win.attributes("-topmost", True)
        
        # Center the window
        screen_width = selector_win.winfo_screenwidth()
        screen_height = selector_win.winfo_screenheight()
        x = (screen_width - 400) // 2
        y = (screen_height - 500) // 2
        selector_win.geometry(f"400x500+{x}+{y}")
        
        # Title
        title = ctk.CTkLabel(
            selector_win,
            text="📝 Quiz Mode",
            font=("Segoe UI", 20, "bold"),
            text_color="#FF6B00"
        )
        title.pack(pady=(20, 5))
        
        subtitle = ctk.CTkLabel(
            selector_win,
            text="Select a notes file to quiz from:",
            font=("Segoe UI", 12),
            text_color="#888888"
        )
        subtitle.pack(pady=(0, 15))
        
        # Scrollable frame for file buttons
        scroll_frame = ctk.CTkScrollableFrame(
            selector_win,
            width=350,
            height=350,
            fg_color="#2a2a2a"
        )
        scroll_frame.pack(padx=20, pady=10, fill="both", expand=True)
        
        # Track buttons for Tab navigation
        file_buttons = []
        
        # Create button for each file
        for notes_file in full_notes_files:
            # Get note count
            try:
                with open(notes_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    import re
                    note_count = len(re.findall(r'\[NOTE_\d+\]', content))
            except:
                note_count = 0
            
            btn = ctk.CTkButton(
                scroll_frame,
                text=f"📄 {notes_file} ({note_count} notes)",
                width=320,
                height=40,
                font=("Segoe UI", 12),
                fg_color="#3a3a3a",
                hover_color="#4a4a4a",
                command=lambda f=notes_file, w=selector_win: self._prompt_review_questions(f, w)
            )
            btn.pack(pady=5)
            # Button focus visuals
            btn.bind("<FocusIn>", lambda e, b=btn: b.configure(border_width=2, border_color="#FFFFFF"))
            btn.bind("<FocusOut>", lambda e, b=btn: b.configure(border_width=0))
            file_buttons.append((btn, notes_file))
        
        # Tab navigation between file buttons
        def on_tab(event):
            current = selector_win.focus_get()
            btn_list = [b[0] for b in file_buttons]
            try:
                idx = btn_list.index(current)
                next_idx = (idx + 1) % len(btn_list)
            except ValueError:
                next_idx = 0
            btn_list[next_idx].focus_set()
            return "break"
        
        def on_shift_tab(event):
            current = selector_win.focus_get()
            btn_list = [b[0] for b in file_buttons]
            try:
                idx = btn_list.index(current)
                prev_idx = (idx - 1) % len(btn_list)
            except ValueError:
                prev_idx = 0
            btn_list[prev_idx].focus_set()
            return "break"
        
        def on_enter(event):
            current = selector_win.focus_get()
            for btn, notes_file in file_buttons:
                if btn == current:
                    self._prompt_review_questions(notes_file, selector_win)
                    return "break"
            return "break"
        
        # Bind keys
        selector_win.bind("<Tab>", on_tab)
        selector_win.bind("<Shift-Tab>", on_shift_tab)
        selector_win.bind("<Return>", on_enter)
        selector_win.bind("<Escape>", lambda e: selector_win.destroy())
        
        # Focus first button
        if file_buttons:
            file_buttons[0][0].focus_set()
        else:
            selector_win.focus_set()
    
    def _prompt_review_questions(self, notes_file, parent_window):
        """Prompt user whether to include review questions"""
        parent_window.destroy()
        
        # Check if Review.txt exists
        if not os.path.exists("Review.txt"):
            # No review file, proceed directly
            self._start_quiz(notes_file, include_review=False)
            return
        
        debug_log("QUIZ", "Prompting for review questions")
        
        # Create prompt window
        prompt_win = ctk.CTkToplevel(self.window)
        prompt_win.title("Review Questions")
        prompt_win.geometry("350x180")
        prompt_win.configure(fg_color="#1a1a1a")
        prompt_win.attributes("-topmost", True)
        
        # Center the window
        screen_width = prompt_win.winfo_screenwidth()
        screen_height = prompt_win.winfo_screenheight()
        x = (screen_width - 350) // 2
        y = (screen_height - 180) // 2
        prompt_win.geometry(f"350x180+{x}+{y}")
        
        # Title
        title = ctk.CTkLabel(
            prompt_win,
            text="Include review questions?",
            font=("Segoe UI", 16, "bold"),
            text_color="#FF6B00"
        )
        title.pack(pady=(25, 5))
        
        subtitle = ctk.CTkLabel(
            prompt_win,
            text="Questions you got wrong previously",
            font=("Segoe UI", 11),
            text_color="#888888"
        )
        subtitle.pack(pady=(0, 20))
        
        # Buttons frame
        btn_frame = ctk.CTkFrame(prompt_win, fg_color="#1a1a1a")
        btn_frame.pack(pady=10)
        
        yes_btn = ctk.CTkButton(
            btn_frame,
            text="Yes (Y)",
            width=120,
            height=40,
            font=("Segoe UI", 13),
            fg_color="#4A90D9",
            hover_color="#5BA0E9",
            command=lambda: self._prompt_question_count(notes_file, True, prompt_win)
        )
        yes_btn.pack(side="left", padx=10)
        
        no_btn = ctk.CTkButton(
            btn_frame,
            text="No (N)",
            width=120,
            height=40,
            font=("Segoe UI", 13),
            fg_color="#555555",
            hover_color="#666666",
            command=lambda: self._prompt_question_count(notes_file, False, prompt_win)
        )
        no_btn.pack(side="left", padx=10)
        
        # Button focus visuals
        buttons = [yes_btn, no_btn]
        for btn in buttons:
            btn.bind("<FocusIn>", lambda e, b=btn: b.configure(border_width=2, border_color="#FFFFFF"))
            btn.bind("<FocusOut>", lambda e, b=btn: b.configure(border_width=0))
            btn.bind("<Return>", lambda e, b=btn: b.invoke())
        
        # Tab navigation
        def cycle_buttons():
            current = prompt_win.focus_get()
            if current == yes_btn:
                no_btn.focus_set()
            else:
                yes_btn.focus_set()
        
        # Keyboard bindings
        prompt_win.bind("y", lambda e: self._prompt_question_count(notes_file, True, prompt_win))
        prompt_win.bind("Y", lambda e: self._prompt_question_count(notes_file, True, prompt_win))
        prompt_win.bind("n", lambda e: self._prompt_question_count(notes_file, False, prompt_win))
        prompt_win.bind("N", lambda e: self._prompt_question_count(notes_file, False, prompt_win))
        prompt_win.bind("<Escape>", lambda e: prompt_win.destroy())
        prompt_win.bind("<Tab>", lambda e: (cycle_buttons(), "break")[-1])
        prompt_win.bind("<Shift-Tab>", lambda e: (cycle_buttons(), "break")[-1])
        
        yes_btn.focus_set()
    
    def _prompt_question_count(self, notes_file, include_review, parent_window):
        """Prompt user for number of quiz questions to generate"""
        parent_window.destroy()
        
        debug_log("QUIZ", "Prompting for question count")
        
        # Create prompt window
        count_win = ctk.CTkToplevel(self.window)
        count_win.title("Question Count")
        count_win.geometry("350x200")
        count_win.configure(fg_color="#1a1a1a")
        count_win.attributes("-topmost", True)
        
        # Center the window
        screen_width = count_win.winfo_screenwidth()
        screen_height = count_win.winfo_screenheight()
        x = (screen_width - 350) // 2
        y = (screen_height - 200) // 2
        count_win.geometry(f"350x200+{x}+{y}")
        
        # Title
        title = ctk.CTkLabel(
            count_win,
            text="How many questions?",
            font=("Segoe UI", 16, "bold"),
            text_color="#FF6B00"
        )
        title.pack(pady=(25, 5))
        
        subtitle = ctk.CTkLabel(
            count_win,
            text="Enter a number (1-50)",
            font=("Segoe UI", 11),
            text_color="#888888"
        )
        subtitle.pack(pady=(0, 15))
        
        # Number entry
        entry_frame = ctk.CTkFrame(count_win, fg_color="#1a1a1a")
        entry_frame.pack(pady=10)
        
        count_entry = ctk.CTkEntry(
            entry_frame,
            width=100,
            height=40,
            font=("Segoe UI", 16),
            fg_color="#2a2a2a",
            border_color="#FF6B00",
            justify="center"
        )
        count_entry.pack(side="left", padx=10)
        count_entry.insert(0, "10")  # Default value
        count_entry.select_range(0, "end")
        
        def submit_count():
            try:
                num = int(count_entry.get().strip())
                if 1 <= num <= 50:
                    count_win.destroy()
                    self._start_quiz_with_review(notes_file, include_review, num)
                else:
                    count_entry.configure(border_color="#FF0000")
            except ValueError:
                count_entry.configure(border_color="#FF0000")
        
        start_btn = ctk.CTkButton(
            entry_frame,
            text="Start",
            width=80,
            height=40,
            font=("Segoe UI", 13),
            fg_color="#4A90D9",
            hover_color="#5BA0E9",
            command=submit_count
        )
        start_btn.pack(side="left", padx=10)
        
        # Button focus visuals
        start_btn.bind("<FocusIn>", lambda e: start_btn.configure(border_width=2, border_color="#FFFFFF"))
        start_btn.bind("<FocusOut>", lambda e: start_btn.configure(border_width=0))
        start_btn.bind("<Return>", lambda e: submit_count())
        
        # Keyboard bindings
        count_entry.bind("<Return>", lambda e: submit_count())
        count_win.bind("<Escape>", lambda e: count_win.destroy())
        
        # Tab between entry and button with visual feedback
        def on_tab(event):
            current = count_win.focus_get()
            if current == count_entry:
                start_btn.configure(border_width=2, border_color="#FFFFFF")
                start_btn.focus_set()
            else:
                start_btn.configure(border_width=0)
                count_entry.focus_set()
            return "break"
        
        count_win.bind("<Tab>", on_tab)
        count_win.bind("<Shift-Tab>", on_tab)
        count_entry.focus_set()
    
    def _cycle_focus(self, window):
        """Cycle focus between buttons"""
        current = window.focus_get()
        children = [w for w in window.winfo_children() if isinstance(w, ctk.CTkFrame)]
        if children:
            buttons = [w for w in children[0].winfo_children() if isinstance(w, ctk.CTkButton)]
            if buttons:
                try:
                    idx = buttons.index(current)
                    next_idx = (idx + 1) % len(buttons)
                    buttons[next_idx].focus_set()
                except:
                    buttons[0].focus_set()
    
    def _start_quiz_with_review(self, notes_file, include_review, question_count):
        """Start quiz with review preference and question count"""
        self._start_quiz(notes_file, include_review, question_count)
    
    def _start_quiz(self, notes_file, include_review=False, question_count=10):
        """Start the quiz by generating questions from notes"""
        debug_log("QUIZ", f"Starting quiz from {notes_file}", {"include_review": include_review, "question_count": question_count})
        
        self.include_review = include_review
        self.quiz_question_count = question_count
        self.quiz_score = {"correct": 0, "incorrect": 0}
        self.current_quiz_index = 0
        
        # Show loading indicator
        loading_win = ctk.CTkToplevel(self.window)
        loading_win.title("Generating Quiz...")
        loading_win.geometry("300x100")
        loading_win.configure(fg_color="#1a1a1a")
        loading_win.attributes("-topmost", True)
        
        screen_width = loading_win.winfo_screenwidth()
        screen_height = loading_win.winfo_screenheight()
        x = (screen_width - 300) // 2
        y = (screen_height - 100) // 2
        loading_win.geometry(f"300x100+{x}+{y}")
        
        loading_label = ctk.CTkLabel(
            loading_win,
            text="🧠 Generating quiz questions...",
            font=("Segoe UI", 14),
            text_color="#FF6B00"
        )
        loading_label.pack(expand=True)
        
        # Generate questions in background thread
        def generate_and_start():
            try:
                # Read notes content
                with open(notes_file, 'r', encoding='utf-8') as f:
                    notes_content = f.read()
                
                # Add review questions if requested
                review_content = ""
                if include_review and os.path.exists("Review.txt"):
                    with open("Review.txt", 'r', encoding='utf-8') as f:
                        review_content = f.read()
                
                # Read covered topics log
                covered_topics = ""
                if os.path.exists(self.quiz_topics_log_file):
                    with open(self.quiz_topics_log_file, 'r', encoding='utf-8') as f:
                        covered_topics = f.read()
                
                # Generate questions
                questions = self._generate_quiz_questions(notes_content, review_content, covered_topics, question_count)
                
                # Update UI on main thread
                self.window.after(0, lambda: self._quiz_ready(questions, loading_win))
                
            except Exception as e:
                debug_log("QUIZ_ERROR", f"Failed to generate quiz: {str(e)}")
                self.window.after(0, lambda: self._quiz_error(str(e), loading_win))
        
        threading.Thread(target=generate_and_start, daemon=True).start()
    
    def _get_covered_topics(self):
        """Read the covered topics log file"""
        if os.path.exists(self.quiz_topics_log_file):
            try:
                with open(self.quiz_topics_log_file, 'r', encoding='utf-8') as f:
                    return f.read()
            except:
                pass
        return ""
    
    def _log_understood_topic(self, topic):
        """Log a topic that the user demonstrated understanding of"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"[{timestamp}] UNDERSTOOD: {topic}\n"
        
        try:
            with open(self.quiz_topics_log_file, 'a', encoding='utf-8') as f:
                f.write(entry)
            debug_log("QUIZ_TOPICS", f"Logged understood topic: {topic}")
        except Exception as e:
            debug_log("QUIZ_TOPICS_ERROR", f"Failed to log topic: {str(e)}")
    
    def _generate_quiz_questions(self, notes_content, review_content="", covered_topics="", question_count=10):
        """Call OpenAI to generate quiz questions from notes"""
        debug_log("QUIZ", f"Generating {question_count} quiz questions via OpenAI")
        
        combined_content = notes_content
        if review_content:
            combined_content += "\n\n--- REVIEW QUESTIONS (prioritize these topics) ---\n" + review_content
        
        # Build topics avoidance instruction
        topics_instruction = ""
        if covered_topics.strip():
            topics_instruction = f"""
PREVIOUSLY COVERED TOPICS (avoid quizzing heavily on these unless reviewing):
{covered_topics[-3000:]}

Focus on topics NOT yet covered or only lightly touched. Prioritize fresh material."""
        
        # Calculate question type distribution based on count
        mc_count = max(1, int(question_count * 0.45))  # ~45% multiple choice
        ms_count = max(1, int(question_count * 0.25))  # ~25% multiple select  
        sa_count = max(1, question_count - mc_count - ms_count)  # Rest short answer
        
        prompt = f"""Based on the following notes, generate a quiz with exactly {question_count} questions.
        
IMPORTANT: Generate a mix of question types:
- {mc_count} multiple choice questions (single answer)
- {ms_count} multiple select questions (multiple correct answers)
- {sa_count} short answer questions
{topics_instruction}

Format your response EXACTLY as JSON like this:
{{
    "questions": [
        {{
            "type": "multiple_choice",
            "question": "What is...?",
            "topic": "Brief topic label for this question",
            "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"],
            "correct": "A",
            "explanation": "Brief explanation"
        }},
        {{
            "type": "multiple_select",
            "question": "Select ALL that apply: Which of these...?",
            "topic": "Brief topic label for this question",
            "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"],
            "correct": ["A", "C"],
            "explanation": "Brief explanation"
        }},
        {{
            "type": "short_answer",
            "question": "Explain briefly...",
            "topic": "Brief topic label for this question",
            "correct": "The expected answer or key points",
            "explanation": "More detailed explanation"
        }}
    ]
}}

NOTES CONTENT:
{combined_content[:8000]}

Generate questions that test understanding, not just recall. Make them challenging but fair."""

        try:
            from openai import OpenAI
            client = OpenAI()
            
            # Scale max tokens with question count
            max_tokens = min(8000, 300 * question_count + 500)
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a quiz generator. Output ONLY valid JSON, no markdown code blocks."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=max_tokens
            )
            
            result = response.choices[0].message.content.strip()
            
            # Clean up response if it has markdown code blocks
            if result.startswith("```"):
                result = result.split("```")[1]
                if result.startswith("json"):
                    result = result[4:]
                result = result.strip()
            
            import json
            quiz_data = json.loads(result)
            
            debug_log("QUIZ", f"Generated {len(quiz_data['questions'])} questions")
            return quiz_data['questions']
            
        except Exception as e:
            debug_log("QUIZ_ERROR", f"OpenAI quiz generation failed: {str(e)}")
            raise
    
    def _quiz_ready(self, questions, loading_win):
        """Quiz questions ready, start the quiz"""
        loading_win.destroy()
        
        if not questions:
            self.status_label.configure(text="Failed to generate quiz questions")
            return
        
        self.quiz_questions = questions
        self.current_quiz_index = 0
        
        debug_log("QUIZ", f"Starting quiz with {len(questions)} questions")
        
        # Show first question
        self._show_question(0)
    
    def _quiz_error(self, error_msg, loading_win):
        """Handle quiz generation error"""
        loading_win.destroy()
        self.status_label.configure(text=f"Quiz error: {error_msg}")
    
    def _show_question(self, index):
        """Display a quiz question in its own window"""
        if index >= len(self.quiz_questions):
            self._show_quiz_results()
            return
        
        question = self.quiz_questions[index]
        q_type = question.get('type', 'multiple_choice')
        
        debug_log("QUIZ", f"Showing question {index + 1}", {"type": q_type})
        
        # Create question window
        q_win = ctk.CTkToplevel(self.window)
        q_win.title(f"Question {index + 1} of {len(self.quiz_questions)}")
        q_win.configure(fg_color="#1a1a1a")
        q_win.attributes("-topmost", True)
        
        if q_type == "short_answer":
            q_win.geometry("550x400")
        else:
            q_win.geometry("550x500")
        
        # Center the window
        screen_width = q_win.winfo_screenwidth()
        screen_height = q_win.winfo_screenheight()
        win_width = 550
        win_height = 500 if q_type != "short_answer" else 400
        x = (screen_width - win_width) // 2
        y = (screen_height - win_height) // 2
        q_win.geometry(f"{win_width}x{win_height}+{x}+{y}")
        
        # Progress indicator
        progress = ctk.CTkLabel(
            q_win,
            text=f"Question {index + 1}/{len(self.quiz_questions)} | Score: {self.quiz_score['correct']}/{self.quiz_score['correct'] + self.quiz_score['incorrect']}",
            font=("Segoe UI", 10),
            text_color="#666666"
        )
        progress.pack(pady=(10, 5))
        
        # Question type indicator
        type_labels = {
            "multiple_choice": "📝 Multiple Choice (select one)",
            "multiple_select": "☑️ Multiple Select (select ALL that apply)",
            "short_answer": "✏️ Short Answer"
        }
        type_label = ctk.CTkLabel(
            q_win,
            text=type_labels.get(q_type, "Question"),
            font=("Segoe UI", 11),
            text_color="#FF6B00"
        )
        type_label.pack(pady=(0, 10))
        
        # Question text
        q_text = ctk.CTkLabel(
            q_win,
            text=question['question'],
            font=("Segoe UI", 14),
            text_color="white",
            wraplength=500,
            justify="left"
        )
        q_text.pack(padx=20, pady=(10, 20))
        
        if q_type == "short_answer":
            self._show_short_answer_question(q_win, question, index)
        elif q_type == "multiple_select":
            self._show_multiple_select_question(q_win, question, index)
        else:
            self._show_multiple_choice_question(q_win, question, index)
        
        q_win.focus_set()
    
    def _show_multiple_choice_question(self, q_win, question, index):
        """Show multiple choice question with numbered options"""
        options = question.get('options', [])
        correct = question.get('correct', '')
        
        # Options frame
        options_frame = ctk.CTkFrame(q_win, fg_color="#1a1a1a")
        options_frame.pack(padx=20, pady=10, fill="x")
        
        def select_answer(letter, btn, all_buttons):
            # Check if correct
            is_correct = letter.upper() == correct.upper()
            
            # Visual feedback
            for b in all_buttons:
                b.configure(state="disabled")
            
            if is_correct:
                btn.configure(fg_color="#2E7D32")  # Green
                self.quiz_score['correct'] += 1
            else:
                btn.configure(fg_color="#C62828")  # Red
                self.quiz_score['incorrect'] += 1
                # Save to review
                self._save_to_review(question)
                # Highlight correct answer
                for b, opt in zip(all_buttons, options):
                    if opt.startswith(correct.upper() + ")"):
                        b.configure(fg_color="#2E7D32")
            
            # Show explanation and next button
            self._show_answer_feedback(q_win, question, is_correct, index)
        
        buttons = []
        for i, option in enumerate(options):
            letter = chr(65 + i)  # A, B, C, D...
            num = i + 1
            
            btn = ctk.CTkButton(
                options_frame,
                text=f"{num}. {option}",
                width=480,
                height=45,
                font=("Segoe UI", 12),
                fg_color="#3a3a3a",
                hover_color="#4a4a4a",
                anchor="w"
            )
            btn.pack(pady=5)
            buttons.append(btn)
            
            # Set command after all buttons created
            btn.configure(command=lambda l=letter, b=btn: select_answer(l, b, buttons))
        
        # Numpad bindings
        for i in range(len(options)):
            letter = chr(65 + i)
            num = str(i + 1)
            q_win.bind(num, lambda e, l=letter: select_answer(l, buttons[ord(l) - 65], buttons))
            q_win.bind(f"<KP_{num}>", lambda e, l=letter: select_answer(l, buttons[ord(l) - 65], buttons))
    
    def _show_multiple_select_question(self, q_win, question, index):
        """Show multiple select question with checkboxes"""
        options = question.get('options', [])
        correct = question.get('correct', [])
        
        # Options frame
        options_frame = ctk.CTkFrame(q_win, fg_color="#1a1a1a")
        options_frame.pack(padx=20, pady=10, fill="x")
        
        selected = {}
        checkboxes = []
        
        for i, option in enumerate(options):
            letter = chr(65 + i)
            num = i + 1
            
            var = ctk.BooleanVar(value=False)
            selected[letter] = var
            
            cb_frame = ctk.CTkFrame(options_frame, fg_color="#1a1a1a")
            cb_frame.pack(fill="x", pady=3)
            
            cb = ctk.CTkCheckBox(
                cb_frame,
                text=f"{num}. {option}",
                variable=var,
                font=("Segoe UI", 12),
                fg_color="#FF6B00",
                hover_color="#FF8C00",
                text_color="white"
            )
            cb.pack(anchor="w", padx=10)
            checkboxes.append((cb, letter))
        
        # Submit button
        def submit_answer():
            # Get selected answers
            user_answers = [l for l, v in selected.items() if v.get()]
            correct_set = set([c.upper() for c in correct])
            user_set = set([u.upper() for u in user_answers])
            
            is_correct = user_set == correct_set
            
            # Visual feedback
            for cb, letter in checkboxes:
                cb.configure(state="disabled")
                if letter.upper() in correct_set:
                    cb.configure(fg_color="#2E7D32")  # Green for correct
                elif letter.upper() in user_set:
                    cb.configure(fg_color="#C62828")  # Red for wrong selection
            
            if is_correct:
                self.quiz_score['correct'] += 1
            else:
                self.quiz_score['incorrect'] += 1
                self._save_to_review(question)
            
            submit_btn.configure(state="disabled")
            self._show_answer_feedback(q_win, question, is_correct, index)
        
        submit_btn = ctk.CTkButton(
            q_win,
            text="Submit Answer",
            width=200,
            height=40,
            font=("Segoe UI", 13, "bold"),
            fg_color="#FF6B00",
            hover_color="#FF8C00",
            command=submit_answer
        )
        submit_btn.pack(pady=15)
        
        # Numpad toggles
        for i in range(len(options)):
            letter = chr(65 + i)
            num = str(i + 1)
            
            def toggle(l=letter):
                selected[l].set(not selected[l].get())
            
            q_win.bind(num, lambda e, l=letter: toggle(l))
            q_win.bind(f"<KP_{num}>", lambda e, l=letter: toggle(l))
        
        def on_return(e):
            if e.state & 0x1:  # Shift key
                return
            submit_answer()
            return "break"
        q_win.bind("<Return>", on_return)
    
    def _show_short_answer_question(self, q_win, question, index):
        """Show short answer question with text input"""
        correct = question.get('correct', '')
        
        # Input frame
        input_frame = ctk.CTkFrame(q_win, fg_color="#1a1a1a")
        input_frame.pack(padx=20, pady=10, fill="x")
        
        answer_entry = ctk.CTkTextbox(
            input_frame,
            width=480,
            height=80,
            font=("Segoe UI", 12),
            fg_color="#2a2a2a"
        )
        answer_entry.pack(pady=10)
        
        hint_label = ctk.CTkLabel(
            q_win,
            text="Press Enter to submit your answer",
            font=("Segoe UI", 10),
            text_color="#666666"
        )
        hint_label.pack()
        
        # Result display (hidden initially)
        result_frame = ctk.CTkFrame(q_win, fg_color="#2a2a2a")
        
        def submit_answer(event=None):
            user_answer = answer_entry.get("1.0", "end").strip()
            if not user_answer:
                return
            
            answer_entry.configure(state="disabled")
            hint_label.pack_forget()
            
            # Show correct answer
            result_frame.pack(padx=20, pady=10, fill="x")
            
            correct_label = ctk.CTkLabel(
                result_frame,
                text="✓ Correct Answer:",
                font=("Segoe UI", 11, "bold"),
                text_color="#4CAF50"
            )
            correct_label.pack(anchor="w", padx=10, pady=(10, 5))
            
            correct_text = ctk.CTkLabel(
                result_frame,
                text=correct,
                font=("Segoe UI", 12),
                text_color="white",
                wraplength=450,
                justify="left"
            )
            correct_text.pack(anchor="w", padx=10, pady=(0, 10))
            
            # Self-assessment buttons
            assess_label = ctk.CTkLabel(
                q_win,
                text="Was your answer correct?",
                font=("Segoe UI", 12),
                text_color="#FF6B00"
            )
            assess_label.pack(pady=(10, 5))
            
            assess_frame = ctk.CTkFrame(q_win, fg_color="#1a1a1a")
            assess_frame.pack(pady=5)
            
            def mark_correct():
                self.quiz_score['correct'] += 1
                # Log understood topic
                topic = question.get('topic', '')
                if topic:
                    self._log_understood_topic(topic)
                assess_frame.destroy()
                assess_label.destroy()
                self._show_next_button(q_win, index)
            
            def mark_incorrect():
                self.quiz_score['incorrect'] += 1
                self._save_to_review(question)
                assess_frame.destroy()
                assess_label.destroy()
                self._show_next_button(q_win, index)
            
            yes_btn = ctk.CTkButton(
                assess_frame,
                text="Yes (Y)",
                width=100,
                height=35,
                font=("Segoe UI", 12),
                fg_color="#2E7D32",
                hover_color="#388E3C",
                command=mark_correct
            )
            yes_btn.pack(side="left", padx=10)
            
            no_btn = ctk.CTkButton(
                assess_frame,
                text="No (N)",
                width=100,
                height=35,
                font=("Segoe UI", 12),
                fg_color="#C62828",
                hover_color="#D32F2F",
                command=mark_incorrect
            )
            no_btn.pack(side="left", padx=10)
            
            q_win.bind("y", lambda e: mark_correct())
            q_win.bind("Y", lambda e: mark_correct())
            q_win.bind("n", lambda e: mark_incorrect())
            q_win.bind("N", lambda e: mark_incorrect())
        
        def on_return(e):
            if e.state & 0x1:  # Shift key - allow newline
                return
            submit_answer(e)
            return "break"
        
        def on_tab(e):
            answer_entry.tk_focusNext().focus()
            return "break"
        
        def on_shift_tab(e):
            answer_entry.tk_focusPrev().focus()
            return "break"
        
        # Bind Tab to internal textbox widget for CTkTextbox
        try:
            internal = answer_entry._textbox
            internal.bind("<Tab>", on_tab)
            internal.bind("<Shift-Tab>", on_shift_tab)
        except AttributeError:
            pass
        answer_entry.bind("<Return>", on_return)
        answer_entry.bind("<Tab>", on_tab)
        answer_entry.bind("<Shift-Tab>", on_shift_tab)
        answer_entry.focus_set()
    
    def _show_answer_feedback(self, q_win, question, is_correct, index):
        """Show feedback after answering"""
        feedback_frame = ctk.CTkFrame(q_win, fg_color="#1a1a1a")
        feedback_frame.pack(pady=10, fill="x", padx=20)
        
        if is_correct:
            feedback_label = ctk.CTkLabel(
                feedback_frame,
                text="✓ Correct!",
                font=("Segoe UI", 14, "bold"),
                text_color="#4CAF50"
            )
            # Log understood topic
            topic = question.get('topic', '')
            if topic:
                self._log_understood_topic(topic)
        else:
            feedback_label = ctk.CTkLabel(
                feedback_frame,
                text="✗ Incorrect",
                font=("Segoe UI", 14, "bold"),
                text_color="#F44336"
            )
        feedback_label.pack(pady=5)
        
        # Show explanation
        explanation = question.get('explanation', '')
        if explanation:
            exp_label = ctk.CTkLabel(
                feedback_frame,
                text=explanation,
                font=("Segoe UI", 11),
                text_color="#888888",
                wraplength=480,
                justify="left"
            )
            exp_label.pack(pady=5)
        
        self._show_next_button(q_win, index)
    
    def _show_next_button(self, q_win, index):
        """Show button to proceed to next question"""
        next_btn = ctk.CTkButton(
            q_win,
            text="Next Question →" if index < len(self.quiz_questions) - 1 else "See Results",
            width=200,
            height=40,
            font=("Segoe UI", 13, "bold"),
            fg_color="#FF6B00",
            hover_color="#FF8C00",
            command=lambda: self._next_question(q_win, index)
        )
        next_btn.pack(pady=15)
        
        q_win.bind("<Return>", lambda e: self._next_question(q_win, index))
        q_win.bind("<space>", lambda e: self._next_question(q_win, index))
    
    def _next_question(self, current_win, current_index):
        """Proceed to next question"""
        current_win.destroy()
        self.current_quiz_index = current_index + 1
        self._show_question(self.current_quiz_index)
    
    def _save_to_review(self, question):
        """Save missed question to Review.txt"""
        debug_log("QUIZ", "Saving question to Review.txt")
        
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            separator = "-" * 60
            
            q_type = question.get('type', 'multiple_choice')
            correct = question.get('correct', '')
            if isinstance(correct, list):
                correct = ", ".join(correct)
            
            review_content = f"\n{timestamp}\nType: {q_type}\nQ: {question['question']}\nCorrect Answer: {correct}\n{separator}\n"
            
            with open("Review.txt", 'a', encoding='utf-8') as f:
                f.write(review_content)
            
            debug_log("QUIZ", "Question saved to Review.txt")
            
        except Exception as e:
            debug_log("QUIZ_ERROR", f"Failed to save to Review.txt: {str(e)}")
    
    def _show_quiz_results(self):
        """Show final quiz results"""
        total = self.quiz_score['correct'] + self.quiz_score['incorrect']
        percentage = (self.quiz_score['correct'] / total * 100) if total > 0 else 0
        
        debug_log("QUIZ", f"Quiz complete", {"score": self.quiz_score, "percentage": percentage})
        
        # Create results window
        results_win = ctk.CTkToplevel(self.window)
        results_win.title("Quiz Results")
        results_win.geometry("400x350")
        results_win.configure(fg_color="#1a1a1a")
        results_win.attributes("-topmost", True)
        
        # Center the window
        screen_width = results_win.winfo_screenwidth()
        screen_height = results_win.winfo_screenheight()
        x = (screen_width - 400) // 2
        y = (screen_height - 350) // 2
        results_win.geometry(f"400x350+{x}+{y}")
        
        # Title
        title = ctk.CTkLabel(
            results_win,
            text="🎉 Quiz Complete!",
            font=("Segoe UI", 22, "bold"),
            text_color="#FF6B00"
        )
        title.pack(pady=(30, 20))
        
        # Score
        score_label = ctk.CTkLabel(
            results_win,
            text=f"{self.quiz_score['correct']}/{total}",
            font=("Segoe UI", 48, "bold"),
            text_color="white"
        )
        score_label.pack(pady=10)
        
        # Percentage
        if percentage >= 80:
            color = "#4CAF50"
            message = "Excellent!"
        elif percentage >= 60:
            color = "#FF9800"
            message = "Good job!"
        else:
            color = "#F44336"
            message = "Keep studying!"
        
        percent_label = ctk.CTkLabel(
            results_win,
            text=f"{percentage:.0f}% - {message}",
            font=("Segoe UI", 18),
            text_color=color
        )
        percent_label.pack(pady=10)
        
        # Missed questions note
        if self.quiz_score['incorrect'] > 0:
            missed_label = ctk.CTkLabel(
                results_win,
                text=f"💡 {self.quiz_score['incorrect']} question(s) saved to Review.txt",
                font=("Segoe UI", 11),
                text_color="#888888"
            )
            missed_label.pack(pady=10)
        
        # Close button
        close_btn = ctk.CTkButton(
            results_win,
            text="Close",
            width=150,
            height=40,
            font=("Segoe UI", 13),
            fg_color="#3a3a3a",
            hover_color="#4a4a4a",
            command=results_win.destroy
        )
        close_btn.pack(pady=20)
        
        # Button focus visuals
        close_btn.bind("<FocusIn>", lambda e: close_btn.configure(border_width=2, border_color="#FFFFFF"))
        close_btn.bind("<FocusOut>", lambda e: close_btn.configure(border_width=0))
        close_btn.bind("<Tab>", lambda e: "break")
        close_btn.bind("<Shift-Tab>", lambda e: "break")
        
        results_win.bind("<Return>", lambda e: results_win.destroy())
        results_win.bind("<Escape>", lambda e: results_win.destroy())
        results_win.bind("<space>", lambda e: results_win.destroy())
        close_btn.focus_set()

    def on_left_arrow_pressed(self, event):
        """Handle left arrow - go back one word (when paused)"""
        debug_log("KEYPRESS_LEFT", "Left arrow pressed", {
            "is_paused": self.is_paused,
            "current_index": self.current_word_index
        })
        
        if self.is_paused and self.formatted_words:
            self._navigate_word(-1)
            # Start repeat if not already running
            if self.arrow_repeat_job is None:
                self._start_arrow_repeat(-1)
        
        return "break"
    
    def on_right_arrow_pressed(self, event):
        """Handle right arrow - go forward one word (when paused)"""
        debug_log("KEYPRESS_RIGHT", "Right arrow pressed", {
            "is_paused": self.is_paused,
            "current_index": self.current_word_index
        })
        
        if self.is_paused and self.formatted_words:
            self._navigate_word(1)
            # Start repeat if not already running
            if self.arrow_repeat_job is None:
                self._start_arrow_repeat(1)
        
        return "break"
    
    def on_arrow_released(self, event):
        """Handle arrow key release - stop repeating"""
        debug_log("KEYRELEASE_ARROW", f"Arrow key released: {event.keysym}")
        self._stop_arrow_repeat()
        return "break"
    
    def _start_arrow_repeat(self, direction):
        """Start repeating word navigation while arrow is held"""
        debug_log("ARROW_REPEAT", f"Starting arrow repeat, direction: {direction}")
        
        def repeat():
            if self.is_paused and self.formatted_words:
                self._navigate_word(direction)
                self.arrow_repeat_job = self.window.after(self.arrow_repeat_delay, repeat)
        
        # Initial delay before repeat starts (slightly longer)
        self.arrow_repeat_job = self.window.after(300, repeat)
    
    def _stop_arrow_repeat(self):
        """Stop the arrow key repeat"""
        if self.arrow_repeat_job is not None:
            debug_log("ARROW_REPEAT", "Stopping arrow repeat")
            self.window.after_cancel(self.arrow_repeat_job)
            self.arrow_repeat_job = None
    
    def _navigate_word(self, direction):
        """Navigate to the next/previous word"""
        new_index = self.current_word_index + direction
        
        # Clamp to valid range
        if new_index < 0:
            new_index = 0
        elif new_index >= len(self.formatted_words):
            new_index = len(self.formatted_words) - 1
        
        if new_index != self.current_word_index:
            self.current_word_index = new_index
            word, _, _ = self.formatted_words[self.current_word_index]
            
            debug_log("NAVIGATE_WORD", f"Navigated to word {self.current_word_index + 1}/{len(self.formatted_words)}", {
                "word": word,
                "direction": direction
            })
            
            # Update display
            self.display_word(word)
            self.update_progress_bar()
    
    def update_progress_bar(self):
        """Update the progress bar to reflect current position"""
        if self.progress_bar and self.formatted_words:
            progress = (self.current_word_index + 1) / len(self.formatted_words)
            self.progress_bar.set(progress)
            
            if self.progress_label:
                self.progress_label.configure(
                    text=f"{self.current_word_index + 1}/{len(self.formatted_words)}"
                )
            
            debug_log("PROGRESS_UPDATE", "Progress bar updated", {
                "current": self.current_word_index + 1,
                "total": len(self.formatted_words),
                "progress": progress
            })
    
    # ==================== MAIN FUNCTIONALITY ====================
    
    def show_window(self):
        """Show the Spreeder window and load clipboard"""
        debug_log("WINDOW_SHOW", "Showing window")
        
        # Reset quick answer mode (we're in normal clipboard mode now)
        self.quick_answer_mode = False
        self.quick_answer = ""
        self.pending_quick_answer = None
        self._on_quick_answer_complete = None
        
        # Reset simplified explanation state (new text = new explanations needed)
        self.simplified_explanations = []
        self.current_explanation_index = 0
        self.simplify_source_text = ""
        
        # Reset text view mode to serial reader
        self.full_text_view_mode = False
        
        # Read clipboard
        try:
            self.current_text = pyperclip.paste()
            debug_log("CLIPBOARD", "Clipboard read successfully", {
                "text_length": len(self.current_text),
                "text_preview": self.current_text[:100] + "..." if len(self.current_text) > 100 else self.current_text
            })
        except Exception as e:
            debug_log("CLIPBOARD_ERROR", f"Failed to read clipboard: {str(e)}")
            self.current_text = "Error reading clipboard"
        
        # Parse words
        self.words = self.current_text.split()
        self.current_word_index = 0
        debug_log("TEXT_PARSE", f"Parsed {len(self.words)} words from clipboard")
        
        # Reset UI state
        self.word_label.pack(expand=True)
        self.summary_text.pack_forget()
        self.word_label.configure(text="Ready")
        self.status_label.configure(text="Press SPACE to start | CTRL+ALT+SPACE for full text | F3 to close")
        
        # Check if clipboard is the same as before - use cached summary
        if self.current_text == self.last_clipboard_text and self.cached_summary:
            debug_log("SUMMARY_CACHE", "Using cached summary (clipboard unchanged)", {
                "cached_length": len(self.cached_summary)
            })
            self.summary = self.cached_summary
            self.summary_ready = True
        else:
            # Don't auto-generate summary - wait for Shift+Space
            self.summary_ready = False
            self.summary = ""
            if self.current_text.strip():
                debug_log("SUMMARY_STATE", "Summary will generate on Shift+Space")
                self.last_clipboard_text = self.current_text  # Store for cache comparison
        
        # Show window
        self.window.deiconify()
        self.window.focus_force()
        self.is_visible = True
        debug_log("WINDOW_SHOW", "Window is now visible")
    
    def hide_window(self):
        """Hide the Spreeder window"""
        debug_log("WINDOW_HIDE", "Hiding window")
        
        self.stop_playback = True
        self.is_playing = False
        
        if self.window:
            self.window.withdraw()
        
        self.is_visible = False
        debug_log("WINDOW_HIDE", "Window is now hidden")
    
    def generate_summary_async(self):
        """Generate summary in background thread"""
        debug_log("SUMMARY_ASYNC", "Background summary generation started")
        
        try:
            self.summary = get_summary(self.current_text)
            self.summary_ready = True
            # Cache the summary for reuse if clipboard hasn't changed
            self.cached_summary = self.summary
            debug_log("SUMMARY_ASYNC", "Summary generation complete and cached", {
                "summary_length": len(self.summary)
            })
        except Exception as e:
            debug_log("SUMMARY_ASYNC_ERROR", f"Summary generation failed: {str(e)}")
            self.summary = f"Error generating summary: {str(e)}"
            self.summary_ready = True
    
    def show_summary_immediately(self):
        """Show summary immediately (Shift+F3 behavior)"""
        debug_log("SUMMARY_IMMEDIATE", "Showing summary immediately")
        
        # Stop any playback
        self.stop_playback = True
        self.is_playing = False
        
        # If summary not ready, start generation now
        if not self.summary_ready:
            debug_log("SUMMARY_IMMEDIATE", "Summary not ready, starting generation")
            self.word_label.configure(text="Generating summary...")
            
            # Start summary thread if not already running
            if not (self.summary_thread and self.summary_thread.is_alive()):
                debug_log("SUMMARY_IMMEDIATE", "Starting summary thread")
                self.summary_thread = threading.Thread(target=self.generate_summary_async, daemon=True)
                self.summary_thread.start()
            
            # Wait for summary thread to complete
            if self.summary_thread and self.summary_thread.is_alive():
                debug_log("SUMMARY_IMMEDIATE", "Waiting for summary thread to complete")
                self.summary_thread.join(timeout=30)
        
        # Show summary
        self.display_summary()
    
    def display_summary(self):
        """Display the summary in the UI"""
        debug_log("SUMMARY_DISPLAY", "Displaying summary", {
            "quick_answer_mode": getattr(self, 'quick_answer_mode', False)
        })
        
        # If in quick answer mode, show the quick answer instead of summary
        if getattr(self, 'quick_answer_mode', False):
            debug_log("SUMMARY_DISPLAY", "Quick answer mode - showing full answer")
            self._show_answer(self.quick_answer)
            return
        
        # Hide word label, show summary text
        self.word_label.pack_forget()
        self.summary_text.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Clear and insert summary
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", self.summary)
        self._apply_markdown_formatting(self.summary_text)
        
        # Add note button if not already present
        if not hasattr(self, 'note_button_frame') or not self.note_button_frame.winfo_exists():
            self.note_button_frame = ctk.CTkFrame(self.window)
            self.note_button_frame.pack(side="bottom", pady=5)
            
            self.note_button = ctk.CTkButton(
                self.note_button_frame,
                text="📝",
                width=50,
                height=35,
                font=("Segoe UI Emoji", 18),
                command=self.on_save_note,
                fg_color="#2b2b2b",
                hover_color="#3b3b3b"
            )
            self.note_button.pack(side="left", padx=5)
            
            self.clarify_button = ctk.CTkButton(
                self.note_button_frame,
                text="❓",
                width=50,
                height=35,
                font=("Segoe UI Emoji", 18),
                command=self._show_clarify_prompt,
                fg_color="#2b2b2b",
                hover_color="#3b3b3b"
            )
            self.clarify_button.pack(side="left", padx=5)
        
        self.status_label.configure(text="Press ENTER or SPACE to close | Ctrl+Alt+N to save note")
        debug_log("SUMMARY_DISPLAY", "Summary displayed", {"summary": self.summary})
    
    def get_pause_for_word(self, word: str, is_line_break: bool = False, is_headline: bool = False) -> float:
        """
        Calculate additional pause time based on punctuation and formatting.
        Returns pause time in seconds.
        """
        pause_ms = 0
        pause_reasons = []
        
        # Check for line break marker
        if is_line_break:
            pause_ms = self.pause_delay
            pause_reasons.append("line_break")
        
        # Check for headline (short line, possibly all caps or title case)
        if is_headline:
            pause_ms = max(pause_ms, self.pause_delay)
            pause_reasons.append("headline")
        
        # Check ending punctuation
        if word:
            last_char = word[-1]
            
            # End of sentence - full pause
            if last_char in '.!?':
                pause_ms = max(pause_ms, self.pause_delay)
                pause_reasons.append(f"sentence_end({last_char})")
            
            # Comma, semicolon, colon - half pause
            elif last_char in ',;:':
                pause_ms = max(pause_ms, self.pause_delay // 2)
                pause_reasons.append(f"comma_pause({last_char})")
            
            # Dash or ellipsis - three-quarter pause
            elif last_char in '-–—' or word.endswith('...'):
                pause_ms = max(pause_ms, int(self.pause_delay * 0.75))
                pause_reasons.append("dash_or_ellipsis")
        
        if pause_ms > 0:
            debug_log("PAUSE_CALC", f"Calculated pause for '{word}'", {
                "pause_ms": pause_ms,
                "reasons": pause_reasons,
                "is_line_break": is_line_break,
                "is_headline": is_headline
            })
        
        return pause_ms / 1000.0  # Convert to seconds
    
    def parse_text_with_formatting(self, text: str) -> list:
        """
        Parse text into words while tracking line breaks and headlines.
        Returns list of tuples: (word, is_line_break, is_headline)
        """
        debug_log("TEXT_PARSE_FORMAT", "Parsing text with formatting detection", {
            "text_length": len(text)
        })
        
        result = []
        lines = text.split('\n')
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            words = line.split()
            if not words:
                continue
            
            # Detect if this line might be a headline
            # Headlines are typically: short (< 10 words), no ending punctuation, or ALL CAPS
            is_headline = False
            if len(words) <= 8:
                last_word = words[-1]
                # No sentence-ending punctuation, or all caps
                if last_word[-1] not in '.!?,' or line.isupper():
                    is_headline = True
            
            for j, word in enumerate(words):
                # Mark the last word of each line as having a line break
                is_last_word_in_line = (j == len(words) - 1) and (i < len(lines) - 1)
                # Only the first word gets the headline marker
                is_headline_word = is_headline and (j == 0)
                
                result.append((word, is_last_word_in_line, is_headline_word))
        
        debug_log("TEXT_PARSE_FORMAT", f"Parsed {len(result)} words with formatting", {
            "headlines_found": sum(1 for _, _, h in result if h),
            "line_breaks_found": sum(1 for _, lb, _ in result if lb)
        })
        
        return result
    
    def start_playback(self):
        """Start the rapid serial visual presentation"""
        debug_log("PLAYBACK_START", "Starting RSVP playback", {
            "total_words": len(self.words),
            "wpm": self.wpm,
            "pause_delay": self.pause_delay
        })
        
        if not self.words:
            debug_log("PLAYBACK_ERROR", "No words to display")
            self.word_label.configure(text="No text in clipboard")
            return
        
        # Clear any lingering quick answer callbacks to prevent
        # the quick answer window from appearing after normal playback
        self._on_quick_answer_complete = None
        self.pending_quick_answer = None
        
        self.is_playing = True
        self.is_paused = False
        self.stop_playback = False
        self.current_word_index = 0
        
        # Parse text with formatting info
        self.formatted_words = self.parse_text_with_formatting(self.current_text)
        
        # Update status
        self.status_label.configure(text="Playing... Press SPACE to pause")
        
        # Start playback in separate thread
        self.play_thread = threading.Thread(target=self.playback_loop, daemon=True)
        self.play_thread.start()
    
    def resume_playback(self):
        """Resume playback from current position"""
        debug_log("PLAYBACK_RESUME", "Resuming playback", {
            "from_index": self.current_word_index,
            "total_words": len(self.formatted_words)
        })
        
        if not self.formatted_words or self.current_word_index >= len(self.formatted_words):
            debug_log("PLAYBACK_RESUME", "Nothing to resume, at end of text")
            self.is_paused = False
            return
        
        self.is_playing = True
        self.stop_playback = False
        
        # Update status
        self.status_label.configure(text="Playing... Press SPACE to pause")
        
        # Start playback in separate thread from current position
        self.play_thread = threading.Thread(target=self.playback_loop, daemon=True)
        self.play_thread.start()
    
    def get_word_length_multiplier(self, word: str) -> float:
        """
        Calculate a time multiplier based on word length.
        Short words (1-3 chars) display faster, long words (8+) display longer.
        Returns a multiplier centered around 1.0
        
        Exception: Words ending with sentence-ending punctuation (. ! ?) always return 1.0
        to ensure the full pause delay is applied.
        """
        # Words ending with sentence-ending punctuation should use full timing
        if word and word[-1] in '.!?':
            return 1.0
        
        # Get word length (strip punctuation for accurate count)
        clean_word = ''.join(c for c in word if c.isalnum())
        length = len(clean_word)
        
        # Reference length is 5 characters (average English word)
        # Scale: 1-3 chars = 0.7x, 4-5 = 1.0x, 6-7 = 1.15x, 8-10 = 1.3x, 11+ = 1.5x
        if length <= 2:
            multiplier = 0.6
        elif length <= 3:
            multiplier = 0.75
        elif length <= 5:
            multiplier = 1.0
        elif length <= 7:
            multiplier = 1.15
        elif length <= 10:
            multiplier = 1.3
        else:
            multiplier = 1.5
        
        return multiplier
    
    def playback_loop(self):
        """Main playback loop - runs in separate thread"""
        debug_log("PLAYBACK_LOOP", "Playback loop started", {
            "starting_index": self.current_word_index
        })
        
        base_delay = 60.0 / self.wpm  # Seconds per word
        debug_log("PLAYBACK_LOOP", f"Calculated base delay: {base_delay:.4f} seconds per word")
        
        while self.current_word_index < len(self.formatted_words) and not self.stop_playback:
            word, is_line_break, is_headline = self.formatted_words[self.current_word_index]
            
            debug_log("WORD_DISPLAY", f"Displaying word {self.current_word_index + 1}/{len(self.formatted_words)}", {
                "word": word,
                "index": self.current_word_index,
                "is_line_break": is_line_break,
                "is_headline": is_headline
            })
            
            # Update UI in main thread (word and progress bar)
            self.window.after(0, lambda w=word: self.display_word(w))
            self.window.after(0, self.update_progress_bar)
            
            # Calculate word-length adjusted delay
            length_multiplier = self.get_word_length_multiplier(word)
            adjusted_base_delay = base_delay * length_multiplier
            
            # Calculate total delay (adjusted base + punctuation pause)
            extra_pause = self.get_pause_for_word(word, is_line_break, is_headline)
            total_delay = adjusted_base_delay + extra_pause
            
            if extra_pause > 0:
                debug_log("PLAYBACK_PAUSE", f"Adding pause after '{word}'", {
                    "base_delay": base_delay,
                    "extra_pause": extra_pause,
                    "total_delay": total_delay
                })
            
            self.current_word_index += 1
            time.sleep(total_delay)
        
        debug_log("PLAYBACK_LOOP", "Playback loop ended", {
            "completed": self.current_word_index >= len(self.formatted_words),
            "stopped": self.stop_playback,
            "paused": self.is_paused
        })
        
        self.is_playing = False
        
        # If completed naturally (not paused) and Shift+Space was used, show summary
        if not self.stop_playback and self.current_word_index >= len(self.formatted_words):
            if self.summary_after_playback:
                debug_log("PLAYBACK_COMPLETE", "Playback completed, showing summary (Shift+Space was used)")
                self.window.after(500, self.display_summary)
            else:
                debug_log("PLAYBACK_COMPLETE", "Playback completed, ready to replay (Space only)")
                # Check if we're in simplify mode (showing an explanation)
                if self.simplified_explanations and self.current_explanation_index < 2:
                    self.window.after(0, lambda: self.status_label.configure(text="Done! CTRL+SPACE for simpler | SPACE to replay | F3 to close"))
                else:
                    self.window.after(0, lambda: self.status_label.configure(text="Done! CTRL+SPACE to simplify | SPACE to replay | F3 to close"))
                self.current_word_index = 0  # Reset for replay
    
    def display_word(self, word: str):
        """Display a word with fixation point highlighting"""
        debug_log("WORD_RENDER", f"Rendering word: '{word}'")
        
        fixation_index = get_fixation_point(word)
        
        # Create text with orange highlight at fixation point
        # We'll use a simple approach: display the word with the fixation character in orange
        if len(word) > 0:
            before = word[:fixation_index]
            highlight = word[fixation_index] if fixation_index < len(word) else ""
            after = word[fixation_index + 1:] if fixation_index + 1 < len(word) else ""
            
            # Unfortunately CTkLabel doesn't support rich text easily
            # We'll use a workaround with the label and update it
            # For now, we mark the fixation with brackets
            # A better solution would use multiple labels or a canvas
            
            debug_log("WORD_RENDER", "Word breakdown for fixation", {
                "before": before,
                "highlight": highlight,
                "after": after,
                "fixation_index": fixation_index
            })
            
            # Update the word label
            # We'll display with visual indication using Unicode
            display_text = word
            self.word_label.configure(text=display_text)
            
            # Apply color effect using custom rendering
            # Since CTkLabel has limited rich text, we simulate by using the word
            # In a production app, you'd use a Canvas or multiple Labels
            self.apply_fixation_highlight(word, fixation_index)
    
    def apply_fixation_highlight(self, word: str, fixation_index: int):
        """
        Apply visual highlight to the fixation point.
        Since CTkLabel doesn't support rich text, we use a creative workaround.
        """
        debug_log("HIGHLIGHT", f"Applying highlight to '{word}' at index {fixation_index}")
        
        # For the actual implementation, we'd need to use a more complex widget
        # For now, the word is displayed as-is, and we note the fixation point in logs
        # A full implementation would use tkinter Canvas or multiple labels
        
        # Update label with the word
        self.word_label.configure(text=word)
        
        # Log the intended highlight
        debug_log("HIGHLIGHT", "Fixation point applied (visual indicator)", {
            "word": word,
            "fixation_char": word[fixation_index] if fixation_index < len(word) else "N/A",
            "fixation_index": fixation_index
        })
    
    # ==================== AI STRATEGY ANALYSIS METHODS ====================
    
    def open_strategy_analysis_window(self):
        """Open the AI Strategy Analysis window - triggered by Ctrl+Shift+A"""
        debug_log("STRATEGY_UI", "Opening Strategy Analysis window")
        
        # Check if window already exists
        if hasattr(self, '_strategy_window') and self._strategy_window:
            try:
                if self._strategy_window.winfo_exists():
                    self._strategy_window.lift()
                    self._strategy_window.focus_force()
                    return
            except:
                pass
        
        # Create main analysis window
        self._strategy_window = ctk.CTkToplevel(self.window)
        self._strategy_window.title("AI Strategy Analysis")
        self._strategy_window.geometry("900x750")
        self._strategy_window.configure(fg_color="#1a1a1a")
        self._strategy_window.transient(self.window)
        
        # Center the window
        screen_width = self._strategy_window.winfo_screenwidth()
        screen_height = self._strategy_window.winfo_screenheight()
        x = (screen_width - 900) // 2
        y = (screen_height - 750) // 2
        self._strategy_window.geometry(f"900x750+{x}+{y}")
        
        # Bind Escape to close
        self._strategy_window.bind("<Escape>", lambda e: self._close_strategy_window())
        self._strategy_window.protocol("WM_DELETE_WINDOW", self._close_strategy_window)
        
        # Setup event logging
        setup_global_event_logging(self._strategy_window, "Strategy Analysis")
        
        # Title header
        title_frame = ctk.CTkFrame(self._strategy_window, fg_color="#2a2a2a", corner_radius=10)
        title_frame.pack(fill="x", padx=20, pady=(20, 10))
        
        title_label = ctk.CTkLabel(
            title_frame,
            text="📊 AI Strategy Optimization",
            font=("Segoe UI", 20, "bold"),
            text_color="#FF6B00"
        )
        title_label.pack(pady=15)
        
        subtitle_label = ctk.CTkLabel(
            title_frame,
            text="Press 'Analyze Strategy' to generate a comprehensive AI-powered optimization report",
            font=("Segoe UI", 11),
            text_color="#888888"
        )
        subtitle_label.pack(pady=(0, 15))
        
        # Parameters preview frame
        params_frame = ctk.CTkFrame(self._strategy_window, fg_color="#2a2a2a", corner_radius=10)
        params_frame.pack(fill="x", padx=20, pady=10)
        
        params_header = ctk.CTkLabel(
            params_frame,
            text="Current Strategy Parameters",
            font=("Segoe UI", 14, "bold"),
            text_color="white"
        )
        params_header.pack(pady=(10, 5), anchor="w", padx=15)
        
        # Load current parameters
        self._strategy_params = load_strategy_config()
        
        # Create a scrollable text box for parameters
        self._params_text = ctk.CTkTextbox(
            params_frame,
            height=120,
            font=("Consolas", 10),
            fg_color="#1a1a1a",
            text_color="#00ff00",
            wrap="none"
        )
        self._params_text.pack(fill="x", padx=15, pady=(0, 10))
        self._update_params_display()
        
        # Edit parameters button
        edit_params_btn = ctk.CTkButton(
            params_frame,
            text="⚙️ Edit Parameters",
            width=150,
            font=("Segoe UI", 11),
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            command=self._open_params_editor
        )
        edit_params_btn.pack(pady=(0, 10))
        
        # Auto-test toggle frame
        toggle_frame = ctk.CTkFrame(self._strategy_window, fg_color="transparent")
        toggle_frame.pack(fill="x", padx=20, pady=5)
        
        self._auto_test_var = ctk.BooleanVar(value=False)
        auto_test_check = ctk.CTkCheckBox(
            toggle_frame,
            text="Auto-Test Suggested Changes (apply incrementally and re-run backtest)",
            variable=self._auto_test_var,
            font=("Segoe UI", 11),
            text_color="#888888",
            fg_color="#FF6B00",
            hover_color="#ff8533"
        )
        auto_test_check.pack(side="left")
        
        # Results area
        results_frame = ctk.CTkFrame(self._strategy_window, fg_color="#2a2a2a", corner_radius=10)
        results_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        results_header = ctk.CTkLabel(
            results_frame,
            text="Analysis Results",
            font=("Segoe UI", 14, "bold"),
            text_color="white"
        )
        results_header.pack(pady=(10, 5), anchor="w", padx=15)
        
        self._results_text = ctk.CTkTextbox(
            results_frame,
            font=("Segoe UI", 11),
            fg_color="#1a1a1a",
            text_color="white",
            wrap="word"
        )
        self._results_text.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        self._results_text.insert("1.0", "Click 'Analyze Strategy' to generate an AI-powered optimization report.\n\nThe analysis will evaluate:\n• Expectancy decomposition\n• Structural bottlenecks\n• MFE/MAE analysis\n• Capital efficiency\n• Volatility regime segmentation\n• Quantified parameter adjustments")
        self._results_text.configure(state="disabled")
        
        # Status/cost info
        self._status_label = ctk.CTkLabel(
            results_frame,
            text="Ready | Estimated cost: ~$0.05-0.15",
            font=("Segoe UI", 10),
            text_color="#666666"
        )
        self._status_label.pack(pady=(0, 10))
        
        # Action buttons frame
        buttons_frame = ctk.CTkFrame(self._strategy_window, fg_color="transparent")
        buttons_frame.pack(fill="x", padx=20, pady=(10, 20))
        
        # Analyze button (main action)
        self._analyze_btn = ctk.CTkButton(
            buttons_frame,
            text="🔍 Analyze Strategy (AI)",
            width=200,
            height=40,
            font=("Segoe UI", 13, "bold"),
            fg_color="#FF6B00",
            hover_color="#ff8533",
            command=self._run_strategy_analysis
        )
        self._analyze_btn.pack(side="left", padx=5)
        
        # Apply changes button
        self._apply_btn = ctk.CTkButton(
            buttons_frame,
            text="✅ Apply Suggested Changes",
            width=180,
            height=40,
            font=("Segoe UI", 11),
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            state="disabled",
            command=self._apply_suggested_changes
        )
        self._apply_btn.pack(side="left", padx=5)
        
        # Export button
        self._export_btn = ctk.CTkButton(
            buttons_frame,
            text="📄 Export to .md",
            width=130,
            height=40,
            font=("Segoe UI", 11),
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            state="disabled",
            command=self._export_analysis
        )
        self._export_btn.pack(side="left", padx=5)
        
        # Run backtest button
        self._backtest_btn = ctk.CTkButton(
            buttons_frame,
            text="🔄 Run Backtest",
            width=130,
            height=40,
            font=("Segoe UI", 11),
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            command=self._run_backtest_with_adjustments
        )
        self._backtest_btn.pack(side="left", padx=5)
        
        # Store analysis results
        self._last_analysis = None
        self._suggested_changes = {}
        
        debug_log("STRATEGY_UI", "Strategy Analysis window created")
    
    def _close_strategy_window(self):
        """Close the strategy analysis window"""
        if hasattr(self, '_strategy_window') and self._strategy_window:
            self._strategy_window.destroy()
            self._strategy_window = None
        debug_log("STRATEGY_UI", "Strategy Analysis window closed")
    
    def _update_params_display(self):
        """Update the parameters display text"""
        self._params_text.configure(state="normal")
        self._params_text.delete("1.0", "end")
        
        params_lines = []
        for key, value in sorted(self._strategy_params.items()):
            if isinstance(value, float):
                params_lines.append(f"{key}: {value:.2f}")
            else:
                params_lines.append(f"{key}: {value}")
        
        self._params_text.insert("1.0", "\n".join(params_lines))
        self._params_text.configure(state="disabled")
    
    def _open_params_editor(self):
        """Open a dialog to edit strategy parameters"""
        debug_log("STRATEGY_UI", "Opening parameters editor")
        
        editor_win = ctk.CTkToplevel(self._strategy_window)
        editor_win.title("Edit Strategy Parameters")
        editor_win.geometry("500x600")
        editor_win.configure(fg_color="#1a1a1a")
        editor_win.transient(self._strategy_window)
        
        # Center
        screen_width = editor_win.winfo_screenwidth()
        screen_height = editor_win.winfo_screenheight()
        x = (screen_width - 500) // 2
        y = (screen_height - 600) // 2
        editor_win.geometry(f"500x600+{x}+{y}")
        
        editor_win.bind("<Escape>", lambda e: editor_win.destroy())
        
        # Title
        title = ctk.CTkLabel(
            editor_win,
            text="⚙️ Strategy Parameters",
            font=("Segoe UI", 16, "bold"),
            text_color="#FF6B00"
        )
        title.pack(pady=15)
        
        # Scrollable frame for parameters
        scroll_frame = ctk.CTkScrollableFrame(
            editor_win,
            fg_color="#2a2a2a",
            width=460,
            height=450
        )
        scroll_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Create entry fields for each parameter
        entries = {}
        for key, value in sorted(self._strategy_params.items()):
            row = ctk.CTkFrame(scroll_frame, fg_color="transparent")
            row.pack(fill="x", pady=3)
            
            label = ctk.CTkLabel(
                row,
                text=key.replace("_", " ").title() + ":",
                font=("Segoe UI", 10),
                text_color="#aaaaaa",
                width=200,
                anchor="e"
            )
            label.pack(side="left", padx=(0, 10))
            
            entry = ctk.CTkEntry(
                row,
                width=150,
                font=("Consolas", 11),
                fg_color="#1a1a1a",
                text_color="white"
            )
            entry.insert(0, str(value))
            entry.pack(side="left")
            entries[key] = entry
        
        # Buttons
        btn_frame = ctk.CTkFrame(editor_win, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=15)
        
        def save_params():
            for key, entry in entries.items():
                try:
                    val = entry.get()
                    if '.' in val:
                        self._strategy_params[key] = float(val)
                    else:
                        self._strategy_params[key] = int(val) if val.isdigit() else float(val)
                except ValueError:
                    pass
            save_strategy_config(self._strategy_params)
            self._update_params_display()
            editor_win.destroy()
            debug_log("STRATEGY_UI", "Parameters saved")
        
        def reset_defaults():
            for key, entry in entries.items():
                entry.delete(0, "end")
                entry.insert(0, str(DEFAULT_STRATEGY_PARAMS.get(key, "")))
        
        save_btn = ctk.CTkButton(
            btn_frame,
            text="💾 Save",
            width=100,
            fg_color="#FF6B00",
            hover_color="#ff8533",
            command=save_params
        )
        save_btn.pack(side="left", padx=5)
        
        reset_btn = ctk.CTkButton(
            btn_frame,
            text="🔄 Reset Defaults",
            width=120,
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            command=reset_defaults
        )
        reset_btn.pack(side="left", padx=5)
        
        cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=80,
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            command=editor_win.destroy
        )
        cancel_btn.pack(side="left", padx=5)
    
    def _run_strategy_analysis(self):
        """Run the AI strategy analysis"""
        debug_log("STRATEGY_ANALYSIS", "Starting AI strategy analysis")
        
        # Update UI
        self._analyze_btn.configure(state="disabled", text="🔄 Analyzing...")
        self._status_label.configure(text="Collecting strategy data...")
        self._results_text.configure(state="normal")
        self._results_text.delete("1.0", "end")
        self._results_text.insert("1.0", "Collecting strategy data and sending to AI for analysis...\nThis may take 15-30 seconds.")
        self._results_text.configure(state="disabled")
        
        # Run analysis in background thread
        def run_analysis():
            try:
                # Collect all data
                params = self._strategy_params
                backtest = load_backtest_results()
                trades = load_trade_ledger_metrics()
                regime = load_regime_metrics()
                capital = calculate_capital_efficiency()
                
                debug_log("STRATEGY_ANALYSIS", "Data collected", {
                    "params_count": len(params),
                    "backtest_pnl": backtest.get("total_pnl", 0),
                    "total_trades": trades.get("total_trades", 0)
                })
                
                # Build prompt
                prompt = build_strategy_analysis_prompt(params, backtest, trades, regime, capital)
                
                # Call OpenAI
                self._strategy_window.after(0, lambda: self._status_label.configure(
                    text="Sending to OpenAI for analysis..."
                ))
                
                start_time = time.time()
                
                from openai import OpenAI
                client = OpenAI()
                
                response = client.chat.completions.create(
                    model="gpt-4o",  # Use gpt-4o for comprehensive analysis
                    messages=[
                        {"role": "system", "content": STRATEGY_ANALYSIS_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,  # Lower temp for consistent analysis
                    max_tokens=4000
                )
                
                latency = int((time.time() - start_time) * 1000)
                
                analysis = response.choices[0].message.content
                token_info = {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
                
                cost = estimate_cost(token_info["input_tokens"], token_info["output_tokens"], "gpt-4o")
                
                debug_log("STRATEGY_ANALYSIS", "Analysis complete", {
                    "latency_ms": latency,
                    "tokens": token_info,
                    "cost": cost
                })
                
                # Save to backup
                save_api_response_backup(
                    "STRATEGY_ANALYSIS",
                    f"Strategy Analysis Request ({len(prompt)} chars)",
                    analysis,
                    token_info["input_tokens"],
                    token_info["output_tokens"],
                    token_info["total_tokens"],
                    "gpt-4o"
                )
                
                # Store results
                self._last_analysis = analysis
                self._analysis_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._analysis_params = params.copy()
                
                # Parse suggested changes
                self._suggested_changes = parse_suggested_changes(analysis)
                
                # Update UI on main thread
                self._strategy_window.after(0, lambda: self._show_analysis_results(
                    analysis, token_info, cost, latency
                ))
                
            except Exception as e:
                debug_log("STRATEGY_ANALYSIS_ERROR", f"Analysis failed: {str(e)}")
                self._strategy_window.after(0, lambda: self._show_analysis_error(str(e)))
        
        threading.Thread(target=run_analysis, daemon=True).start()
    
    def _show_analysis_results(self, analysis: str, token_info: dict, cost: float, latency: int):
        """Display the analysis results"""
        self._results_text.configure(state="normal")
        self._results_text.delete("1.0", "end")
        self._results_text.insert("1.0", analysis)
        self._apply_markdown_formatting(self._results_text)
        self._results_text.configure(state="disabled")
        
        # Update status
        self._status_label.configure(
            text=f"✅ Analysis complete | {token_info['total_tokens']} tokens | {format_cost(cost)} | {latency}ms"
        )
        
        # Enable buttons
        self._analyze_btn.configure(state="normal", text="🔍 Analyze Strategy (AI)")
        self._export_btn.configure(state="normal")
        
        if self._suggested_changes:
            self._apply_btn.configure(state="normal")
        
        debug_log("STRATEGY_UI", "Analysis results displayed")
        
        # If auto-test is enabled, run the test loop
        if self._auto_test_var.get() and self._suggested_changes:
            self._run_auto_test_loop()
    
    def _show_analysis_error(self, error: str):
        """Display an error message"""
        self._results_text.configure(state="normal")
        self._results_text.delete("1.0", "end")
        self._results_text.insert("1.0", f"❌ Analysis Failed\n\nError: {error}\n\nPlease check:\n• Your OpenAI API key is configured in .env\n• You have sufficient API credits\n• Your internet connection is working")
        self._results_text.configure(state="disabled")
        
        self._status_label.configure(text="❌ Analysis failed - see error above")
        self._analyze_btn.configure(state="normal", text="🔍 Analyze Strategy (AI)")
    
    def _apply_suggested_changes(self):
        """Apply the AI-suggested parameter changes"""
        if not self._suggested_changes:
            return
        
        debug_log("STRATEGY_UI", f"Applying suggested changes: {self._suggested_changes}")
        
        # Create confirmation dialog
        confirm_win = ctk.CTkToplevel(self._strategy_window)
        confirm_win.title("Apply Changes")
        confirm_win.geometry("450x350")
        confirm_win.configure(fg_color="#1a1a1a")
        confirm_win.transient(self._strategy_window)
        
        screen_width = confirm_win.winfo_screenwidth()
        screen_height = confirm_win.winfo_screenheight()
        x = (screen_width - 450) // 2
        y = (screen_height - 350) // 2
        confirm_win.geometry(f"450x350+{x}+{y}")
        
        title = ctk.CTkLabel(
            confirm_win,
            text="⚠️ Apply Suggested Changes",
            font=("Segoe UI", 16, "bold"),
            text_color="#FF6B00"
        )
        title.pack(pady=15)
        
        info = ctk.CTkLabel(
            confirm_win,
            text="The following parameter changes will be applied:",
            font=("Segoe UI", 11),
            text_color="#888888"
        )
        info.pack(pady=5)
        
        # Show changes
        changes_text = ctk.CTkTextbox(
            confirm_win,
            height=150,
            font=("Consolas", 11),
            fg_color="#2a2a2a",
            text_color="#00ff00"
        )
        changes_text.pack(fill="x", padx=20, pady=10)
        
        for param, new_value in self._suggested_changes.items():
            old_value = self._strategy_params.get(param, "N/A")
            changes_text.insert("end", f"{param}:\n  Old: {old_value}\n  New: {new_value}\n\n")
        
        changes_text.configure(state="disabled")
        
        btn_frame = ctk.CTkFrame(confirm_win, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=15)
        
        def apply():
            for param, value in self._suggested_changes.items():
                self._strategy_params[param] = value
            save_strategy_config(self._strategy_params)
            self._update_params_display()
            confirm_win.destroy()
            debug_log("STRATEGY_UI", "Changes applied successfully")
        
        apply_btn = ctk.CTkButton(
            btn_frame,
            text="✅ Apply Changes",
            width=130,
            fg_color="#FF6B00",
            hover_color="#ff8533",
            command=apply
        )
        apply_btn.pack(side="left", padx=5)
        
        cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=80,
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            command=confirm_win.destroy
        )
        cancel_btn.pack(side="left", padx=5)
    
    def _export_analysis(self):
        """Export the analysis to a markdown file"""
        if not self._last_analysis:
            return
        
        timestamp = getattr(self, '_analysis_timestamp', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        params = getattr(self, '_analysis_params', self._strategy_params)
        
        filepath = save_analysis_report(self._last_analysis, params, timestamp)
        
        if filepath:
            self._status_label.configure(text=f"✅ Exported to: {os.path.basename(filepath)}")
            debug_log("STRATEGY_UI", f"Analysis exported to {filepath}")
        else:
            self._status_label.configure(text="❌ Export failed")
    
    def _run_backtest_with_adjustments(self):
        """Run a backtest with the current/adjusted parameters"""
        debug_log("STRATEGY_UI", "Backtest requested")
        
        # This would integrate with an actual backtesting system
        # For now, show a placeholder message
        self._results_text.configure(state="normal")
        self._results_text.insert("end", "\n\n" + "="*60 + "\n")
        self._results_text.insert("end", "📊 BACKTEST REQUESTED\n")
        self._results_text.insert("end", "="*60 + "\n\n")
        self._results_text.insert("end", "To run a backtest:\n")
        self._results_text.insert("end", "1. Ensure backtest_results.json is populated by your backtesting system\n")
        self._results_text.insert("end", "2. Run your backtest with the current parameters\n")
        self._results_text.insert("end", "3. Re-run this analysis to see updated metrics\n")
        self._results_text.insert("end", "\nCurrent parameters have been saved to strategy_config.json\n")
        self._results_text.configure(state="disabled")
        
        # Save current params
        save_strategy_config(self._strategy_params)
    
    def _run_auto_test_loop(self):
        """Run automatic testing of suggested changes"""
        debug_log("STRATEGY_UI", "Starting auto-test loop")
        
        self._results_text.configure(state="normal")
        self._results_text.insert("end", "\n\n" + "="*60 + "\n")
        self._results_text.insert("end", "🔄 AUTO-TEST MODE ENABLED\n")
        self._results_text.insert("end", "="*60 + "\n\n")
        self._results_text.insert("end", "Suggested changes will be applied incrementally.\n")
        self._results_text.insert("end", "After applying each change, re-run your backtest and\n")
        self._results_text.insert("end", "then run analysis again to compare results.\n\n")
        
        for param, value in self._suggested_changes.items():
            old = self._strategy_params.get(param, "N/A")
            self._results_text.insert("end", f"• {param}: {old} → {value}\n")
        
        self._results_text.insert("end", "\nApply changes individually using 'Apply Suggested Changes'\n")
        self._results_text.insert("end", "and monitor the impact on your backtest results.\n")
        self._results_text.configure(state="disabled")

    def run(self):
        """Run the application main loop"""
        debug_log("APP_RUN", "Starting application main loop")
        
        print("Spreeder is running. Press F3 to open the window.")
        print("Press Ctrl+Shift+A for AI Strategy Analysis.")
        print("Press Ctrl+C to exit.")
        
        debug_log("APP_RUN", "Application ready, starting tkinter mainloop")
        
        try:
            # Run the tkinter mainloop - this is the main event loop
            self.window.mainloop()
        except KeyboardInterrupt:
            debug_log("APP_EXIT", "Application exiting due to KeyboardInterrupt")
            print("\nExiting Spreeder...")
        except Exception as e:
            debug_log("APP_ERROR", f"Unexpected error: {str(e)}")
            raise

# ==================== ENHANCED FIXATION POINT DISPLAY ====================

class EnhancedSpreederApp(SpreederApp):
    """
    Enhanced version with better fixation point visualization using Canvas.
    """
    
    def create_ui_elements(self):
        """Create all UI elements with enhanced word display"""
        debug_log("UI_ENHANCED", "Creating enhanced UI elements with Canvas-based word display")
        
        # Main frame
        main_frame = ctk.CTkFrame(self.window, fg_color="#1a1a1a")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        main_frame.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "main_frame"))
        main_frame.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "main_frame"))
        main_frame.bind("<Button-1>", lambda e: self.on_widget_click(e, "main_frame"))
        
        # Status label at top
        self.status_label = ctk.CTkLabel(
            main_frame,
            text="Press SPACE to start | F3 to close | SHIFT+F3 for summary",
            font=("Segoe UI", 12),
            text_color="#888888"
        )
        self.status_label.pack(pady=(0, 20))
        self.status_label.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "status_label"))
        self.status_label.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "status_label"))
        debug_log("UI_ENHANCED", "Created status label")
        
        # Word display area frame
        self.word_frame = ctk.CTkFrame(main_frame, fg_color="#2a2a2a", corner_radius=10)
        self.word_frame.pack(fill="both", expand=True, pady=10)
        self.word_frame.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "word_frame"))
        self.word_frame.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "word_frame"))
        
        # Canvas for rich text display (allows multiple colors)
        import tkinter as tk
        self.word_canvas = tk.Canvas(
            self.word_frame,
            bg="#2a2a2a",
            highlightthickness=0
        )
        self.word_canvas.pack(fill="both", expand=True)
        self.word_canvas.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "word_canvas"))
        self.word_canvas.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "word_canvas"))
        self.word_canvas.bind("<Button-1>", lambda e: self.on_widget_click(e, "word_canvas"))
        self.word_canvas.bind("<Configure>", self.on_canvas_resize)
        debug_log("UI_ENHANCED", "Created word canvas")
        
        # Also keep a label for fallback/ready state
        self.word_label = ctk.CTkLabel(
            self.word_frame,
            text="Ready",
            font=("Comic Sans MS", 48, "bold"),
            text_color="white"
        )
        # Don't pack the label, we'll use canvas primarily
        debug_log("UI_ENHANCED", "Created word label (fallback)")
        
        # Summary text area (initially hidden)
        self.summary_text = ctk.CTkTextbox(
            self.word_frame,
            font=("Segoe UI", 14),
            fg_color="#2a2a2a",
            text_color="white",
            wrap="word"
        )
        self.summary_text.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "summary_text"))
        self.summary_text.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "summary_text"))
        debug_log("UI_ENHANCED", "Created summary text area")
        
        # Progress bar frame
        progress_frame = ctk.CTkFrame(main_frame, fg_color="#1a1a1a")
        progress_frame.pack(fill="x", pady=(10, 0))
        progress_frame.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "progress_frame"))
        progress_frame.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "progress_frame"))
        
        # Progress label (word count)
        self.progress_label = ctk.CTkLabel(
            progress_frame,
            text="0/0",
            font=("Segoe UI", 11),
            text_color="#888888",
            width=70
        )
        self.progress_label.pack(side="left", padx=(0, 10))
        self.progress_label.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "progress_label"))
        self.progress_label.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "progress_label"))
        debug_log("UI_ENHANCED", "Created progress label")
        
        # Progress bar (clickable for seeking)
        self.progress_bar = ctk.CTkProgressBar(
            progress_frame,
            fg_color="#3a3a3a",
            progress_color="#FF6B00",
            height=8
        )
        self.progress_bar.set(0)
        self.progress_bar.pack(side="left", fill="x", expand=True, pady=5)
        self.progress_bar.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "progress_bar"))
        self.progress_bar.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "progress_bar"))
        self.progress_bar.bind("<Button-1>", self.on_progress_bar_click)
        debug_log("UI_ENHANCED", "Created progress bar")
        
        # Controls container frame
        controls_frame = ctk.CTkFrame(main_frame, fg_color="#1a1a1a")
        controls_frame.pack(fill="x", pady=(10, 0))
        
        # WPM control frame
        wpm_frame = ctk.CTkFrame(controls_frame, fg_color="#1a1a1a")
        wpm_frame.pack(fill="x", pady=(0, 10))
        wpm_frame.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "wpm_frame"))
        wpm_frame.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "wpm_frame"))
        
        # WPM label
        self.wpm_label = ctk.CTkLabel(
            wpm_frame,
            text=f"WPM: {self.wpm}",
            font=("Segoe UI", 14),
            text_color="white",
            width=100
        )
        self.wpm_label.pack(side="left", padx=(0, 10))
        self.wpm_label.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "wpm_label"))
        self.wpm_label.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "wpm_label"))
        debug_log("UI_ENHANCED", "Created WPM label")
        
        # WPM slider
        self.wpm_slider = ctk.CTkSlider(
            wpm_frame,
            from_=100,
            to=1000,
            number_of_steps=90,
            command=self.on_wpm_change,
            fg_color="#3a3a3a",
            progress_color="#FF6B00",
            button_color="#FF6B00",
            button_hover_color="#FF8C00"
        )
        self.wpm_slider.set(self.wpm)
        self.wpm_slider.pack(side="left", fill="x", expand=True)
        self.wpm_slider.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "wpm_slider"))
        self.wpm_slider.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "wpm_slider"))
        self.wpm_slider.bind("<ButtonRelease-1>", lambda e: self.on_slider_release(e))
        debug_log("UI_ENHANCED", "Created WPM slider")
        
        # Pause delay control frame
        pause_frame = ctk.CTkFrame(controls_frame, fg_color="#1a1a1a")
        pause_frame.pack(fill="x")
        pause_frame.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "pause_frame"))
        pause_frame.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "pause_frame"))
        
        # Pause delay label
        self.pause_label = ctk.CTkLabel(
            pause_frame,
            text=f"Pause: {self.pause_delay}ms",
            font=("Segoe UI", 14),
            text_color="white",
            width=100
        )
        self.pause_label.pack(side="left", padx=(0, 10))
        self.pause_label.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "pause_label"))
        self.pause_label.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "pause_label"))
        debug_log("UI_ENHANCED", "Created pause delay label")
        
        # Pause delay slider (0-2000ms)
        self.pause_slider = ctk.CTkSlider(
            pause_frame,
            from_=0,
            to=2000,
            number_of_steps=40,
            command=self.on_pause_change,
            fg_color="#3a3a3a",
            progress_color="#4A90D9",
            button_color="#4A90D9",
            button_hover_color="#5BA0E9"
        )
        self.pause_slider.set(self.pause_delay)
        self.pause_slider.pack(side="left", fill="x", expand=True)
        self.pause_slider.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "pause_slider"))
        self.pause_slider.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "pause_slider"))
        self.pause_slider.bind("<ButtonRelease-1>", lambda e: self.on_pause_slider_release(e))
        debug_log("UI_ENHANCED", "Created pause delay slider")
        
        # Shortcuts button
        shortcuts_btn = ctk.CTkButton(
            pause_frame,
            text="⌨",
            width=30,
            height=28,
            font=("Segoe UI", 14),
            fg_color="#3a3a3a",
            hover_color="#4a4a4a",
            command=self._show_shortcuts
        )
        shortcuts_btn.pack(side="right", padx=(10, 0))
        shortcuts_btn.bind("<Enter>", lambda e: self.on_mouse_enter_widget(e, "shortcuts_btn"))
        shortcuts_btn.bind("<Leave>", lambda e: self.on_mouse_leave_widget(e, "shortcuts_btn"))
        debug_log("UI_ENHANCED", "Created shortcuts button")
        
        # Draw initial ready state
        self.draw_word_on_canvas("Ready", -1)
        
        debug_log("UI_ENHANCED", "All enhanced UI elements created successfully")
    
    def on_canvas_resize(self, event):
        """Handle canvas resize"""
        debug_log("CANVAS_RESIZE", "Canvas resized", {
            "width": event.width,
            "height": event.height
        })
        # Redraw current word if playing
        if hasattr(self, '_current_display_word'):
            self.draw_word_on_canvas(self._current_display_word, self._current_fixation_index)
    
    def draw_word_on_canvas(self, word: str, fixation_index: int):
        """Draw word on canvas with surrounding context words at reduced opacity"""
        debug_log("CANVAS_DRAW", f"Drawing word on canvas: '{word}'", {
            "fixation_index": fixation_index
        })
        
        self._current_display_word = word
        self._current_fixation_index = fixation_index
        
        self.word_canvas.delete("all")
        
        canvas_width = self.word_canvas.winfo_width()
        canvas_height = self.word_canvas.winfo_height()
        
        # Default size if not yet rendered
        if canvas_width < 10:
            canvas_width = 500
        if canvas_height < 10:
            canvas_height = 200
        
        font_name = "Comic Sans MS"
        main_font_size = 48
        context_font_size = 32  # Smaller font for surrounding words
        y_center = canvas_height // 2
        canvas_center_x = canvas_width // 2
        
        # Colors for context words (65% opacity on dark background #1a1a1a)
        # White at 65% on #1a1a1a ≈ #b3b3b3, but we'll use a slightly dimmer shade
        context_color = "#a6a6a6"  # ~65% white
        context_fixation_color = "#a64700"  # ~65% of orange #FF6B00
        
        # Get surrounding words from formatted_words if available
        context_words_before = []
        context_words_after = []
        
        if hasattr(self, 'formatted_words') and self.formatted_words and hasattr(self, 'current_word_index'):
            idx = self.current_word_index
            # Get up to 2 words before and after
            for i in range(max(0, idx - 2), idx):
                context_words_before.append(self.formatted_words[i][0])
            for i in range(idx + 1, min(len(self.formatted_words), idx + 3)):
                context_words_after.append(self.formatted_words[i][0])
        
        # Helper function to measure word width
        def measure_word(text, font_size):
            total = 0
            for char in text:
                temp_id = self.word_canvas.create_text(0, 0, text=char, font=(font_name, font_size, "bold"))
                bbox = self.word_canvas.bbox(temp_id)
                if bbox:
                    total += bbox[2] - bbox[0]
                else:
                    total += font_size // 2
                self.word_canvas.delete(temp_id)
            return total
        
        # Measure main word
        main_word_width = measure_word(word, main_font_size)
        
        # Calculate main word position (centered with fixation point alignment)
        main_char_widths = []
        for char in word:
            temp_id = self.word_canvas.create_text(0, 0, text=char, font=(font_name, main_font_size, "bold"))
            bbox = self.word_canvas.bbox(temp_id)
            if bbox:
                main_char_widths.append(bbox[2] - bbox[0])
            else:
                main_char_widths.append(main_font_size // 2)
            self.word_canvas.delete(temp_id)
        
        if 0 <= fixation_index < len(word):
            width_before_fixation = sum(main_char_widths[:fixation_index])
            fixation_char_half = main_char_widths[fixation_index] // 2 if fixation_index < len(main_char_widths) else main_font_size // 4
            main_x_start = canvas_center_x - width_before_fixation - fixation_char_half
        else:
            main_x_start = canvas_center_x - main_word_width // 2
        
        # Draw context words BEFORE main word
        spacing = 25  # Space between words
        x_pos = main_x_start - spacing
        
        for ctx_word in reversed(context_words_before):
            ctx_width = measure_word(ctx_word, context_font_size)
            x_pos -= ctx_width
            
            # Draw each character of context word
            char_x = x_pos
            ctx_fixation = get_fixation_point(ctx_word)
            for i, char in enumerate(ctx_word):
                color = context_fixation_color if i == ctx_fixation else context_color
                self.word_canvas.create_text(
                    char_x, y_center,
                    text=char,
                    font=(font_name, context_font_size, "bold"),
                    fill=color,
                    anchor="w"
                )
                # Measure this char width
                temp_id = self.word_canvas.create_text(0, 0, text=char, font=(font_name, context_font_size, "bold"))
                bbox = self.word_canvas.bbox(temp_id)
                char_x += (bbox[2] - bbox[0]) if bbox else context_font_size // 2
                self.word_canvas.delete(temp_id)
            
            x_pos -= spacing
        
        # Draw MAIN word (full brightness)
        x_pos = main_x_start
        for i, char in enumerate(word):
            color = "#FF6B00" if i == fixation_index else "white"
            self.word_canvas.create_text(
                x_pos, y_center,
                text=char,
                font=(font_name, main_font_size, "bold"),
                fill=color,
                anchor="w"
            )
            x_pos += main_char_widths[i] if i < len(main_char_widths) else main_font_size // 2
        
        # Draw context words AFTER main word
        x_pos = main_x_start + main_word_width + spacing
        
        for ctx_word in context_words_after:
            ctx_fixation = get_fixation_point(ctx_word)
            char_x = x_pos
            
            for i, char in enumerate(ctx_word):
                color = context_fixation_color if i == ctx_fixation else context_color
                self.word_canvas.create_text(
                    char_x, y_center,
                    text=char,
                    font=(font_name, context_font_size, "bold"),
                    fill=color,
                    anchor="w"
                )
                # Measure this char width
                temp_id = self.word_canvas.create_text(0, 0, text=char, font=(font_name, context_font_size, "bold"))
                bbox = self.word_canvas.bbox(temp_id)
                char_x += (bbox[2] - bbox[0]) if bbox else context_font_size // 2
                self.word_canvas.delete(temp_id)
            
            x_pos = char_x + spacing
        
        # Draw fixation line marker above the main word's fixation point
        if 0 <= fixation_index < len(word):
            self.word_canvas.create_line(
                canvas_center_x, y_center - 40,
                canvas_center_x, y_center - 30,
                fill="#FF6B00",
                width=2
            )
        
        debug_log("CANVAS_DRAW", "Word drawn with context", {
            "canvas_width": canvas_width,
            "words_before": len(context_words_before),
            "words_after": len(context_words_after)
        })
    
    def display_word(self, word: str):
        """Display a word with fixation point highlighting using Canvas"""
        debug_log("WORD_RENDER", f"Rendering word on canvas: '{word}'")
        
        fixation_index = get_fixation_point(word)
        self.draw_word_on_canvas(word, fixation_index)
    
    def show_window(self):
        """Show the Spreeder window and load clipboard"""
        debug_log("WINDOW_SHOW", "Showing window (enhanced)")
        
        # Reset quick answer mode (we're in normal clipboard mode now)
        self.quick_answer_mode = False
        self.quick_answer = ""
        
        # Reset simplified explanation state (new text = new explanations needed)
        self.simplified_explanations = []
        self.current_explanation_index = 0
        self.simplify_source_text = ""
        
        # Reset text view mode to serial reader
        self.full_text_view_mode = False
        
        # Read clipboard
        try:
            self.current_text = pyperclip.paste()
            debug_log("CLIPBOARD", "Clipboard read successfully", {
                "text_length": len(self.current_text),
                "text_preview": self.current_text[:100] + "..." if len(self.current_text) > 100 else self.current_text
            })
        except Exception as e:
            debug_log("CLIPBOARD_ERROR", f"Failed to read clipboard: {str(e)}")
            self.current_text = "Error reading clipboard"
        
        # Parse words
        self.words = self.current_text.split()
        self.current_word_index = 0
        debug_log("TEXT_PARSE", f"Parsed {len(self.words)} words from clipboard")
        
        # Reset UI state
        try:
            self.word_label.pack_forget()  # Hide base class label if visible
        except:
            pass
        self.word_canvas.pack(fill="both", expand=True)
        self.summary_text.pack_forget()
        self.draw_word_on_canvas("Ready", -1)
        self.status_label.configure(text="Press SPACE to start | CTRL+ALT+SPACE for full text | F3 to close")
        
        # Check if clipboard is the same as before - use cached summary
        if self.current_text == self.last_clipboard_text and self.cached_summary:
            debug_log("SUMMARY_CACHE", "Using cached summary (clipboard unchanged)", {
                "cached_length": len(self.cached_summary)
            })
            self.summary = self.cached_summary
            self.summary_ready = True
        else:
            # Don't auto-generate summary - wait for Shift+Space
            self.summary_ready = False
            self.summary = ""
            if self.current_text.strip():
                debug_log("SUMMARY_STATE", "Summary will generate on Shift+Space")
                self.last_clipboard_text = self.current_text  # Store for cache comparison
        
        # Show window
        self.window.deiconify()
        self.window.focus_force()
        self.is_visible = True
        
        # Reset progress bar
        if self.progress_bar:
            self.progress_bar.set(0)
        if self.progress_label:
            self.progress_label.configure(text=f"0/{len(self.words)}")
        
        # Reset pause state
        self.is_paused = False
        self.formatted_words = []
        
        debug_log("WINDOW_SHOW", "Window is now visible")
    
    def on_progress_bar_click(self, event):
        """Handle click on progress bar to seek to position"""
        if not self.formatted_words:
            debug_log("PROGRESS_CLICK", "No words loaded, ignoring click")
            return
        
        # Calculate the position based on click location
        bar_width = self.progress_bar.winfo_width()
        click_x = event.x
        progress = max(0, min(1, click_x / bar_width))
        new_index = int(progress * len(self.formatted_words))
        new_index = max(0, min(new_index, len(self.formatted_words) - 1))
        
        debug_log("PROGRESS_CLICK", "Progress bar clicked", {
            "click_x": click_x,
            "bar_width": bar_width,
            "progress": progress,
            "new_index": new_index
        })
        
        # Update position
        self.current_word_index = new_index
        
        # If playing, pause first
        if self.is_playing:
            self.is_paused = True
            self.stop_playback = True
            self.status_label.configure(text="PAUSED - Use ← → arrows to navigate | SPACE to resume")
        
        # Display the word at new position
        word, _, _ = self.formatted_words[self.current_word_index]
        self.display_word(word)
        self.update_progress_bar()
    
    def display_summary(self):
        """Display the summary in the UI"""
        debug_log("SUMMARY_DISPLAY", "Displaying summary (enhanced)", {
            "quick_answer_mode": getattr(self, 'quick_answer_mode', False)
        })
        
        # If in quick answer mode, show the quick answer instead of summary
        if getattr(self, 'quick_answer_mode', False):
            debug_log("SUMMARY_DISPLAY", "Quick answer mode - showing full answer")
            self._show_answer(self.quick_answer)
            return
        
        # Hide canvas and word label, show summary text
        try:
            self.word_label.pack_forget()  # Hide base class label if visible
        except:
            pass
        self.word_canvas.pack_forget()
        self.summary_text.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Clear and insert summary
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", self.summary)
        self._apply_markdown_formatting(self.summary_text)
        
        # Add note button if not already present
        if not hasattr(self, 'note_button_frame') or not self.note_button_frame.winfo_exists():
            self.note_button_frame = ctk.CTkFrame(self.window)
            self.note_button_frame.pack(side="bottom", pady=5)
            
            self.note_button = ctk.CTkButton(
                self.note_button_frame,
                text="📝",
                width=50,
                height=35,
                font=("Segoe UI Emoji", 18),
                command=self.on_save_note,
                fg_color="#2b2b2b",
                hover_color="#3b3b3b"
            )
            self.note_button.pack(side="left", padx=5)
            
            self.clarify_button = ctk.CTkButton(
                self.note_button_frame,
                text="❓",
                width=50,
                height=35,
                font=("Segoe UI Emoji", 18),
                command=self._show_clarify_prompt,
                fg_color="#2b2b2b",
                hover_color="#3b3b3b"
            )
            self.clarify_button.pack(side="left", padx=5)
        
        self.status_label.configure(text="Press ENTER or SPACE to close | Ctrl+Alt+N to save note")
        debug_log("SUMMARY_DISPLAY", "Summary displayed", {"summary": self.summary})
    
    def _show_answer(self, answer: str):
        """Display the answer in the main window (enhanced version)"""
        debug_log("QUICK_QUESTION", "Displaying answer (enhanced)", {"answer_length": len(answer)})
        
        # Clear quick answer mode flag
        self.quick_answer_mode = False
        
        # Hide canvas and word label, show summary text area
        try:
            self.word_label.pack_forget()  # Hide base class label if visible
        except:
            pass
        self.word_canvas.pack_forget()
        self.summary_text.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Display the answer
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", answer)
        self._apply_markdown_formatting(self.summary_text)
        self.summary_text.configure(state="disabled")
        
        # Add note button if not already present
        if not hasattr(self, 'note_button_frame') or not self.note_button_frame.winfo_exists():
            self.note_button_frame = ctk.CTkFrame(self.window)
            self.note_button_frame.pack(side="bottom", pady=5)
            
            self.note_button = ctk.CTkButton(
                self.note_button_frame,
                text="📝",
                width=50,
                height=35,
                font=("Segoe UI Emoji", 18),
                command=self.on_save_note,
                fg_color="#2b2b2b",
                hover_color="#3b3b3b"
            )
            self.note_button.pack(side="left", padx=5)
            
            self.clarify_button = ctk.CTkButton(
                self.note_button_frame,
                text="❓",
                width=50,
                height=35,
                font=("Segoe UI Emoji", 18),
                command=self._show_clarify_prompt,
                fg_color="#2b2b2b",
                hover_color="#3b3b3b"
            )
            self.clarify_button.pack(side="left", padx=5)
        
        self.status_label.configure(text="Press SPACE or ENTER to close | Ctrl+Alt+N to save note")
    
    def _prepare_serial_answer(self, answer: str):
        """Prepare answer for serial reading mode (enhanced version)"""
        debug_log("QUICK_QUESTION", "Preparing answer for serial reading (enhanced)", {"answer_length": len(answer)})
        
        # Store the answer for display after playback
        self.quick_answer = answer
        self.quick_answer_mode = True
        
        # Set up the text for serial reading (like clipboard text)
        self.current_text = answer
        self.words = self.current_text.split()
        self.current_word_index = 0
        
        # Reset playback state
        self.is_playing = False
        self.is_paused = False
        self.stop_playback = False
        
        # Show ready state
        self.word_canvas.pack(fill="both", expand=True)
        self.summary_text.pack_forget()
        self.draw_word_on_canvas("Ready", -1)
        self.status_label.configure(text="Press SPACE to read | ENTER to skip to full answer")
        
        # Update progress bar
        if hasattr(self, 'progress_bar') and self.progress_bar:
            self.progress_bar.set(0)
        if hasattr(self, 'progress_label') and self.progress_label:
            self.progress_label.configure(text=f"0 / {len(self.words)} words")
        
        debug_log("QUICK_QUESTION", f"Serial answer ready with {len(self.words)} words (enhanced)")

    def _show_window_minimal(self):
        """Show the window without reading clipboard - for hyperstudy mode (enhanced)"""
        debug_log("WINDOW_SHOW_MINIMAL", "Showing window (minimal, no clipboard) - enhanced")
        
        # Reset UI state without touching current_text
        self.word_canvas.pack(fill="both", expand=True)
        self.summary_text.pack_forget()
        
        # Show window
        self.window.deiconify()
        self.window.focus_force()
        self.is_visible = True
        debug_log("WINDOW_SHOW_MINIMAL", "Window is now visible (minimal, enhanced)")

    def show_summary_immediately(self):
        """Show summary immediately (Shift+F3 behavior)"""
        debug_log("SUMMARY_IMMEDIATE", "Showing summary immediately (enhanced)")
        
        # Stop any playback
        self.stop_playback = True
        self.is_playing = False
        
        # If summary not ready, start generation now
        if not self.summary_ready:
            debug_log("SUMMARY_IMMEDIATE", "Summary not ready, starting generation")
            self.draw_word_on_canvas("Generating...", -1)
            
            # Start summary thread if not already running
            if not (self.summary_thread and self.summary_thread.is_alive()):
                debug_log("SUMMARY_IMMEDIATE", "Starting summary thread")
                self.summary_thread = threading.Thread(target=self.generate_summary_async, daemon=True)
                self.summary_thread.start()
            
            # Wait for summary thread to complete
            if self.summary_thread and self.summary_thread.is_alive():
                debug_log("SUMMARY_IMMEDIATE", "Waiting for summary thread to complete")
                self.summary_thread.join(timeout=30)
        
        # Show summary
        self.display_summary()


# ==================== SYSTEM TRAY SUPPORT ====================

def create_tray_icon_image(size=64):
    """Create a simple tray icon image programmatically"""
    # Create an orange "K" icon
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Draw orange circle background
    margin = 2
    draw.ellipse([margin, margin, size-margin, size-margin], fill='#FF6B00')
    
    # Draw "K" letter in white (simple approximation)
    # Since we may not have fonts, draw a simple K shape
    cx, cy = size // 2, size // 2
    r = size // 3
    # Vertical line of K
    draw.line([(cx - r//2, cy - r), (cx - r//2, cy + r)], fill='white', width=3)
    # Diagonal lines of K
    draw.line([(cx - r//2, cy), (cx + r//2, cy - r)], fill='white', width=3)
    draw.line([(cx - r//2, cy), (cx + r//2, cy + r)], fill='white', width=3)
    
    return image


class TrayManager:
    """Manages the system tray icon and menu"""
    
    def __init__(self, app):
        self.app = app
        self.icon = None
        self._running = True
        
    def create_menu(self):
        """Create the tray icon menu"""
        return pystray.Menu(
            pystray.MenuItem("Show Window (F3)", self.on_show_window, default=True),
            pystray.MenuItem("Strategy Analysis (Ctrl+Shift+A)", self.on_strategy_analysis),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self.on_exit)
        )
    
    def on_show_window(self, icon, item):
        """Show the main Spreeder window"""
        if self.app and self.app.window:
            self.app.window.after(0, lambda: self._show_window())
    
    def _show_window(self):
        """Show window on main thread"""
        try:
            if hasattr(self.app, '_toggle_window'):
                self.app._toggle_window(shift_held=False)
            else:
                self.app.window.deiconify()
                self.app.window.focus_force()
        except Exception as e:
            debug_log("TRAY_ERROR", f"Failed to show window: {e}")
    
    def on_strategy_analysis(self, icon, item):
        """Open the Strategy Analysis window"""
        if self.app and self.app.window:
            self.app.window.after(0, self.app.open_strategy_analysis_window)
    
    def on_exit(self, icon, item):
        """Exit the application completely"""
        debug_log("TRAY", "Exit requested from tray menu")
        self._running = False
        if self.icon:
            self.icon.stop()
        if self.app and self.app.window:
            self.app.window.after(0, self._quit_app)
    
    def _quit_app(self):
        """Quit on main thread"""
        try:
            keyboard.unhook_all()
        except:
            pass
        if self.app and self.app.window:
            self.app.window.quit()
            self.app.window.destroy()
        os._exit(0)
    
    def run(self):
        """Run the tray icon (call from separate thread)"""
        try:
            image = create_tray_icon_image()
            menu = self.create_menu()
            
            self.icon = pystray.Icon(
                "KISS",
                image,
                "KISS - Press F3 to activate\nCtrl+Shift+A for Strategy Analysis",
                menu
            )
            
            debug_log("TRAY", "System tray icon started")
            self.icon.run()
        except Exception as e:
            debug_log("TRAY_ERROR", f"Failed to run tray icon: {e}")


def run_with_tray():
    """Run the application with system tray support"""
    log_startup()
    
    debug_log("MAIN", "Creating EnhancedSpreederApp instance")
    app = EnhancedSpreederApp()
    
    if TRAY_AVAILABLE:
        debug_log("MAIN", "Setting up system tray icon")
        tray = TrayManager(app)
        
        # Run tray icon in background thread
        tray_thread = threading.Thread(target=tray.run, daemon=True)
        tray_thread.start()
        
        print("KISS is running in the background.")
        print("  - Press F3 to open the speed reader")
        print("  - Press Ctrl+Shift+A for AI Strategy Analysis")
        print("  - Right-click the tray icon (orange K) to access menu")
        print("  - Or click Exit in tray menu to quit")
    else:
        print("Running without system tray (install pystray for tray icon)")
    
    debug_log("MAIN", "Starting application main loop")
    app.run()


# ==================== ENTRY POINT ====================

if __name__ == "__main__":
    # Handle PyInstaller frozen executable
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        application_path = os.path.dirname(sys.executable)
        os.chdir(application_path)  # Set working directory to exe location
    
    run_with_tray()
