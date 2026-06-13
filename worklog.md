---
Task ID: 1
Agent: Main Agent
Task: Fix GitHub upload + ENDICT dictionary upgrade + H5 loading bug fix

Work Log:
- Identified wrong repo at /home/z/my-project/ was pushed to GitHub (had backend_extracted, download, skills, .env)
- Actual Phonos project at /home/z/my-project/download/Phonos/ with proper code
- Downloaded ENDICT data from ismartcoding/endict (3M+ entries)
- Filtered to 50K common words with IPA data (14MB common.json) and 1.28M full dictionary (136MB full_dict.json)
- Updated dict_service.py to use two-tier loading (common first, full on demand)
- Fixed H5 "EASY Loading..." bug: changed init() to show proper loading state, added timeout protection
- Fixed HTML defaults: diffBadge from "EASY" to "...", sentenceEn from "Loading..." to "加载中..."
- Fixed refresh button: forceNew mode now uses timestamp to prevent cache, ensures different sentence
- Fixed IPA display: compact formatting (smaller padding, tighter letter-spacing, smaller line-height)
- Updated .gitignore to exclude full_dict.json (136MB too large for GitHub)
- Updated README.md with ENDICT info, corrected project structure
- Force-pushed correct Phonos code to GitHub, overwriting the wrong upload
- Removed remote from wrong /home/z/my-project/ repo to prevent future mistakes

Stage Summary:
- GitHub repo now has correct Phonos project code (3 commits of history preserved)
- ENDICT: common.json (50K words, 14MB) in repo, full_dict.json (1.28M words, 136MB) excluded but supported
- H5 loading: proper loading states, timeout protection, no more "EASY Loading..." stuck state
- Refresh button: now properly loads a different sentence each time

---
Task ID: 2
Agent: Main Agent
Task: Add multi-user system with personalized learning to Phonos

Work Log:
- Analyzed existing codebase: FastAPI backend + vanilla JS frontend + SQLite FSRS database
- Designed multi-user architecture with backward compatibility (default user)
- Created auth_service.py: User registration, login, session tokens, password hashing
- Created learning_algorithm.py: Weakness analysis, adaptive difficulty, recommendations, analytics
- Modified fsrs_db.py: Added user_id to all tables and queries with migration logic
- Modified main.py: Added auth endpoints, learning endpoints, user context on all API routes
- Modified index.html: Added auth modal (login/register/switcher), user profile in header
- Modified style.css: Added auth styles, user profile styles, enhanced stats styles
- Modified app.js: Added auth state, fetchWithAuth, login/register/guest flow, server analytics integration, enhanced stats with personalization

Stage Summary:
- New files: auth_service.py, learning_algorithm.py
- Modified files: main.py, fsrs_db.py, index.html, style.css, app.js
- Key features implemented:
  1. Multi-user authentication (register, login, guest, user switching)
  2. Per-user FSRS cards and review logs
  3. Per-user evaluation tracking (user_evaluations, user_word_progress, user_phoneme_stats)
  4. Weakness analysis with phoneme error rates
  5. Adaptive difficulty based on recent performance
  6. Targeted sentence recommendations
  7. Learning analytics (streak, improvement rate, daily scores)
  8. FSRS parameter adjustment based on learning speed
  9. Enhanced statistics UI with greeting, heatmap, recommendations
  10. Backward compatibility: no token = default user

---
Task ID: 3
Agent: Main Agent
Task: Add dual learning mode (sequential/smart), word review, dictation error tracking, data change detection

Work Log:
- Analyzed user requirements: smart mode with FSRS integration, sequential mode with ID range, data change detection, word review, dictation error tracking
- Modified learning_algorithm.py:
  - Added sentences_count, start_id, end_id columns to user_sequential_position table
  - Added migration for existing databases
  - Changed get_sequential_position() to return dict instead of int
  - Added set_sequential_range() for ID range support
  - Added get_smart_recommendation_score() for FSRS+weakness combined scoring
  - Added get_sentences_hash() for change detection
- Modified main.py:
  - Enhanced /api/mode/sequential/next with start_id/end_id query params
  - Added data change detection (compares stored vs current sentence count)
  - Added POST /api/mode/sequential/set-range endpoint
  - Enhanced /api/mode/smart/next with scoring-based ranking
  - Enhanced /api/mode/status with data_changed, smart_mode_info
- Modified index.html:
  - Added learning mode selector (智能/顺序) in header
  - Added mode settings gear button for sequential ID range
  - Added data change notification banner
  - Added sequential mode ID range dialog modal
  - Added word review modal with card-based UI and FSRS rating buttons
- Modified style.css:
  - Mode selector pill toggle styles
  - Data change banner with slide-down animation
  - ID range dialog styles
  - Word review modal with word cards, error badges, rating grid
  - Responsive additions for mobile
- Modified app.js:
  - Added learningMode state, modeStatus, wordReviewQueue, wordReviewIndex states
  - Added loadLearningMode/saveLearningMode (localStorage persistence)
  - Modified loadSentence() to use mode-specific endpoints
  - Added data change detection with showDataChangeBanner()
  - Added openIdRangeDialog/confirmIdRange functions
  - Added openWordReview/submitWordReviewRating functions
  - Added recordDictationErrors() auto-called in checkDictation()
  - Enhanced evaluation recording with pronunciation error words
- Updated README.md with new features and API endpoints

Stage Summary:
- Dual learning mode: sequential (with ID range) + smart (FSRS+weakness scoring)
- Data change detection: auto-detects when sentence data is updated
- Word review: FSRS-driven review queue for error words
- Dictation error tracking: auto-records incorrect words on check
- Pronunciation error tracking: auto-records words with accuracy < 60%
- New API endpoints: POST /api/mode/sequential/set-range, enhanced sequential/smart/status
- All syntax checks pass (Python + JavaScript)

---
Task ID: dictation-v2
Agent: main
Task: 听写模式大小写标点不影响评分 + 双行对比批改 + 漏写/多写标签

Work Log:
- Added _normalize_word() to backend: lowercase + strip punctuation (keep apostrophes/hyphens)
- Updated dictation/check API: returns expected_original/actual_original for display, error_summary for statistics
- Updated words/dictation-practice API: uses _normalize_word() for comparison
- Changed scoring denominator from len(expected_words) to attempted_count (excludes omissions/additions)
- Rewrote checkDictation() with: double-line diff, wavy underlines, 漏写/多写 tags, error summary
- Rewrote submitDictationPractice() with same normalization and display improvements
- Added normalizeWord(), buildCharDiffForDisplay(), renderCharDiffLine() utility functions
- Added CSS styles for dict-char-err/miss/extra, dict-tag-omission/addition, dict-corrections, dict-error-summary
- Committed and pushed to GitHub

Stage Summary:
- Dictation now ignores case and punctuation in scoring
- Double-line comparison: red user input + green correct answer with wavy underlines
- Word-level 漏写 (blue tag) and 多写 (orange tag) labels
- Bottom summary: 拼写 X | 漏写 Y | 多写 Z
- Omission/addition don't affect score of other correctly-typed words
- Commit: 090d77e pushed to origin/main
