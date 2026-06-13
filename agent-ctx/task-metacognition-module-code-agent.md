# Task: Create Metacognition Module for Phonos

## Task ID: task-metacognition-module

## Summary
Created `/home/z/my-project/backend/metacognition.py` — a production-ready Python module implementing the "metacognition layer" for the Phonos project, teaching students "how to learn".

## Implementation Details

### 4 Core Subsystems

1. **Cognitive Mirror (认知镜像)** — Real-time user learning path profile
   - Classifies users into 5 archetypes: 囫囵吞枣型, 完美主义型, 稳健进步型, 高自信低准确型, 焦虑型
   - Computes 6 metrics: speed, retention, coverage, confidence_accuracy_gap, again_rate, easy_rate
   - Returns profile with archetype, metrics, description, strengths, weaknesses
   - 1-hour caching with force_refresh option

2. **Prediction Calibration (预测校准)** — For overconfident users
   - `record_prediction()` and `get_calibration_stats()` methods
   - Calibration score = 1 - mean(|predicted - actual| / 100)
   - Auto-detection for 高自信低准确型 users via `should_enable_calibration()`
   - Trend tracking (improving/stable/worsening)

3. **Strategy Recommendation (策略推荐)** — Based on cognitive profile
   - 5 strategies per archetype with specific actionable advice
   - FSRS parameter adjustments (desired_retention, new_per_day, learning_steps, etc.)
   - `apply_param_adjustments()` to auto-apply recommended changes
   - Strategy history tracking

4. **Learning Session Quality (学习质量评估)**
   - `record_session()` and `get_session_quality()` methods
   - Zombie learning detection (consecutive Again, ultra-short review intervals, mechanical patterns)
   - Quality score = base_score × engagement × effectiveness × focus factors
   - Personalized feedback generation

### DB Tables (at `phonos_metacognition.db`)
- `cognitive_profiles` — user archetype + metrics
- `prediction_calibrations` — predicted vs actual scores
- `learning_sessions` — per-session metrics + quality score
- `strategy_history` — strategies recommended over time

### Design Decisions
- Lazy imports for `fsrs_db` and `learning_algorithm` to avoid circular dependencies
- Graceful error handling: all external data queries wrapped in try/except
- Chinese documentation throughout
- Singleton pattern via `get_metacognition()`
- Comprehensive threshold-based archetype classification with priority ordering

### Test Results
- All 4 subsystems verified functional
- Zombie learning correctly detected
- Calibration tracking working
- Strategy recommendations context-appropriate
- DB creation and persistence working
