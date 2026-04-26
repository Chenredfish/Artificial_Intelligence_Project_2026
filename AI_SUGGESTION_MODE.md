AI Suggestion Mode with Auto-Apply Toggle
Feature Overview

This update enhances the AI interaction workflow by introducing a toggle-based execution mode for the Ask AI button.

Previously:

Ask AI → AI immediately executes the move

After this update:

Ask AI → either executes move automatically OR provides suggestion only

depending on the toggle state.

This improves usability and allows human players to evaluate AI recommendations before applying them.

Motivation

The original implementation forced AI moves to be executed immediately after inference:

Ask AI → automatic move execution

However, this behavior prevents:

manual verification of AI decisions
educational analysis of suggested moves
human–AI cooperative play

To address this limitation, a dual-mode system was introduced.

New Interaction Modes
Mode 1 — Auto Apply (Enabled)

Default behavior remains unchanged.

Workflow:

Ask AI
→ AI computes move
→ move applied automatically
→ board updated immediately

This mode is useful for:

fast gameplay
AI vs human matches
automated testing
Mode 2 — Suggestion Only (Disabled)

New behavior introduced.

Workflow:

Ask AI
→ AI computes move
→ suggestion displayed
→ suggested move highlighted on board
→ user confirms manually
→ move executed

This enables:

interactive analysis
move validation before execution
teaching demonstrations
debugging AI behavior
Backend Implementation

Modified:

src/app.py

Updated API:

POST /api/ask_ai

Now supports:

auto_apply = request.json.get("auto_apply", True)

Behavior:

auto_apply	Result
True	move executed immediately
False	suggestion returned only

Returned response structure:

{
  "ok": true,
  "suggestion_only": true,
  "from_pos": [r, c],
  "to_pos": [r, c],
  "move": "A:(3,3)-(3,4)"
}
New API Endpoint

Added:

POST /api/apply_ai_suggestion

Purpose:

Execute a previously suggested move after user confirmation.

Example request:

{
  "from_pos": [3,3],
  "to_pos": [3,4]
}
Frontend Implementation

Modified:

templates/index.html

Added components:

Auto Apply Toggle
<input type="checkbox" id="auto-ai-toggle">

Controls whether AI executes moves automatically.

Confirm AI Move Button
<button id="btn-confirm-ai">
Use AI Move
</button>

Enabled only when a suggestion exists.

Suggestion Display Panel
AI suggestion: A:(3,3)-(3,4)

Displays latest AI recommendation.

Board Highlighting Support

When suggestion-only mode is active:

Suggested move visually marked on board:

origin square → selected highlight
destination square → valid-move indicator

This improves readability and decision clarity.

JavaScript State Extension

Added new runtime variable:

pendingAiMove

Stores temporary AI suggestion:

{
    from_pos,
    to_pos,
    move
}

Used by:

Use AI Move button

to execute confirmed suggestion.

Compatibility with Existing System

This feature preserves backward compatibility.

Original behavior:

Ask AI → execute immediately

remains unchanged when:

Auto apply AI move = enabled

Therefore:

No existing functionality was removed.

User Experience Improvement

This update introduces a hybrid interaction model:

Mode	Description
Auto mode	fast automatic execution
Suggestion mode	manual confirmation workflow

Benefits:

supports beginner learning scenarios
enables AI debugging and evaluation
improves gameplay transparency
enhances demonstration capability during project presentations