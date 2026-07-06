# Figma Plugin Importer Runbook

## Overview
The Sellform Figma Plugin allows editors to import structured landing page designs into a Figma canvas directly using single-use ticket codes or fallback JSON packages. This document describes the local setup, build instructions, test procedures, and troubleshooting guidelines.

---

## 1. Directory Structure
```
integrations/figma-plugin/
├── dist/                          # Compiled artifacts (code.js, ui.html)
├── src/
│   ├── code.ts                    # Main thread controller
│   ├── ui.html                    # Plugin iframe HTML template
│   ├── ui.ts                      # Client UI thread and endpoints fetching
│   ├── contracts.ts               # Payload interface definitions
│   └── payload-validator.ts       # Validation rules
├── scripts/
│   ├── configure-manifest.mjs     # Interactive manifest generator
│   └── configure-manifest.test.mjs
└── package.json
```

---

## 2. Setup & Configuration

### Step 0: Configure the backend secret

Add a unique random value of at least 32 characters to the root `.env`.

```dotenv
SELLFORM_FIGMA_PLUGIN_TICKET_SECRET=<at-least-32-random-characters>
SELLFORM_FIGMA_PLUGIN_TICKET_TTL_SECONDS=600
SELLFORM_FIGMA_PLUGIN_SESSION_TTL_SECONDS=600
SELLFORM_FIGMA_PLUGIN_PACKAGE_MAX_BYTES=20971520
```

The backend returns `503` for plugin ticket operations when the secret is
missing or too short. Never commit the real secret.

### Step A: Configure Manifest with Plugin ID
Before running or building the plugin, you must configure the `manifest.json` file using your numeric Figma Plugin ID:
```cmd
cd integrations/figma-plugin
npm.cmd run configure -- <figma_plugin_id>
```
If run without an argument, the script will run interactively and prompt you for the ID.

### Step B: Build Compiled Bundles
To compile TypeScript files and compile/inline the UI script into the single `ui.html` required by Figma:
```cmd
npm.cmd run build
```
This output is saved to the `dist/` directory.

### Step C: Load the Plugin in Figma Desktop
1. Open **Figma Desktop app**.
2. Click **Plugins** -> **Development** -> **New Plugin...** -> **Import plugin from manifest...**.
3. Choose the generated `integrations/figma-plugin/manifest.json`.
4. Click Open. The plugin is now loaded in your development environment.

---

## 3. Running Automated Tests
To run Jest unit tests for the validator, renderer, and code configuration:
```cmd
npm.cmd test
```

---

## 4. Troubleshooting & Error Codes

### backend API Errors
- **`404 Project Not Found`**: The requested project does not exist or does not belong to the user's current workspace.
- **`409 Page Draft Not Found`**: The project does not have a page draft generated yet. Generate a draft via the editor UI first.
- **`410 Ticket Expired`**: The ticket code has passed its 10-minute expiration window. Generate a new ticket code in the editor UI.
- **`413 Payload Too Large`**: The JSON fallback package exceeds the 20MB asset limit. Use the code redemption path instead.

### Plugin UI Errors
- **`IMAGE_PLACEHOLDER_USED`**: Emitted as a warning when a specific image asset failes to download or is not present in the backend. The renderer draws a gray box placeholder so layout flow is not disrupted.
- **`UNSUPPORTED_SCHEMA_VERSION`**: The imported package version is not `1.0`. Verify that the Sellform backend is running the correct sprint package version.
- **`INVALID_CUT_COUNT`**: The page draft does not contain the canonical seven sections. Regenerate the page structure before issuing a new code.
- **`429 Too Many Requests`**: Ten invalid codes were submitted in five minutes. Wait for the window to expire.
- **`503 Ticket Secret Missing`**: Configure `SELLFORM_FIGMA_PLUGIN_TICKET_SECRET` and restart the backend.

---

## 5. Manual Figma QA

1. Generate a code from Sellform's `Figma 플러그인으로 내보내기` dialog.
2. Open a blank Figma Design file and run the local Sellform plugin.
3. Paste the code and select `가져오기 및 그리기`.
4. Confirm one 860px root frame and exactly seven editable section frames.
5. Confirm text nodes can be edited and available images use Figma Image Fill.
6. Confirm a missing image creates only a placeholder warning.
7. Reuse the same code and confirm it is rejected.
8. Save a screenshot in the Sprint 34 test evidence document.
