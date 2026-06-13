# Task 1: FSRS-6 Algorithm Upgrade

## Summary
Successfully rewrote `/home/z/my-project/backend/fsrs_db.py` from FSRS-4.5 to FSRS-6.

## Key Changes

### Algorithm (18 → 21 params)
- **DECAY**: Constant `-0.5` → Learnable `-w[20]` (default `-0.1542`)
- **FACTOR**: Derived from `0.9^(1/DECAY) - 1` (default `0.9803`)
- **D0(G)**: Linear `w[4]-w[5]*(G-3)` → Exponential `clamp(w[4]-exp(w[5]*(G-1))+1, 1, 10)`
- **Forget Stability**: Added floor `min(s_recall, S/exp(w[17]*w[18]))`
- **Short-term Stability**: New same-day formula `S*exp(w[17]*(G-3+w[18]))*S^(-w[19])`
- **Retrievability**: `(1+FACTOR*t/S)^DECAY` with proper negative DECAY handling
- **Interval**: `(S/FACTOR)*(r^(1/DECAY)-1)` with fuzzing perturbation

### New Features
- Parameter fitting every 30 reviews (simplified gradient descent, no PyTorch)
- Per-user parameter storage (`user_fsrs_params` table)
- `learning_steps` / `relearning_steps` support
- Interval fuzzing to avoid clustering
- `review_duration` column in review_log

### New Methods
- `FSRSScheduler.get_retrievability(card, now)`
- `FSRSScheduler.get_next_interval_info(card, now)`
- `FSRSDatabase.get_user_params(user_id)`
- `FSRSDatabase.set_user_params(user_id, params_dict)`
- `FSRSDatabase.fit_params(user_id)`
- `FSRSDatabase.get_scheduler(user_id)`

### Backward Compatibility
- All existing method signatures preserved
- Existing DB schema migrations handled automatically
- Default `user_id='default'` works as before
- `get_fsrs_db()` singleton still works

## Test Results
All verification tests passed:
- 21 parameters validated
- Core formulas: R(interval) = 0.9 for all S values ✓
- DECAY = -0.1542, FACTOR = 0.9803 ✓
- Short-term stability, forgetting floor, fuzzing ✓
- DB CRUD, queue methods, statistics ✓
- User params, fitting, learning steps ✓
