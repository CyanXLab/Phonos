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
