# Prompt log

1. **Request:** “Use Tkinter.”  
   **Changes:** Added a Tkinter desktop application in `app.py` alongside the existing browser version, using the project specification for its basin, gage, detail, and hydrograph behavior.  
   **Outcome:** `python -m py_compile app.py` passed. The first launch exposed a callback error while reporting a live-data failure; the exception-capture bug was fixed. A subsequent launch remained open without console output during the observation period, but was stopped without confirming the live services or visually checking the interface. Live-data and calculation validation are still outstanding.

2. **Request:** Add `prompts.md` with an entry for each request, following the linked `AGENTS.md` instruction, and add a `README.md` explaining installation and how to run the app; read and correct the log before submission.  
   **Changes:** Added this prompt log, top-level `AGENTS.md` with the required standing instruction, and `README.md` with Python/Tkinter requirements, Windows time-zone-data guidance, network requirements, and launch instructions.  
   **Outcome:** The request log was reviewed against the conversation and records the limited verification honestly. Documentation has not been tested as an application run guide.

3. **Request:** Implement the two new features in `spec.md`. After clarification, save/open should preserve session settings and the selected gage, reopening should refresh live data, and exports should support both CSV and Excel.  
   **Changes:** Added `.brwork.json` save/open controls for the selected gage, search text, and historical setting; added CSV and `.xlsx` export actions with missing values left blank; documented the behavior and added the `openpyxl` dependency and focused tests.  
   **Outcome:** All four focused tests passed, including CSV/Excel missing-value checks and work-file validation. `python -m py_compile app.py` passed. Live USGS refresh and interactive GUI operation were not verified.

4. **Request:** Verify the two handwritten validations and document them, then assess UI proportions in a table. Clarification identified the second handwritten calculation as a duplicate of the first and set the target as the Tkinter app at 1500 × 900.  
   **Changes:** Added a directly tested daily-series summary helper and a regression test for the 12, missing, 18, and 30 cfs calculation. Added the two numbered calculation entries and a table of Tkinter layout ratios and verification status to `spec.md`.  
   **Outcome:** All five focused tests and Python syntax checks passed. The duplicate yields the same 20.0 cfs mean, 3 valid values, and 1 missing day, but is not an independent test. Grid ratios and map/chart scaling were checked from the source; a stable window was not available for visual fit verification, and live-data validation remains pending.

5. **Request:** Add a Platform section to `spec.md`.  
   **Changes:** Documented the Windows desktop target, Python/Tkinter runtime, live-data internet requirement, and `openpyxl` requirement for Excel export.  
   **Outcome:** Section added; documentation-only change.
