---
Task ID: 1
Agent: Main Agent
Task: Fix Phonos word mastery statistics and related bugs

Work Log:
- Analyzed the Phonos codebase (FastAPI + vanilla JS frontend)
- Identified root cause: FSRS algorithm always set new cards to LEARNING state regardless of rating
- Fixed FSRS scheduler: Good/Easy ratings now transition to REVIEW state (mastered) instead of always LEARNING
- Fixed word card creation: all words in practiced sentences now get FSRS cards (not just error words)
- Fixed stats API: word_review_stats now merges FSRS data with learning DB data for accurate counts
- Fixed frontend stats display: masteredWords/allWeakWords now use FSRS mastery state
- Fixed sequential mode: fetchModeStatus() now awaited before loadSentence() to preserve start_id/end_id
- Fixed review count display: separate sentence/word due counts with correct labels
- All fixes verified with automated tests

Stage Summary:
- 6 bugs fixed in fsrs_db.py, main.py, and app.js
- Key fix: FSRS Good/Easy → REVIEW state (was: always LEARNING)
- Key fix: word cards created for all practiced sentence words (was: only error words)
- Key fix: sequential mode preserves ID range on page refresh
- Code saved to /home/z/my-project/download/Phonos/ and synced to all locations
- Server restart required for changes to take effect
