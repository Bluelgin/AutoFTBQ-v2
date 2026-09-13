# Studio UX polish

This document describes the product-layer UX shell introduced by `autoftbq_v2/ux_polish.py`.
The shell intentionally wraps the existing editor instead of replacing editing, Agent, bridge,
persistence, or validation logic.

## User-facing changes

- First-run start page with continue, open, new project, Minecraft connection guidance, and AI setup.
- Basic mode is the default. It keeps common task/chapter editing, validation, and Agent features visible while hiding taskbook-wide advanced fields and raw SNBT.
- Advanced mode restores the complete taskbook and expert editing surface and is remembered between launches.
- Canvas toolbar keeps the high-frequency actions visible and moves zoom/fit/copy/paste/delete into a `More` menu. Existing keyboard shortcuts still work.
- Right-clicking a quest exposes Agent context selection directly, while `Alt + click` remains available as the fast path.
- `Ctrl+K` opens a searchable command palette for less-frequent actions.
- AI setup keeps provider, key, model, and local/cloud selection prominent. Endpoint, reasoning effort, and image capability are collapsed under advanced settings unless a custom provider needs them.
- A lightweight run marker detects likely abnormal termination. On the next graphical launch the Studio explains that the workspace was recovered and offers the log folder.

## Manual acceptance checklist

1. Clean first launch opens the welcome page and does not immediately force the AI setup dialog.
2. Creating a new project or continuing a restored workspace enters the normal editor.
3. Basic mode shows `Task`, `Chapter`, and `Check`; taskbook-wide settings, raw SNBT, and display/progression fields are hidden.
4. Switching to advanced mode restores all original v2 editor tabs without losing the current selection.
5. `Check taskbook` remains usable in basic mode.
6. The canvas still supports `Ctrl+C`, `Ctrl+V`, `Delete`, zoom, fit, undo/redo, add task, and connection mode.
7. Right-click a quest and choose `Let Agent focus on this quest`; the Agent context label updates, and selecting the action again removes it.
8. `Ctrl+K` can launch validation, modpack scan, AI setup, fit canvas, new/open project, and mode switching.
9. Normal AI providers start with advanced connection fields collapsed; choosing a custom provider expands the endpoint field path.
10. Force-close the process after a workspace autosave, relaunch, and confirm the recovery notice appears while the workspace content is restored.
11. Connect the Minecraft Agent Mod and confirm the existing game-backend mode still takes precedence over the welcome/editor pages.
12. Run `python v2_main.py --smoke-test` and the full unittest suite before release packaging.
