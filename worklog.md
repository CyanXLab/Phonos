---
Task ID: 1
Agent: Main Agent
Task: Fix all bugs and add new features for Phonos platform

Work Log:
- Rewrote dictation scoring backend (main.py): added _normalize_word(), _check_order_errors(), enhanced dictation_check endpoint
  - Fix: middle-empty input bug (empty positions no longer counted as correct)
  - Fix: ignore case/punctuation in comparison (_normalize_word strips non-alpha)
  - Added: 6 error types (match, order_error, substitution, partial, near_correct, deletion, insertion)
  - Added: order error detection (prevents random word arrangement scoring)
  - Added: detailed summary stats (spelling X | missed Y | extra Z | order W)
- Fixed 100% read wrong bug in error stats (main.py + learning_algorithm.py):
  - Changed: error rate uses max(total_attempts, error_count) instead of always 100%
  - Added: total_attempts to get_error_words() response
- Fixed FSRS card state display (app.js):
  - Changed: review badge logic to check FSRS state (LEARNING/REVIEW/RELEARNING) not just sentenceType
  - Old cards with state >= 1 now correctly show "复习" instead of "新句"
- Updated frontend dictation display (app.js):
  - Added: order_error CSS class (purple wavy underline)
  - Added: dict-error-summary showing detailed error breakdown
  - Added: user_index mapping for proper input-to-result alignment
- Fixed dark mode CSS (style.css):
  - Added: 89 comprehensive dark mode overrides at end of file (wins specificity)
  - Added: --bg2 CSS variable (used by practice tabs, buttons, etc.)
  - Covers: waveform, badges, tip cards, FSRS buttons, semantic tags, stats, heatmap, etc.
- Added translation & TTS priority settings (app.js + main.py):
  - Added: translation_priority selector (auto/local/online)
  - Added: translation_display selector (after/first)
  - Added: backend support for translation_display setting
- Added progress visualization (app.js):
  - Added: 4-card motivation section (mastered count, streak, improvement rate, weak words)
  - Added: deliberate practice suggestion with specific weak words
  - Added: switchErrorTab() for tabbed error stats view
- Updated README.md with all new features and API changes

Stage Summary:
- All high-priority bugs fixed
- All requested new features added
- Dark mode comprehensively covered
- README updated to match latest code
