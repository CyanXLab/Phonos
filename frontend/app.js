/**
 * Phonos 口语练习平台 - 前端逻辑
 *
 * 功能：句子获取(FSRS队列)、TTS(浏览器+服务端回退)、IPA点击发音(标准IPA音频)、
 *       听写模式(倍速播放)、录音+波形可视化、回放、评测、评分展示、音素对比、
 *       错误诊断、单词学习、FSRS评级、学习统计、音素指南
 */

const API = '';

// ============================================================
// ARPAbet → IPA mapping
// ============================================================
const ARPABET_TO_IPA = {
    'AA':'ɑ','AE':'æ','AH':'ʌ','AO':'ɔ','AW':'aʊ','AY':'aɪ',
    'EH':'ɛ','ER':'ɝ','EY':'eɪ','IH':'ɪ','IY':'i','OW':'oʊ',
    'OY':'ɔɪ','UH':'ʊ','UW':'u',
    'P':'p','B':'b','T':'t','D':'d','K':'k','G':'ɡ',
    'F':'f','V':'v','S':'s','Z':'z','SH':'ʃ','ZH':'ʒ','TH':'θ','DH':'ð',
    'CH':'tʃ','JH':'dʒ',
    'M':'m','N':'n','NG':'ŋ',
    'L':'l','R':'r','W':'w','Y':'j','HH':'h',
};

// Diphthong/affricate component mapping (for sequential playback)
const DIPHTHONG_COMPONENTS = {
    'AW': ['AA', 'UW'],
    'AY': ['AA', 'IY'],
    'EY': ['EH', 'IY'],
    'OW': ['AO', 'UW'],
    'OY': ['AO', 'IY'],
    'CH': ['T', 'SH'],
    'JH': ['D', 'ZH'],
};

// ============================================================
// State
// ============================================================
const S = {
    sentence: null,
    recording: false,
    mediaRec: null,
    audioCtx: null,
    analyser: null,
    stream: null,
    chunks: [],
    recStart: 0,
    recTimer: null,
    animFrame: null,
    recordedBlob: null,
    recordedUrl: null,
    playbackPlaying: false,
    wordsExpanded: false,
    ipaVisible: false,
    phonemeTips: null,
    // --- New state ---
    mode: 'dictation',          // 'dictation' | 'practice'
    ttsFailCount: 0,
    ttsMode: 'browser',         // 'browser' | 'server'
    dictationResults: null,     // { words: [...], checked: bool }
    _dictationErrorWords: null, // Backend error words with similarity info
    fsrsRated: false,           // whether user has rated this sentence
    sentenceType: 'new',        // 'new' | 'review'
    pendingReviewCount: 0,
    pendingWordReviewCount: 0,
    ttsSpeed: 1.0,              // TTS playback speed for dictation
    phonemeAudioCache: {},      // Cache for IPA audio blobs
    // --- Auth state ---
    user: null,                 // {id, username, display_name, avatar_color, settings}
    authToken: null,            // Bearer token
    serverStats: null,          // Server-side per-user stats (from DB, cross-browser sync)
    weaknessProfile: null,      // User's weakness analysis
    // --- Learning mode state ---
    learningMode: 'smart',       // 'smart' | 'sequential'
    modeStatus: null,            // cached /api/mode/status response
    wordReviewQueue: [],         // Word review queue items
    wordReviewIndex: 0,          // Current index in review queue
    wordReviewTotal: 0,          // Total items in review queue
    // --- Prediction calibration state ---
    predictionScore: null,       // User's prediction score (0-100)
    calibrationEnabled: false,   // Auto-detected from /api/metacognition/profile
    abPhase: null,               // 'A' | 'B' | null - A/B compare playback phase
    bookmarked: false,           // Whether current sentence is bookmarked
    _lastReviewedCardId: null,   // Track last reviewed card to avoid repetition
    _reviewedCardIds: [],         // All reviewed card IDs in current session (avoid LEARNING/RELEARNING re-appearance)
    // --- Settings state ---
    settings: null,              // Cached settings from /api/settings
};

// 统计数据全部存储在服务端数据库中，跨浏览器自动同步
// 前端不再使用 localStorage 存储统计，所有数据从 /api/stats 获取

// ============================================================
// Auth helpers
// ============================================================
function loadAuth() {
    try {
        const token = localStorage.getItem('phonos_auth_token');
        const user = localStorage.getItem('phonos_user');
        if (token && user) {
            S.authToken = token;
            S.user = JSON.parse(user);
            return true;
        }
    } catch {}
    return false;
}

function saveAuth(token, user) {
    S.authToken = token;
    S.user = user;
    try {
        localStorage.setItem('phonos_auth_token', token);
        localStorage.setItem('phonos_user', JSON.stringify(user));
    } catch {}
}

function clearAuth() {
    S.authToken = null;
    S.user = null;
    try {
        localStorage.removeItem('phonos_auth_token');
        localStorage.removeItem('phonos_user');
    } catch {}
}

async function fetchWithAuth(url, options = {}) {
    if (S.authToken) {
        if (!options.headers) options.headers = {};
        options.headers['Authorization'] = `Bearer ${S.authToken}`;
    }
    return fetch(url, options);
}

async function validateToken() {
    if (!S.authToken) return false;
    try {
        const r = await fetchWithAuth(`${API}/api/auth/me`);
        if (r.ok) {
            S.user = await r.json();
            return true;
        } else {
            clearAuth();
            return false;
        }
    } catch {
        return false;
    }
}

async function doLogin(username, password) {
    const r = await fetch(`${API}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
    });
    if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || '登录失败');
    }
    const data = await r.json();
    saveAuth(data.token, data.user);
    return data;
}

async function doRegister(username, password, display_name) {
    const r = await fetch(`${API}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, display_name }),
    });
    if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || '注册失败');
    }
    const data = await r.json();
    saveAuth(data.token, data.user);
    return data;
}

async function doLogout() {
    if (S.authToken) {
        try { await fetchWithAuth(`${API}/api/auth/logout`, { method: 'POST' }); } catch {}
    }
    clearAuth();
}

async function doGuestLogin() {
    // No login needed, just clear auth and use default user
    clearAuth();
}

function updateUserProfileUI() {
    const profile = document.getElementById('userProfile');
    const avatar = document.getElementById('userAvatar');
    const name = document.getElementById('userName');
    if (!profile || !avatar || !name) return;

    if (S.user && S.user.id !== 'default') {
        profile.style.display = 'flex';
        avatar.style.background = S.user.avatar_color || '#6b7280';
        avatar.textContent = (S.user.display_name || S.user.username || '?')[0].toUpperCase();
        name.textContent = S.user.display_name || S.user.username;
    } else {
        profile.style.display = 'flex';
        avatar.style.background = '#6b7280';
        avatar.textContent = '?';
        name.textContent = '访客';
    }
}

function showAuthModal(mode = 'login') {
    const modal = document.getElementById('authModal');
    if (!modal) return;
    modal.style.display = 'flex';

    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const authTitle = document.getElementById('authTitle');

    loginForm.style.display = 'none';
    registerForm.style.display = 'none';

    if (mode === 'login') {
        loginForm.style.display = '';
        authTitle.textContent = '登录';
    } else if (mode === 'register') {
        registerForm.style.display = '';
        authTitle.textContent = '注册';
    }
}

function hideAuthModal() {
    const modal = document.getElementById('authModal');
    if (modal) modal.style.display = 'none';
}

// 不再提供用户列表功能，不暴露其他用户信息
// 每个用户只看自己的数据，跨浏览器通过服务端数据库同步

async function loadWeaknessProfile() {
    if (!S.authToken) return;
    try {
        const r = await fetchWithAuth(`${API}/api/learning/weakness-profile`);
        if (r.ok) S.weaknessProfile = await r.json();
    } catch {}
}

async function loadServerStats() {
    try {
        const r = await fetchWithAuth(`${API}/api/stats`);
        if (r.ok) {
            S.serverStats = await r.json();
            return S.serverStats;
        }
    } catch {}
    return null;
}

// ============================================================
// DOM
// ============================================================
const $ = id => document.getElementById(id);
const el = {
    statusDot: $('statusDot'), sentenceEn: $('sentenceEn'), sentenceZh: $('sentenceZh'),
    diffBadge: $('diffBadge'), reviewBadge: $('reviewBadge'),
    ipaSection: $('ipaSection'), ipaPhonemes: $('ipaPhonemes'),
    phrasesSection: $('phrasesSection'),
    phrasesList: $('phrasesList'), culturalNote: $('culturalNote'),
    btnRefresh: $('btnRefresh'), btnTTS: $('btnTTS'), btnToggleIPA: $('btnToggleIPA'),
    wordsList: $('wordsList'), btnToggleWords: $('btnToggleWords'),
    // Dictation
    dictationCard: $('dictationCard'), dictationInputs: $('dictationInputs'),
    dictationActions: $('dictationActions'), btnDictationCheck: $('btnDictationCheck'),
    dictationResults: $('dictationResults'), dictationTransition: $('dictationTransition'),
    btnStartPractice: $('btnStartPractice'), btnTTSDictation: $('btnTTSDictation'),
    dictationPhase: $('dictationPhase'),
    speedBtns: document.querySelectorAll('.speed-btn'),
    // Recording
    waveformCanvas: $('waveformCanvas'), waveformPlaceholder: $('waveformPlaceholder'),
    btnRecord: $('btnRecord'), recDot: $('recDot'), recLabel: $('recLabel'),
    recInfo: $('recInfo'), recTime: $('recTime'),
    playbackBar: $('playbackBar'), btnPlayback: $('btnPlayback'),
    playbackFill: $('playbackFill'), playbackTime: $('playbackTime'),
    btnSubmit: $('btnSubmit'), playbackAudio: $('playbackAudio'),
    recordingCard: $('recordingCard'),
    loadingCard: $('loadingCard'), resultCard: $('resultCard'),
    overallScore: $('overallScore'), scoreRing: $('scoreRing'),
    pronFill: $('pronFill'), pronVal: $('pronVal'),
    compFill: $('compFill'), compVal: $('compVal'),
    fluFill: $('fluFill'), fluVal: $('fluVal'),
    wordScoreGrid: $('wordScoreGrid'),
    phExpected: $('phExpected'), phActual: $('phActual'),
    fluDuration: $('fluDuration'), fluRate: $('fluRate'),
    fluPauses: $('fluPauses'), fluPauseDur: $('fluPauseDur'),
    tipsList: $('tipsList'),
    btnRetry: $('btnRetry'), btnNext: $('btnNext'),
    // FSRS
    fsrsSection: $('fsrsSection'),
    // Header
    reviewCounter: $('reviewCounter'), reviewCount: $('reviewCount'),
    btnStats: $('btnStats'), btnPhonemeGuide: $('btnPhonemeGuide'),
    phonemeModal: $('phonemeModal'), phonemeModalBody: $('phonemeModalBody'),
    closePhonemeModal: $('closePhonemeModal'),
    statsModal: $('statsModal'), statsModalBody: $('statsModalBody'),
    closeStatsModal: $('closeStatsModal'),
    // TTS audio element
    ttsAudio: $('ttsAudio'),
    // Mode selector
    modeSelector: $('modeSelector'), btnModeSmart: $('btnModeSmart'),
    btnModeSequential: $('btnModeSequential'), btnModeSettings: $('btnModeSettings'),
    // ID range dialog
    idRangeModal: $('idRangeModal'), closeIdRangeModal: $('closeIdRangeModal'),
    idRangeStart: $('idRangeStart'), idRangeEnd: $('idRangeEnd'),
    idRangeInfo: $('idRangeInfo'), idRangeError: $('idRangeError'),
    btnIdRangeConfirm: $('btnIdRangeConfirm'),
    // Data change banner
    dataChangeBanner: $('dataChangeBanner'), btnCloseDataChangeBanner: $('btnCloseDataChangeBanner'),
    // Word review modal
    wordReviewModal: $('wordReviewModal'), closeWordReviewModal: $('closeWordReviewModal'),
    wordReviewProgress: $('wordReviewProgress'), wordReviewEmpty: $('wordReviewEmpty'),
    wordReviewCards: $('wordReviewCards'),
    btnWordReview: $('btnWordReview'),
    btnWordPractice: $('btnWordPractice'),
    // New UI elements
    btnCognitiveMirror: $('btnCognitiveMirror'),
    btnBookmarks: $('btnBookmarks'),
    btnTheme: $('btnTheme'),
    btnSettings: $('btnSettings'),
    cognitiveMirrorModal: $('cognitiveMirrorModal'),
    closeCognitiveMirrorModal: $('closeCognitiveMirrorModal'),
    cognitiveMirrorBody: $('cognitiveMirrorBody'),
    settingsModal: $('settingsModal'),
    closeSettingsModal: $('closeSettingsModal'),
    settingsModalBody: $('settingsModalBody'),
    predictionSection: $('predictionSection'),
    predictionSlider: $('predictionSlider'),
    predictionValue: $('predictionValue'),
    calibrationDisplay: $('calibrationDisplay'),
    calPrediction: $('calPrediction'),
    calActual: $('calActual'),
    calDeviation: $('calDeviation'),
    semanticNetworkSection: $('semanticNetworkSection'),
    semanticNetworkContent: $('semanticNetworkContent'),
    btnAB: $('btnAB'),
    btnBookmark: $('btnBookmark'),
};

// ============================================================
// Init
// ============================================================
async function init() {
    // Show loading state immediately
    el.sentenceEn.textContent = '加载中...';
    el.diffBadge.textContent = '...';
    el.diffBadge.className = 'diff-badge';
    el.reviewBadge.style.display = 'none';
    el.dictationCard.style.display = 'none';
    el.recordingCard.style.display = 'none';

    initCanvas();
    bindEvents();

    // Load learning mode from localStorage
    loadLearningMode();

    // Auth: try to load saved token
    const hasAuth = loadAuth();
    if (hasAuth && S.authToken) {
        // Validate token with server
        const valid = await validateToken();
        if (!valid) {
            // Token expired, but don't force login - just use guest mode
            clearAuth();
        }
    }
    updateUserProfileUI();

    // Non-critical: load in parallel, don't block
    checkHealth();
    loadPhonemeTips();
    fetchReviewCount();
    // Fetch mode status BEFORE loading sentence (sequential mode needs start_id/end_id)
    await fetchModeStatus();

    // Load weakness profile if logged in
    if (S.authToken) loadWeaknessProfile();

    // Load metacognition profile (calibration enablement)
    loadMetacognitionProfile();

    // Load settings
    loadSettings();

    // Critical: load sentence (with timeout protection)
    try {
        await Promise.race([
            loadSentence(),
            new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 15000))
        ]);
    } catch (e) {
        el.sentenceEn.textContent = '加载超时，请点击刷新重试';
        el.diffBadge.textContent = '--';
        console.error('Sentence loading failed:', e);
    }
}

async function checkHealth() {
    try {
        const r = await fetch(`${API}/api/health`);
        const d = await r.json();
        el.statusDot.className = 'status-dot' + (d.model_loaded ? ' online' : '');
    } catch { el.statusDot.className = 'status-dot'; }
}

async function loadPhonemeTips() {
    try {
        const r = await fetch(`${API}/api/phoneme-tips`);
        S.phonemeTips = await r.json();
    } catch { S.phonemeTips = null; }
}

async function fetchReviewCount() {
    try {
        // Fetch both sentence and word due counts
        const [sentenceR, wordR] = await Promise.all([
            fetchWithAuth(`${API}/api/fsrs/due-count?card_type=sentence`),
            fetchWithAuth(`${API}/api/fsrs/due-count?card_type=word`)
        ]);
        if (sentenceR.ok) {
            const d = await sentenceR.json();
            S.pendingReviewCount = d.count || 0;  // sentence due count
        }
        if (wordR.ok) {
            const d = await wordR.json();
            // total_reviewable: 可练习总数（新词+待复习，不含已掌握）
            S.pendingWordReviewCount = d.total_reviewable || d.pending_count || d.count || 0;
        }
        updateReviewCounter();
    } catch { /* ignore */ }
}

function updateReviewCounter() {
    if (S.pendingReviewCount > 0) {
        el.reviewCounter.style.display = 'flex';
        el.reviewCount.textContent = S.pendingReviewCount;
    } else {
        el.reviewCounter.style.display = 'none';
    }
}

// ============================================================
// Sentence Loading (FSRS queue preferred)
// ============================================================
async function loadSentence(forceNew = false) {
    const prevId = S.sentence ? S.sentence.id : null;

    // Show loading indicator
    el.sentenceEn.textContent = '加载中...';
    el.diffBadge.textContent = '...';

    try {
        let loaded = false;

        // forceNew: always get a different random sentence
        if (forceNew) {
            try {
                const seed = Date.now();
                const r = await fetchWithAuth(`${API}/api/sentence?force_new=true&_t=${seed}`, {signal: AbortSignal.timeout(10000)});
                if (r.ok) {
                    const data = await r.json();
                    if (data && data.id && data.id !== prevId) {
                        S.sentence = data;
                        S.sentenceType = 'new';
                        loaded = true;
                    }
                }
            } catch { /* fallback below */ }
        }

        // Use mode-specific endpoint when not forceNew
        if (!loaded && !forceNew) {
            try {
                if (S.learningMode === 'sequential') {
                    // Sequential mode
                    let url = `${API}/api/mode/sequential/next`;
                    if (S.modeStatus && S.modeStatus.start_id) {
                        url += `?start_id=${S.modeStatus.start_id}`;
                        if (S.modeStatus.end_id) url += `&end_id=${S.modeStatus.end_id}`;
                    }
                    const r = await fetchWithAuth(url, {signal: AbortSignal.timeout(8000)});
                    if (r.ok) {
                        const d = await r.json();
                        if (d.sentence) {
                            S.sentence = d.sentence;
                            S.sentenceType = d.type || 'new';
                            loaded = true;
                            // Check for data change
                            if (d.data_changed) {
                                showDataChangeBanner();
                            }
                        }
                    }
                } else {
                    // Smart mode (FSRS-based)
                    let smartUrl = `${API}/api/mode/smart/next`;
                    if (S._reviewedCardIds.length > 0) {
                        smartUrl += `?exclude=${encodeURIComponent(S._reviewedCardIds.join(','))}`;
                    }
                    const r = await fetchWithAuth(smartUrl, {signal: AbortSignal.timeout(8000)});
                    if (r.ok) {
                        const d = await r.json();
                        if (d.sentence) {
                            S.sentence = d.sentence;
                            S.sentenceType = d.type || 'new';
                            loaded = true;
                        }
                    }
                }
            } catch { /* fallback below */ }
        }

        // Fallback: try FSRS queue
        if (!loaded && !forceNew) {
            try {
                let fsrsUrl = `${API}/api/fsrs/next`;
                if (S._reviewedCardIds.length > 0) {
                    fsrsUrl += `?exclude=${encodeURIComponent(S._reviewedCardIds.join(','))}`;
                }
                const r = await fetchWithAuth(fsrsUrl, {signal: AbortSignal.timeout(8000)});
                if (r.ok) {
                    const d = await r.json();
                    if (d.sentence) {
                        S.sentence = d.sentence;
                        S.sentenceType = d.type || 'new';
                        loaded = true;
                    }
                }
            } catch { /* fallback below */ }
        }

        // Final fallback: get a random sentence (ensure different from previous)
        if (!loaded) {
            let attempts = 0;
            do {
                try {
                    const seed = Date.now() + attempts;
                    const r = await fetchWithAuth(`${API}/api/sentence?_t=${seed}`, {signal: AbortSignal.timeout(8000)});
                    if (r.ok) {
                        const data = await r.json();
                        if (data && data.text) {
                            S.sentence = data;
                            S.sentenceType = 'new';
                            loaded = true;
                        }
                    }
                } catch { /* retry */ }
                attempts++;
            } while (S.sentence && S.sentence.id === prevId && attempts < 5);
        }

        if (!loaded || !S.sentence) {
            throw new Error('无法加载句子');
        }

        S.mode = 'dictation';
        S.dictationResults = null;
        S._dictationErrorWords = null;
        S.fsrsRated = false;
        S.predictionScore = null;
        // 如果成功加载了不同的句子，清除上一次的exclude（但保留session内已复习列表）
        // _reviewedCardIds 在整个session内保留，防止LEARNING/RELEARNING卡片1分钟后又出现

        renderSentence();
        renderDictationInputs();
        updateModeUI();
        fetchReviewCount();

        // Show prediction UI if calibration is enabled
        showPredictionUI();
        hideCalibrationResult();
    } catch (e) {
        console.error('loadSentence error:', e);
        el.sentenceEn.textContent = '加载失败，请点击刷新重试';
        el.diffBadge.textContent = '--';
        el.diffBadge.className = 'diff-badge';
    }
}

function updateSentenceVisibility() {
    // In dictation mode, hide the sentence text and translation to prevent cheating
    // In practice mode (after dictation), show the full sentence
    if (S.mode === 'dictation') {
        el.sentenceEn.textContent = '🎧 听写模式 — 请根据听力输入句子';
        el.sentenceEn.classList.add('dictation-hidden');
        el.sentenceZh.textContent = '';
        el.sentenceZh.classList.add('dictation-hidden');
        // Also hide IPA and key phrases during dictation
        el.ipaSection.style.display = 'none';
        el.phrasesSection.style.display = 'none';
    } else {
        // Practice mode: show the full sentence
        if (S.sentence) {
            // Apply translation priority setting
            const settings = S.settings || {};
            if (settings.show_translation_first && S.sentence.translation) {
                el.sentenceZh.textContent = S.sentence.translation;
                el.sentenceZh.style.order = '-1';  // Move translation above English
                el.sentenceEn.textContent = S.sentence.text;
            } else {
                el.sentenceEn.textContent = S.sentence.text;
                el.sentenceZh.textContent = S.sentence.translation || '';
                el.sentenceZh.style.order = '';
            }
        }
        el.sentenceEn.classList.remove('dictation-hidden');
        el.sentenceZh.classList.remove('dictation-hidden');
        // Restore IPA visibility based on toggle
        el.ipaSection.style.display = S.ipaVisible ? '' : 'none';
    }
}

function renderSentence() {
    const s = S.sentence;
    el.diffBadge.textContent = s.difficulty.toUpperCase();
    el.diffBadge.className = 'diff-badge ' + s.difficulty;

    // Review badge - use FSRS state from the sentence data if available
    const fsrsData = s.fsrs || {};
    const fsrsState = fsrsData.state_name || fsrsData.state;
    // Determine if this is truly new or a review card
    // A card is "review" if:
    // 1. Its FSRS state is LEARNING(1), REVIEW(2), or RELEARNING(3)
    // 2. It was explicitly loaded as type 'review'
    // 3. It has been previously evaluated (has reps > 0 or was in session reviewed list)
    const cardId = `sentence_${s.id}`;
    const hasBeenReviewedInSession = S._reviewedCardIds.includes(cardId);
    const hasFSRSProgress = fsrsData.reps !== undefined && fsrsData.reps > 0;
    const isReview = S.sentenceType === 'review' ||
                     (fsrsState && ['learning', 'review', 'relearning', 'due'].includes(fsrsState)) ||
                     (fsrsData.state !== undefined && fsrsData.state >= 1) ||
                     hasBeenReviewedInSession ||
                     hasFSRSProgress;

    if (isReview) {
        el.reviewBadge.style.display = '';
        el.reviewBadge.textContent = '复习';
        el.reviewBadge.className = 'review-badge review';
    } else {
        el.reviewBadge.style.display = '';
        el.reviewBadge.textContent = '新句';
        el.reviewBadge.className = 'review-badge new';
    }

    // Apply sentence visibility based on current mode
    updateSentenceVisibility();

    // IPA section - only render chips if visible (not in dictation mode)
    if (S.ipaVisible && S.mode !== 'dictation') renderIPAChips();

    // Key phrases - hidden during dictation, shown in practice mode
    if (S.mode !== 'dictation' && s.key_phrases && s.key_phrases.length) {
        el.phrasesSection.style.display = '';
        el.phrasesList.innerHTML = s.key_phrases.map(p => `
            <div class="phrase-item">
                <div class="phrase-en">${p.phrase}</div>
                <div class="phrase-zh">${p.meaning}</div>
                ${p.note ? `<div class="phrase-note">${p.note}</div>` : ''}
            </div>
        `).join('');
    } else {
        el.phrasesSection.style.display = 'none';
    }

    // Cultural note
    if (s.cultural_note) {
        el.culturalNote.style.display = '';
        el.culturalNote.innerHTML = `<strong>文化提示：</strong>${s.cultural_note}`;
    } else {
        el.culturalNote.style.display = 'none';
    }

    // Words
    renderWords(s.word_details || []);

    // Reset UI
    el.resultCard.style.display = 'none';
    el.loadingCard.style.display = 'none';
    el.playbackBar.style.display = 'none';
    if (el.btnAB) el.btnAB.style.display = 'none';
    S.recordedBlob = null;
    S.recordedUrl = null;
    // Hide semantic network when new sentence loads
    if (el.semanticNetworkSection) el.semanticNetworkSection.style.display = 'none';

    // Bookmark state
    if (S.sentence) {
        const cardId = `sentence_${S.sentence.id}`;
        fetchWithAuth(`${API}/api/sentence-state?card_id=${encodeURIComponent(cardId)}`).then(r => r.ok ? r.json() : Promise.reject()).then(data => {
            S.bookmarked = data.bookmarked || false;
            updateBookmarkUI();
        }).catch(() => { S.bookmarked = false; updateBookmarkUI(); });
    }
}

// ============================================================
// IPA Display with clickable phoneme chips (compact format)
// ============================================================
function renderIPAChips() {
    const s = S.sentence;
    if (!s || !s.ipa) {
        el.ipaPhonemes.innerHTML = '<span style="color:var(--text3);font-size:13px;">No IPA available</span>';
        return;
    }

    const ipaStr = s.ipa;
    const wordParts = ipaStr.split(/\s+/);
    let html = '/';

    wordParts.forEach((word, wi) => {
        if (wi > 0) html += ' ';
        const symbols = tokenizeIPA(word);
        symbols.forEach(sym => {
            const cleanSym = sym.replace(/[ˈˌ]/g, '');
            const arpabet = findARPAbetForIPA(cleanSym);
            html += `<span class="ipa-chip" data-ipa="${escapeAttr(sym)}" data-arpabet="${arpabet}" onclick="pronouncePhoneme(this)">${sym}</span>`;
        });
    });

    html += '/';
    el.ipaPhonemes.innerHTML = html;
}

function tokenizeIPA(word) {
    const tokens = [];
    let i = 0;
    while (i < word.length) {
        const ch = word[i];
        if (ch === 'ˈ' || ch === 'ˌ') {
            if (i + 1 < word.length) {
                tokens.push(ch + word[i + 1]);
                i += 2;
            } else {
                tokens.push(ch);
                i++;
            }
        } else if (i + 1 < word.length) {
            const digraph = ch + word[i + 1];
            if (['tʃ','dʒ','aʊ','aɪ','eɪ','oʊ','ɔɪ'].includes(digraph)) {
                tokens.push(digraph);
                i += 2;
            } else {
                tokens.push(ch);
                i++;
            }
        } else {
            tokens.push(ch);
            i++;
        }
    }
    return tokens;
}

function findARPAbetForIPA(ipaSym) {
    for (const [arp, ipa] of Object.entries(ARPABET_TO_IPA)) {
        if (ipa === ipaSym) return arp;
    }
    return '';
}

function escapeAttr(s) {
    return s.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ============================================================
// Click-to-pronounce phonemes using standard IPA audio files
// ============================================================
const PHONEME_EXAMPLE_WORDS = {
    'AA': 'father', 'AE': 'cat', 'AH': 'about', 'AW': 'how', 'AY': 'my',
    'EH': 'bed', 'ER': 'bird', 'EY': 'day', 'IH': 'sit', 'IY': 'see',
    'OW': 'go', 'OY': 'boy', 'UH': 'book', 'UW': 'food',
    'B': 'big', 'CH': 'chair', 'D': 'day', 'DH': 'this', 'DX': 'water',
    'F': 'five', 'G': 'go', 'HH': 'hello', 'JH': 'jump', 'K': 'can',
    'L': 'light', 'M': 'man', 'N': 'no', 'NG': 'sing',
    'P': 'pen', 'R': 'red', 'S': 'see', 'SH': 'she', 'T': 'time',
    'TH': 'think', 'V': 'very', 'W': 'we', 'Y': 'yes', 'Z': 'zoo', 'ZH': 'vision',
};

async function playIPAAudio(arpabet) {
    if (!arpabet) return false;

    // Check if it's a diphthong/affricate - play components sequentially
    const components = DIPHTHONG_COMPONENTS[arpabet];
    if (components) {
        for (const comp of components) {
            await playSingleIPAAudio(comp);
        }
        return true;
    }

    return await playSingleIPAAudio(arpabet);
}

async function playSingleIPAAudio(arpabet) {
    if (!arpabet) return false;

    // Try the standard IPA audio endpoint first (real human pronunciation)
    try {
        const r = await fetch(`${API}/api/ipa-audio/${encodeURIComponent(arpabet)}`);
        if (r.ok) {
            const contentType = r.headers.get('content-type') || '';
            // If it's a JSON response (composite), handle it
            if (contentType.includes('application/json')) {
                const data = await r.json();
                if (data.type === 'composite' && data.components) {
                    for (const compUrl of data.components) {
                        await playAudioFromUrl(`${API}${compUrl}`);
                    }
                    return true;
                }
            } else {
                // Direct audio file
                return await playAudioFromResponse(r);
            }
        }
    } catch { /* fallback */ }

    return false;
}

async function playAudioFromResponse(response) {
    try {
        const blob = await response.blob();
        if (blob.size > 200) {
            const url = URL.createObjectURL(blob);
            return await new Promise((resolve) => {
                const audio = new Audio(url);
                audio.onended = () => { URL.revokeObjectURL(url); resolve(true); };
                audio.onerror = () => { URL.revokeObjectURL(url); resolve(false); };
                audio.play().catch(() => resolve(false));
            });
        }
    } catch { /* ignore */ }
    return false;
}

async function playAudioFromUrl(url) {
    try {
        const r = await fetch(url);
        if (r.ok) return await playAudioFromResponse(r);
    } catch { /* ignore */ }
    return false;
}

function playPhonemeTTSFallback(arpabet) {
    // Fallback: speak the phoneme's example word using browser TTS
    if ('speechSynthesis' in window) {
        const exampleWord = PHONEME_EXAMPLE_WORDS[arpabet] || findExampleWordFromSentence('', arpabet);
        if (exampleWord) {
            const utter = new SpeechSynthesisUtterance(exampleWord);
            utter.lang = 'en-US';
            utter.rate = 0.6;
            const voices = speechSynthesis.getVoices();
            const usVoice = voices.find(v => v.lang === 'en-US') || voices.find(v => v.lang.startsWith('en'));
            if (usVoice) utter.voice = usVoice;
            speechSynthesis.cancel();
            speechSynthesis.speak(utter);
            return true;
        }
    }
    return false;
}

async function pronouncePhoneme(chipEl) {
    const ipa = chipEl.dataset.ipa;
    const arpabet = chipEl.dataset.arpabet;

    // Visual feedback
    chipEl.classList.add('playing');
    setTimeout(() => chipEl.classList.remove('playing'), 600);

    // Try IPA standard audio first (real human pronunciation)
    const played = await playIPAAudio(arpabet);
    if (played) return;

    // Fallback: TTS with example word
    playPhonemeTTSFallback(arpabet);
}

function findExampleWordFromSentence(ipa, arpabet) {
    if (!S.sentence || !S.sentence.word_details) return null;
    for (const w of S.sentence.word_details) {
        if (w.arpabet && arpabet && w.arpabet.includes(arpabet)) {
            return w.word;
        }
    }
    return null;
}

// Make pronouncePhoneme globally accessible
window.pronouncePhoneme = pronouncePhoneme;

// ============================================================
// Words rendering (with IPA prominent)
// ============================================================
function renderWords(words) {
    if (!words || !words.length) { el.wordsList.innerHTML = ''; return; }
    el.wordsList.innerHTML = words.map(w => {
        const freq = w.frequency || 0;
        const freqDots = Array(5).fill(0).map((_, i) =>
            `<span class="freq-dot${i < freq ? ' active' : ''}"></span>`
        ).join('');

        const ipaStr = w.ipa || '';
        const arpabetStr = w.arpabet ? w.arpabet.join(' ') : '';

        return `
        <div class="word-item" onclick="lookupSemanticNetwork('${escapeAttr(w.word)}')">
            <div class="word-main">
                <span class="word-word">${w.word}</span><span class="word-pos">${w.pos || ''}</span>
                ${ipaStr ? `<div class="word-ipa">/${ipaStr}/</div>` : ''}
                ${arpabetStr ? `<div class="word-phonetic">${arpabetStr}</div>` : ''}
                <div class="word-meaning">${w.meaning || ''}</div>
                ${w.memory_tip ? `<div class="word-extra">${w.memory_tip}</div>` : ''}
                ${w.grammar_note ? `<div class="word-extra">${w.grammar_note}</div>` : ''}
            </div>
            <div class="word-freq" title="使用频率">${freqDots}</div>
        </div>`;
    }).join('');
}

// ============================================================
// TTS with fallback (Browser → Server) + Speed Control
// ============================================================
function speakTTS(speed) {
    if (!S.sentence) return;
    const useSpeed = speed || S.ttsSpeed;
    // Apply TTS priority setting
    const settings = S.settings || {};
    if (settings.tts_priority === 'server') {
        // Try server first, fallback to browser
        speakServerTTS(useSpeed).catch(() => speakBrowserTTS(useSpeed));
    } else {
        // Default: browser first, then server
        if (S.ttsMode === 'browser') {
            speakBrowserTTS(useSpeed);
        } else {
            speakServerTTS(useSpeed);
        }
    }
}

function speakBrowserTTS(speed) {
    if (!('speechSynthesis' in window)) {
        S.ttsFailCount++;
        checkTTSFallback();
        return;
    }

    window.speechSynthesis.cancel();

    const utter = new SpeechSynthesisUtterance(S.sentence.text);
    utter.lang = 'en-US';
    utter.rate = 0.9 * speed;  // Apply speed multiplier
    utter.pitch = 1.0;

    const voices = speechSynthesis.getVoices();
    const usVoice = voices.find(v => v.lang === 'en-US') || voices.find(v => v.lang.startsWith('en'));
    if (usVoice) utter.voice = usVoice;

    el.btnTTS.classList.add('active');
    utter.onend = () => el.btnTTS.classList.remove('active');
    utter.onerror = () => {
        el.btnTTS.classList.remove('active');
        S.ttsFailCount++;
        checkTTSFallback();
    };

    speechSynthesis.speak(utter);
}

async function speakServerTTS(speed) {
    if (!S.sentence) return;
    try {
        const r = await fetch(`${API}/api/tts?text=${encodeURIComponent(S.sentence.text)}`);
        if (!r.ok) throw new Error('Server TTS failed');
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        el.ttsAudio.src = url;
        el.ttsAudio.playbackRate = speed || 1.0;
        el.ttsAudio.onended = () => {
            el.btnTTS.classList.remove('active');
            URL.revokeObjectURL(url);
        };
        el.ttsAudio.onerror = () => {
            el.btnTTS.classList.remove('active');
        };
        el.btnTTS.classList.add('active');
        await el.ttsAudio.play();
    } catch (e) {
        el.btnTTS.classList.remove('active');
        console.error('Server TTS error:', e);
    }
}

function checkTTSFallback() {
    if (S.ttsFailCount >= 2 && S.ttsMode === 'browser') {
        S.ttsMode = 'server';
        console.log('Switching TTS mode to server after', S.ttsFailCount, 'failures');
        speakServerTTS();
    }
}

// Ensure voices are loaded
if ('speechSynthesis' in window) {
    speechSynthesis.onvoiceschanged = () => speechSynthesis.getVoices();
}

// ============================================================
// Dictation Mode
// ============================================================
function renderDictationInputs() {
    if (!S.sentence) return;

    // Ensure we're in dictation mode
    S.mode = 'dictation';

    const words = S.sentence.text.split(/\s+/);

    // Make dictation inputs visible
    el.dictationInputs.style.display = '';
    el.dictationInputs.innerHTML = words.map((word, i) => {
        const cleanWord = word.replace(/[^a-zA-Z'-]/g, '');
        const hintLength = cleanWord.length;
        const hint = '_'.repeat(hintLength);
        const width = Math.max(50, Math.min(120, hintLength * 14));

        return `
        <div class="dict-input-wrap">
            <input type="text" class="dict-input" data-index="${i}" data-answer="${escapeAttr(cleanWord)}"
                   style="width:${width}px;" maxlength="${hintLength + 5}"
                   placeholder="" autocomplete="off" spellcheck="false">
            <span class="dict-hint">${hint}</span>
            <span class="dict-correct-answer" id="dictAnswer${i}" style="display:none;"></span>
        </div>`;
    }).join('');

    // Show dictation card, reset state
    el.dictationCard.style.display = '';
    el.dictationActions.style.display = '';
    el.dictationResults.style.display = 'none';
    el.dictationTransition.style.display = 'none';
    el.dictationPhase.textContent = '听写';
    el.dictationPhase.className = 'dictation-phase';

    // Focus first input
    const firstInput = el.dictationInputs.querySelector('.dict-input');
    if (firstInput) setTimeout(() => firstInput.focus(), 300);

    // Auto-advance on space
    el.dictationInputs.querySelectorAll('.dict-input').forEach(input => {
        input.addEventListener('keydown', e => {
            if (e.key === ' ') {
                e.preventDefault();
                const next = input.closest('.dict-input-wrap').nextElementSibling;
                if (next) next.querySelector('.dict-input').focus();
            } else if (e.key === 'Backspace' && input.value === '') {
                const prev = input.closest('.dict-input-wrap').previousElementSibling;
                if (prev) prev.querySelector('.dict-input').focus();
            } else if (e.key === 'Enter') {
                checkDictation();
            }
        });
    });

    // Hide sentence during dictation
    updateSentenceVisibility();

    // Auto-play TTS for dictation
    setTimeout(() => speakTTS(), 500);
}

async function checkDictation() {
    if (!S.sentence) return;

    const inputs = el.dictationInputs.querySelectorAll('.dict-input');
    const words = S.sentence.text.split(/\s+/);
    const userWords = Array.from(inputs).map(inp => inp.value.trim().toLowerCase());
    const expectedWords = words.map(w => w.replace(/[^a-zA-Z'-]/g, '').toLowerCase());

    // Try backend checking (uses Levenshtein distance)
    let backendResults = null;
    try {
        const r = await fetchWithAuth(`${API}/api/dictation/check`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sentence_text: S.sentence.text,
                user_input: userWords,
            }),
        });
        if (r.ok) backendResults = await r.json();
    } catch { /* fallback to local check */ }

    if (backendResults && backendResults.results) {
        let correctCount = 0;
        let partialCount = 0;
        let orderErrorCount = 0;
        const alignmentResults = backendResults.results;
        const inputMap = new Map();

        let ei = 0, ui = 0;
        for (const r of alignmentResults) {
            if (r.type === 'match') {
                inputMap.set(r.user_index ?? ui, { correct: true, type: 'match', expected: r.expected });
                ei++; ui++;
            } else if (r.type === 'near_correct') {
                // Minor spelling error, counted as correct but flagged
                inputMap.set(r.user_index ?? ui, { correct: true, type: 'near_correct', expected: r.expected, actual: r.actual, similarity: r.similarity });
                ei++; ui++;
            } else if (r.type === 'partial') {
                // Partially correct spelling
                inputMap.set(r.user_index ?? ui, { correct: false, type: 'partial', expected: r.expected, actual: r.actual, similarity: r.similarity });
                ei++; ui++;
            } else if (r.type === 'order_error') {
                // Spelling correct but wrong relative order
                inputMap.set(r.user_index ?? ui, { correct: false, type: 'order_error', expected: r.expected, actual: r.actual });
                orderErrorCount++;
                ei++; ui++;
            } else if (r.type === 'substitution') {
                inputMap.set(r.user_index ?? ui, { correct: false, type: 'substitution', expected: r.expected });
                ei++; ui++;
            } else if (r.type === 'deletion') {
                ei++;
            } else if (r.type === 'insertion') {
                ui++;
            }
        }

        inputs.forEach((input, i) => {
            const mapped = inputMap.get(i);
            input.classList.remove('correct', 'incorrect', 'partial', 'near-correct', 'order-error');
            if (mapped) {
                if (mapped.type === 'near_correct') {
                    input.classList.add('correct', 'near-correct');
                    correctCount++;
                } else if (mapped.type === 'order_error') {
                    input.classList.add('incorrect', 'order-error');
                    const answerEl = document.getElementById(`dictAnswer${i}`);
                    if (answerEl) {
                        answerEl.textContent = mapped.expected;
                        answerEl.style.display = '';
                    }
                } else if (mapped.type === 'partial') {
                    input.classList.add('incorrect', 'partial');
                    partialCount++;
                    const answerEl = document.getElementById(`dictAnswer${i}`);
                    if (answerEl) {
                        answerEl.textContent = mapped.expected;
                        answerEl.style.display = '';
                    }
                } else if (mapped.correct) {
                    input.classList.add('correct');
                    correctCount++;
                } else {
                    input.classList.add('incorrect');
                    const answerEl = document.getElementById(`dictAnswer${i}`);
                    if (answerEl) {
                        answerEl.textContent = mapped.expected;
                        answerEl.style.display = '';
                    }
                }
            } else {
                // Empty input that wasn't consumed = missed word
                input.classList.add('incorrect');
            }
            input.disabled = true;
        });

        const totalExpected = expectedWords.filter(w => w).length;
        // near_correct counts as correct, partial as half
        const effectiveCorrect = correctCount + Math.round(partialCount * 0.5);

        // Build detailed summary from backend
        const summary = backendResults.summary || {};
        let summaryHtml = '';
        if (Object.keys(summary).length > 0) {
            const parts = [];
            if (summary.spelling_errors > 0) parts.push(`<span style="color:#e74c3c">拼写${summary.spelling_errors}</span>`);
            if (summary.missed > 0) parts.push(`<span style="color:#e67e22">漏写${summary.missed}</span>`);
            if (summary.extra > 0) parts.push(`<span style="color:#8b5cf6">多写${summary.extra}</span>`);
            if (summary.order_errors > 0) parts.push(`<span style="color:#9b59b6">顺序错${summary.order_errors}</span>`);
            if (summary.near_correct > 0) parts.push(`<span style="color:#f59e0b">近似${summary.near_correct}</span>`);
            if (parts.length > 0) {
                summaryHtml = `<div class="dict-error-summary">${parts.join(' · ')}</div>`;
            }
        }

        el.dictationResults.style.display = '';
        el.dictationResults.innerHTML = `
            <div class="dict-result-summary">
                <span class="correct-count">${correctCount}</span>
                <span class="total-count">/ ${totalExpected} 正确</span>
                ${partialCount > 0 ? `<span class="partial-hint">（${partialCount}个近似）</span>` : ''}
                ${orderErrorCount > 0 ? `<span class="partial-hint" style="color:#9b59b6">（${orderErrorCount}个顺序错）</span>` : ''}
            </div>
            ${summaryHtml}
        `;
        el.dictationActions.style.display = 'none';
        el.dictationTransition.style.display = '';
        S.dictationResults = { correct: correctCount, total: totalExpected, checked: true };
        // Save backend error words for recordDictationErrors
        S._dictationErrorWords = backendResults.error_words || [];
    } else {
        let correctCount = 0;
        inputs.forEach((input, i) => {
            const answer = expectedWords[i] || '';
            const isCorrect = input.value.trim().toLowerCase() === answer;
            input.classList.remove('correct', 'incorrect');
            input.classList.add(isCorrect ? 'correct' : 'incorrect');
            input.disabled = true;
            if (isCorrect) {
                correctCount++;
            } else {
                const answerEl = document.getElementById(`dictAnswer${i}`);
                if (answerEl) {
                    answerEl.textContent = answer;
                    answerEl.style.display = '';
                }
            }
        });

        el.dictationResults.style.display = '';
        el.dictationResults.innerHTML = `
            <div class="dict-result-summary">
                <span class="correct-count">${correctCount}</span>
                <span class="total-count">/ ${expectedWords.length} 正确</span>
            </div>
        `;
        el.dictationActions.style.display = 'none';
        el.dictationTransition.style.display = '';
        S.dictationResults = { correct: correctCount, total: expectedWords.length, checked: true };
    }

    // Auto-record dictation errors
    recordDictationErrors(inputs, expectedWords);
}

function transitionToPractice() {
    S.mode = 'practice';
    updateModeUI();

    // Show the full sentence now (was hidden during dictation)
    updateSentenceVisibility();

    // Restore key phrases if available
    if (S.sentence && S.sentence.key_phrases && S.sentence.key_phrases.length) {
        el.phrasesSection.style.display = '';
    }

    el.dictationPhase.textContent = '口语';
    el.dictationPhase.className = 'dictation-phase practice';

    // Hide dictation inputs area, keep the card visible with phase change
    el.dictationInputs.style.display = 'none';
    el.dictationResults.style.display = 'none';
    el.dictationTransition.style.display = 'none';
    el.dictationActions.style.display = 'none';

    // Show recording card (it's now inside the practice section below the sentence)
    el.recordingCard.style.display = '';

    // Re-init canvas for waveform (since it may not have been visible)
    setTimeout(() => {
        initCanvas();
        el.recordingCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 200);
}

function updateModeUI() {
    if (S.mode === 'dictation') {
        el.dictationCard.style.display = '';
        el.dictationInputs.style.display = '';
        el.recordingCard.style.display = 'none';
    } else {
        el.recordingCard.style.display = '';
    }
}

// ============================================================
// FSRS Rating
// ============================================================
async function submitFSRSRating(rating) {
    if (!S.sentence) return;

    const cardId = S.sentence.fsrs?.card_id || `sentence_${S.sentence.id}`;

    try {
        const r = await fetchWithAuth(`${API}/api/fsrs/review`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                card_id: cardId,
                rating: rating,
            }),
        });

        if (r.ok) {
            S.fsrsRated = true;
            S._lastReviewedCardId = cardId; // Track to avoid repeating
            // Add to session reviewed list (prevent LEARNING/RELEARNING cards re-appearing)
            if (!S._reviewedCardIds.includes(cardId)) {
                S._reviewedCardIds.push(cardId);
                // Keep only last 50 to avoid URL too long
                if (S._reviewedCardIds.length > 50) S._reviewedCardIds.shift();
            }
            document.querySelectorAll('.fsrs-btn').forEach(btn => {
                btn.classList.remove('selected');
                if (parseInt(btn.dataset.rating) === rating) {
                    btn.classList.add('selected');
                }
            });
            setTimeout(() => loadSentence(), 800);
        }
    } catch (e) {
        console.error('FSRS rating error:', e);
        loadSentence();
    }
}

// ============================================================
// Events
// ============================================================
function bindEvents() {
    el.btnRefresh.addEventListener('click', () => loadSentence(true));
    el.btnTTS.addEventListener('click', () => speakTTS());

    // IPA toggle
    el.btnToggleIPA.addEventListener('click', () => {
        S.ipaVisible = !S.ipaVisible;
        el.ipaSection.style.display = S.ipaVisible ? '' : 'none';
        el.btnToggleIPA.classList.toggle('active', S.ipaVisible);
        if (S.ipaVisible) renderIPAChips();
    });

    el.btnToggleWords.addEventListener('click', () => {
        S.wordsExpanded = !S.wordsExpanded;
        el.wordsList.classList.toggle('collapsed', !S.wordsExpanded);
        el.btnToggleWords.classList.toggle('collapsed', !S.wordsExpanded);
    });

    // Collapsible: Tips section
    const btnToggleTips = document.getElementById('btnToggleTips');
    if (btnToggleTips) {
        btnToggleTips.addEventListener('click', () => {
            const content = el.tipsList;
            const isCollapsed = content.classList.contains('collapsed');
            content.classList.toggle('collapsed', !isCollapsed);
            btnToggleTips.classList.toggle('collapsed', !isCollapsed);
        });
    }

    // Collapsible: Word scores section
    const btnToggleWordScores = document.getElementById('btnToggleWordScores');
    if (btnToggleWordScores) {
        btnToggleWordScores.addEventListener('click', () => {
            const content = el.wordScoreGrid;
            const isCollapsed = content.classList.contains('collapsed');
            content.classList.toggle('collapsed', !isCollapsed);
            btnToggleWordScores.classList.toggle('collapsed', !isCollapsed);
        });
    }

    // Dictation TTS with speed
    el.btnTTSDictation.addEventListener('click', () => speakTTS());

    // Speed buttons
    document.querySelectorAll('.speed-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const speed = parseFloat(btn.dataset.speed);
            S.ttsSpeed = speed;
            // Update active state
            document.querySelectorAll('.speed-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            // Play with the new speed
            speakTTS(speed);
        });
    });

    el.btnDictationCheck.addEventListener('click', checkDictation);
    el.btnStartPractice.addEventListener('click', transitionToPractice);

    // Skip dictation button
    const btnSkipDictation = document.getElementById('btnSkipDictation');
    if (btnSkipDictation) {
        btnSkipDictation.addEventListener('click', () => {
            S.mode = 'practice';
            updateModeUI();
            // Show the full sentence now (was hidden during dictation)
            updateSentenceVisibility();
            // Restore key phrases if available
            if (S.sentence && S.sentence.key_phrases && S.sentence.key_phrases.length) {
                el.phrasesSection.style.display = '';
            }
            el.dictationPhase.textContent = '口语';
            el.dictationPhase.className = 'dictation-phase practice';
            el.dictationInputs.style.display = 'none';
            el.dictationResults.style.display = 'none';
            el.dictationTransition.style.display = 'none';
            el.dictationActions.style.display = 'none';
            el.recordingCard.style.display = '';
            setTimeout(() => {
                initCanvas();
                el.recordingCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }, 200);
        });
    }

    // Recording
    el.btnRecord.addEventListener('click', toggleRecording);
    el.btnPlayback.addEventListener('click', togglePlayback);
    if (el.btnAB) el.btnAB.addEventListener('click', playAB);
    if (el.btnBookmark) el.btnBookmark.addEventListener('click', toggleBookmark);
    el.btnSubmit.addEventListener('click', submitEvaluation);

    el.btnRetry.addEventListener('click', () => {
        el.resultCard.style.display = 'none';
        el.playbackBar.style.display = 'none';
    });

    el.btnNext.addEventListener('click', () => loadSentence(true));

    // FSRS rating buttons
    document.querySelectorAll('.fsrs-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const rating = parseInt(btn.dataset.rating);
            submitFSRSRating(rating);
        });
    });

    // Modals
    el.btnPhonemeGuide.addEventListener('click', openPhonemeGuide);
    el.closePhonemeModal.addEventListener('click', () => el.phonemeModal.style.display = 'none');
    el.btnStats.addEventListener('click', openStats);
    el.closeStatsModal.addEventListener('click', () => el.statsModal.style.display = 'none');

    el.phonemeModal.addEventListener('click', e => { if (e.target === el.phonemeModal) el.phonemeModal.style.display = 'none'; });
    el.statsModal.addEventListener('click', e => { if (e.target === el.statsModal) el.statsModal.style.display = 'none'; });

    // Mode selector events
    if (el.btnModeSmart) el.btnModeSmart.addEventListener('click', () => switchLearningMode('smart'));
    if (el.btnModeSequential) el.btnModeSequential.addEventListener('click', () => switchLearningMode('sequential'));
    if (el.btnModeSettings) el.btnModeSettings.addEventListener('click', openIdRangeDialog);

    // ID range dialog events
    if (el.closeIdRangeModal) el.closeIdRangeModal.addEventListener('click', () => el.idRangeModal.style.display = 'none');
    if (el.idRangeModal) el.idRangeModal.addEventListener('click', e => { if (e.target === el.idRangeModal) el.idRangeModal.style.display = 'none'; });
    if (el.btnIdRangeConfirm) el.btnIdRangeConfirm.addEventListener('click', confirmIdRange);

    // Data change banner
    if (el.btnCloseDataChangeBanner) el.btnCloseDataChangeBanner.addEventListener('click', hideDataChangeBanner);

    // Word review modal events
    if (el.btnWordReview) el.btnWordReview.addEventListener('click', openWordReview);
    if (el.closeWordReviewModal) el.closeWordReviewModal.addEventListener('click', () => el.wordReviewModal.style.display = 'none');
    if (el.wordReviewModal) el.wordReviewModal.addEventListener('click', e => { if (e.target === el.wordReviewModal) el.wordReviewModal.style.display = 'none'; });

    // Word practice modal events
    initWordPractice();

    // Cognitive Mirror modal events
    if (el.btnCognitiveMirror) el.btnCognitiveMirror.addEventListener('click', openCognitiveMirror);
    if (el.closeCognitiveMirrorModal) el.closeCognitiveMirrorModal.addEventListener('click', () => el.cognitiveMirrorModal.style.display = 'none');
    if (el.cognitiveMirrorModal) el.cognitiveMirrorModal.addEventListener('click', e => { if (e.target === el.cognitiveMirrorModal) el.cognitiveMirrorModal.style.display = 'none'; });

    // Settings modal events
    if (el.btnSettings) el.btnSettings.addEventListener('click', openSettingsModal);
    if (el.closeSettingsModal) el.closeSettingsModal.addEventListener('click', () => el.settingsModal.style.display = 'none');
    if (el.settingsModal) el.settingsModal.addEventListener('click', e => { if (e.target === el.settingsModal) el.settingsModal.style.display = 'none'; });

    // Bookmarks modal events
    if (el.btnBookmarks) el.btnBookmarks.addEventListener('click', openBookmarksModal);

    // Theme toggle
    if (el.btnTheme) el.btnTheme.addEventListener('click', toggleTheme);
    initTheme();

    // Prediction slider
    if (el.predictionSlider) el.predictionSlider.addEventListener('input', () => {
        S.predictionScore = parseInt(el.predictionSlider.value);
        el.predictionValue.textContent = S.predictionScore;
    });

    // Auth modal events
    const authModal = document.getElementById('authModal');
    const closeAuthModal = document.getElementById('closeAuthModal');
    if (closeAuthModal) closeAuthModal.addEventListener('click', hideAuthModal);
    if (authModal) authModal.addEventListener('click', e => { if (e.target === authModal) hideAuthModal(); });

    const switchToRegister = document.getElementById('switchToRegister');
    if (switchToRegister) switchToRegister.addEventListener('click', e => { e.preventDefault(); showAuthModal('register'); });
    const switchToLogin = document.getElementById('switchToLogin');
    if (switchToLogin) switchToLogin.addEventListener('click', e => { e.preventDefault(); showAuthModal('login'); });

    const btnLogin = document.getElementById('btnLogin');
    if (btnLogin) btnLogin.addEventListener('click', async () => {
        const username = document.getElementById('loginUsername').value.trim();
        const password = document.getElementById('loginPassword').value;
        const errorEl = document.getElementById('loginError');
        if (!username || !password) {
            errorEl.textContent = '请输入用户名和密码';
            errorEl.style.display = '';
            return;
        }
        try {
            btnLogin.disabled = true;
            await doLogin(username, password);
            hideAuthModal();
            updateUserProfileUI();
            loadWeaknessProfile();
            loadSentence();
        } catch (e) {
            errorEl.textContent = e.message;
            errorEl.style.display = '';
        } finally {
            btnLogin.disabled = false;
        }
    });

    const btnRegister = document.getElementById('btnRegister');
    if (btnRegister) btnRegister.addEventListener('click', async () => {
        const username = document.getElementById('regUsername').value.trim();
        const displayName = document.getElementById('regDisplayName').value.trim();
        const password = document.getElementById('regPassword').value;
        const passwordConfirm = document.getElementById('regPasswordConfirm').value;
        const errorEl = document.getElementById('registerError');
        if (!username || !password) {
            errorEl.textContent = '请输入用户名和密码';
            errorEl.style.display = '';
            return;
        }
        if (password !== passwordConfirm) {
            errorEl.textContent = '两次密码不一致';
            errorEl.style.display = '';
            return;
        }
        try {
            btnRegister.disabled = true;
            await doRegister(username, password, displayName);
            hideAuthModal();
            updateUserProfileUI();
            loadSentence();
        } catch (e) {
            errorEl.textContent = e.message;
            errorEl.style.display = '';
        } finally {
            btnRegister.disabled = false;
        }
    });

    const btnGuestLogin = document.getElementById('btnGuestLogin');
    if (btnGuestLogin) btnGuestLogin.addEventListener('click', () => {
        doGuestLogin();
        hideAuthModal();
        updateUserProfileUI();
        loadSentence();
    });

    // btnNewUser removed - no user list/switcher anymore

    // User profile click -> show login dialog (not switcher)
    const userProfile = document.getElementById('userProfile');
    if (userProfile) userProfile.addEventListener('click', () => {
        if (S.user && S.user.id !== 'default') {
            // 已登录 -> 登出
            if (confirm('确定要退出登录吗？')) doLogout().then(() => updateUserProfileUI());
        } else {
            // 未登录 -> 弹出登录框
            showAuthModal('login');
        }
    });

    // Playback time update
    el.playbackAudio.addEventListener('timeupdate', () => {
        if (el.playbackAudio.duration) {
            const pct = (el.playbackAudio.currentTime / el.playbackAudio.duration) * 100;
            el.playbackFill.style.width = pct + '%';
            const m = Math.floor(el.playbackAudio.currentTime / 60);
            const s = Math.floor(el.playbackAudio.currentTime % 60);
            el.playbackTime.textContent = `${m}:${String(s).padStart(2,'0')}`;
        }
    });
    el.playbackAudio.addEventListener('ended', () => {
        S.playbackPlaying = false;
        el.btnPlayback.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>';
        el.playbackFill.style.width = '0%';
    });
}

// ============================================================
// Recording
// ============================================================
async function toggleRecording() {
    if (S.recording) stopRecording();
    else await startRecording();
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            audio: { channelCount:1, sampleRate:16000, echoCancellation:true, noiseSuppression:true }
        });
        S.stream = stream;
        S.chunks = [];
        S.recording = true;

        S.audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        const src = S.audioCtx.createMediaStreamSource(stream);
        S.analyser = S.audioCtx.createAnalyser();
        S.analyser.fftSize = 2048;
        src.connect(S.analyser);

        const processor = S.audioCtx.createScriptProcessor(4096, 1, 1);
        S.pcmChunks = [];
        processor.onaudioprocess = e => {
            if (S.recording) {
                S.pcmChunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
            }
        };
        src.connect(processor);
        processor.connect(S.audioCtx.destination);
        S.processor = processor;

        S.mediaRec = new MediaRecorder(stream, { mimeType: getMime() });
        S.mediaRec.ondataavailable = e => { if (e.data.size > 0) S.chunks.push(e.data); };
        S.mediaRec.onstop = onRecordStop;
        S.mediaRec.start(100);

        // UI updates
        el.recDot.classList.add('stop');
        el.recLabel.textContent = '停止录音';
        el.recInfo.style.display = 'flex';
        el.waveformPlaceholder.classList.add('hidden');
        el.playbackBar.style.display = 'none';
        el.resultCard.style.display = 'none';
        document.querySelector('.rec-ring').classList.add('active');

        // Start timer - record the start time
        S.recStart = Date.now();
        el.recTime.textContent = '0:00';
        if (S.recTimer) clearInterval(S.recTimer);
        S.recTimer = setInterval(updateRecTime, 200);
        // Force first update
        updateRecTime();

        // Start waveform visualization (re-init canvas first)
        requestAnimationFrame(() => {
            initCanvas();
            startWaveform();
        });
    } catch (e) {
        alert('无法访问麦克风，请确保已授予权限。');
    }
}

function stopRecording() {
    S.recording = false;
    if (S.mediaRec && S.mediaRec.state !== 'inactive') S.mediaRec.stop();
    if (S.processor) { S.processor.disconnect(); S.processor = null; }
    if (S.stream) S.stream.getTracks().forEach(t => t.stop());
    if (S.audioCtx) { S.audioCtx.close(); S.audioCtx = null; }

    el.recDot.classList.remove('stop');
    el.recLabel.textContent = '开始录音';
    el.recInfo.style.display = 'none';
    document.querySelector('.rec-ring').classList.remove('active');
    clearInterval(S.recTimer);
    S.recTimer = null;
    stopWaveform();
}

function onRecordStop() {
    if (S.pcmChunks && S.pcmChunks.length > 0) {
        const sampleRate = 16000; // Use 16000 since audioCtx may be closed
        const wavBlob = encodeWAV(S.pcmChunks, sampleRate);
        if (wavBlob.size > 1000) {
            S.recordedBlob = wavBlob;
            S.recordedUrl = URL.createObjectURL(wavBlob);
            el.playbackBar.style.display = 'flex';
            if (el.btnAB) el.btnAB.style.display = '';
            el.playbackAudio.src = S.recordedUrl;
            el.playbackFill.style.width = '0%';
            el.playbackTime.textContent = '0:00';
            return;
        }
    }

    const mime = S.mediaRec?.mimeType || 'audio/webm';
    S.recordedBlob = new Blob(S.chunks, { type: mime });
    S.recordedUrl = URL.createObjectURL(S.recordedBlob);

    if (S.recordedBlob.size < 1000) { alert('录音太短，请重试'); return; }

    el.playbackBar.style.display = 'flex';
    if (el.btnAB) el.btnAB.style.display = '';
    el.playbackAudio.src = S.recordedUrl;
    el.playbackFill.style.width = '0%';
    el.playbackTime.textContent = '0:00';
}

function encodeWAV(chunks, sampleRate) {
    const totalLen = chunks.reduce((s, c) => s + c.length, 0);
    const buffer = new ArrayBuffer(44 + totalLen * 2);
    const view = new DataView(buffer);

    const writeStr = (offset, str) => { for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i)); };
    writeStr(0, 'RIFF');
    view.setUint32(4, 36 + totalLen * 2, true);
    writeStr(8, 'WAVE');
    writeStr(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeStr(36, 'data');
    view.setUint32(40, totalLen * 2, true);

    let offset = 44;
    for (const chunk of chunks) {
        for (let i = 0; i < chunk.length; i++) {
            let s = Math.max(-1, Math.min(1, chunk[i]));
            s = s < 0 ? s * 0x8000 : s * 0x7FFF;
            view.setInt16(offset, s, true);
            offset += 2;
        }
    }

    return new Blob([buffer], { type: 'audio/wav' });
}

function updateRecTime() {
    if (!S.recStart) return;
    const sec = Math.floor((Date.now() - S.recStart) / 1000);
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    el.recTime.textContent = `${m}:${String(s).padStart(2,'0')}`;
}

function getMime() {
    const types = ['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus','audio/mp4'];
    for (const t of types) { if (MediaRecorder.isTypeSupported(t)) return t; }
    return '';
}

function togglePlayback() {
    if (!S.recordedUrl) return;
    if (S.playbackPlaying) {
        el.playbackAudio.pause();
        S.playbackPlaying = false;
        el.btnPlayback.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>';
    } else {
        el.playbackAudio.play();
        S.playbackPlaying = true;
        el.btnPlayback.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>';
    }
}

// ============================================================
// Waveform Visualization
// ============================================================
function initCanvas() {
    const c = el.waveformCanvas;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    const r = c.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) {
        // Canvas not visible yet - retry after layout
        setTimeout(() => {
            const r2 = c.getBoundingClientRect();
            if (r2.width > 0 && r2.height > 0) {
                c.width = r2.width * dpr;
                c.height = r2.height * dpr;
                const ctx = c.getContext('2d');
                ctx.scale(dpr, dpr);
                drawIdle(ctx, r2.width, r2.height);
            }
        }, 100);
        return;
    }
    c.width = r.width * dpr;
    c.height = r.height * dpr;
    const ctx = c.getContext('2d');
    ctx.scale(dpr, dpr);
    drawIdle(ctx, r.width, r.height);
}

function drawIdle(ctx, w, h) {
    ctx.clearRect(0, 0, w, h);
    const cy = h / 2;
    ctx.beginPath();
    ctx.strokeStyle = '#c7d2fe';
    ctx.lineWidth = 1.5;
    for (let x = 0; x < w; x++) {
        const y = cy + Math.sin(x * 0.04) * 2;
        x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.stroke();
}

function startWaveform() {
    const c = el.waveformCanvas;
    if (!c || !S.analyser) return;
    const dpr = window.devicePixelRatio || 1;
    const r = c.getBoundingClientRect();
    const w = r.width, h = r.height;
    if (w === 0 || h === 0) return;
    const ctx = c.getContext('2d');
    const bufLen = S.analyser.frequencyBinCount;
    const tData = new Uint8Array(bufLen);
    const fData = new Uint8Array(bufLen);

    function draw() {
        if (!S.recording || !S.analyser) return;
        S.analyser.getByteTimeDomainData(tData);
        S.analyser.getByteFrequencyData(fData);
        ctx.clearRect(0, 0, w, h);

        const bg = ctx.createLinearGradient(0, 0, 0, h);
        bg.addColorStop(0, 'rgba(79,70,229,0.02)');
        bg.addColorStop(1, 'rgba(79,70,229,0.06)');
        ctx.fillStyle = bg;
        ctx.fillRect(0, 0, w, h);

        // Waveform line
        ctx.lineWidth = 2;
        ctx.strokeStyle = '#4f46e5';
        ctx.beginPath();
        const sw = w / bufLen;
        let x = 0;
        for (let i = 0; i < bufLen; i++) {
            const y = (tData[i] / 128.0) * (h / 2);
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
            x += sw;
        }
        ctx.lineTo(w, h / 2);
        ctx.stroke();

        // Frequency bars
        const bc = 32, bw = w / bc - 2, step = Math.floor(bufLen / bc);
        for (let i = 0; i < bc; i++) {
            const v = fData[i * step] / 255;
            const bh = v * h * 0.25;
            const a = 0.25 + v * 0.5;
            ctx.fillStyle = `rgba(79,70,229,${a})`;
            ctx.fillRect(i * (bw + 2), h - bh, bw, bh);
        }

        S.animFrame = requestAnimationFrame(draw);
    }
    draw();
}

function stopWaveform() {
    if (S.animFrame) { cancelAnimationFrame(S.animFrame); S.animFrame = null; }
    const c = el.waveformCanvas;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    const r = c.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;
    const ctx = c.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
    drawIdle(ctx, r.width, r.height);
}

// ============================================================
// Submit Evaluation
// ============================================================
async function submitEvaluation() {
    if (!S.recordedBlob || !S.sentence) return;

    el.loadingCard.style.display = 'flex';
    el.resultCard.style.display = 'none';

    try {
        const fd = new FormData();
        const ext = S.recordedBlob.type.includes('wav') ? 'wav'
            : S.recordedBlob.type.includes('webm') ? 'webm'
            : S.recordedBlob.type.includes('ogg') ? 'ogg' : 'wav';
        fd.append('audio', S.recordedBlob, `rec.${ext}`);
        fd.append('sentence_text', S.sentence.text);

        const res = await fetchWithAuth(`${API}/api/evaluate`, { method: 'POST', body: fd });
        if (!res.ok) throw new Error(`评测失败 (${res.status})`);
        const data = await res.json();

        renderResults(data);
        updateStats(data);
    } catch (e) {
        alert('评测失败: ' + e.message);
    } finally {
        el.loadingCard.style.display = 'none';
    }
}

// ============================================================
// A/B Compare Playback
// ============================================================
function playAB() {
    if (!S.recordedUrl) return;
    S.abPhase = 'A';
    el.btnAB.classList.add('active');
    
    // Play TTS first (standard pronunciation)
    speakTTS();
    
    // After TTS ends, play user recording
    const checkTTS = setInterval(() => {
        if (S.ttsMode === 'browser') {
            if (!window.speechSynthesis.speaking) {
                clearInterval(checkTTS);
                S.abPhase = 'B';
                el.playbackAudio.currentTime = 0;
                el.playbackAudio.play();
                S.playbackPlaying = true;
                el.btnPlayback.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>';
            }
        } else {
            // Server TTS mode
            if (el.ttsAudio.paused || el.ttsAudio.ended) {
                clearInterval(checkTTS);
                setTimeout(() => {
                    S.abPhase = 'B';
                    el.playbackAudio.currentTime = 0;
                    el.playbackAudio.play();
                    S.playbackPlaying = true;
                    el.btnPlayback.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>';
                }, 300); // small gap between A and B
            }
        }
    }, 100);
    
    el.playbackAudio.onended = () => {
        S.playbackPlaying = false;
        S.abPhase = null;
        el.btnAB.classList.remove('active');
        el.btnPlayback.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>';
        el.playbackFill.style.width = '0%';
    };
}

// ============================================================
// Bookmark Functions
// ============================================================
async function toggleBookmark() {
    if (!S.sentence) return;
    const cardId = `sentence_${S.sentence.id}`;
    try {
        const r = await fetchWithAuth(`${API}/api/sentence-state`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ card_id: cardId, bookmarked: !S.bookmarked }),
        });
        if (r.ok) {
            S.bookmarked = !S.bookmarked;
            updateBookmarkUI();
        }
    } catch {}
}

function updateBookmarkUI() {
    if (!el.btnBookmark) return;
    el.btnBookmark.style.display = '';
    const svg = S.bookmarked 
        ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>'
        : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>';
    el.btnBookmark.innerHTML = svg;
    el.btnBookmark.style.color = S.bookmarked ? 'var(--warn)' : '';
}

// ============================================================
// Results
// ============================================================
function calibrateScore(raw) {
    // 后端scoring.py已经通过sigmoid映射将分数归一化到0-100范围
    // 不再需要二次校准，直接返回原始值
    if (raw < 0) return 0;
    if (raw > 100) return 100;
    return raw;
}

function renderResults(d) {
    el.resultCard.style.display = '';

    S.fsrsRated = false;
    document.querySelectorAll('.fsrs-btn').forEach(btn => btn.classList.remove('selected'));

    const calOverall = Math.round(calibrateScore(d.scores.overall));
    animNum(el.overallScore, calOverall, 1200);
    animRing(calOverall);
    animSub(el.pronVal, el.pronFill, Math.round(calibrateScore(d.scores.pronunciation)));
    animSub(el.compVal, el.compFill, Math.round(calibrateScore(d.scores.completeness)));
    animSub(el.fluVal, el.fluFill, Math.round(calibrateScore(d.scores.fluency)));

    renderWordScores(d.words || []);
    renderPhonemes(d);
    renderFluency(d.fluency_details || {});
    renderTips(d.tips || []);

    // Show calibration result if prediction was made
    showCalibrationResult(d.scores.overall);
    hidePredictionUI();

    setTimeout(() => el.resultCard.scrollIntoView({ behavior:'smooth', block:'start' }), 300);
}

function animNum(el, target, dur) {
    const t0 = performance.now();
    (function step(ts) {
        const p = Math.min((ts - t0) / dur, 1);
        el.textContent = Math.round((1 - Math.pow(1 - p, 3)) * target);
        if (p < 1) requestAnimationFrame(step);
    })(t0);
}

function animRing(score) {
    const circ = 326.73;
    const off = circ * (1 - score / 100);
    el.scoreRing.style.transition = 'stroke-dashoffset 1.2s cubic-bezier(.4,0,.2,1), stroke .5s';
    el.scoreRing.style.strokeDashoffset = off;
    el.scoreRing.style.stroke = score >= 80 ? '#22c55e' : score >= 60 ? '#4f46e5' : score >= 40 ? '#f59e0b' : '#ef4444';
}

function animSub(valEl, fillEl, v) {
    animNum(valEl, v, 900);
    setTimeout(() => fillEl.style.width = v + '%', 80);
}

function renderWordScores(words) {
    el.wordScoreGrid.innerHTML = words.map(w => {
        const calibratedAcc = Math.round(calibrateScore(w.accuracy));
        const c = calibratedAcc >= 80 ? 'hi' : calibratedAcc >= 50 ? 'md' : 'lo';
        const errorTitle = w.has_error ? `title="发音准确度: ${calibratedAcc}%"` : '';
        return `<div class="ws-item${w.has_error ? ' err' : ''}" ${errorTitle}><div class="ws-word">${w.word}</div><div class="ws-acc ${c}">${calibratedAcc}%</div></div>`;
    }).join('');
}

function renderPhonemes(d) {
    const exp = d.phonemes.expected;
    const act = d.phonemes.actual;
    const errs = d.errors || [];

    const errPos = new Map();
    errs.forEach(e => {
        if (e.type === 'substitution') errPos.set(e.position, e);
        else if (e.type === 'deletion') errPos.set(e.position, e);
    });

    el.phExpected.innerHTML = exp.map((p, i) => {
        const err = errPos.get(i);
        let cls = 'ok';
        let bgColor = 'background:rgba(34,197,94,0.08);';
        if (err) {
            if (err.type === 'substitution') {
                cls = 'bad';
                bgColor = 'background:rgba(239,68,68,0.12);';
            } else if (err.type === 'deletion') {
                cls = 'missing';
                bgColor = 'background:rgba(245,158,11,0.12);';
            }
        }
        const ipa = ARPABET_TO_IPA[p] || '';
        const ipaLabel = ipa ? `/${ipa}/` : '';
        return `<span class="ph-chip ${cls} clickable" style="${bgColor}" title="${ipaLabel} - 点击听发音" data-arpabet="${p}" onclick="pronounceResultPhoneme(this)">${ipa ? ipa : p}<span style="font-size:9px;opacity:0.6;margin-left:2px;">${p}</span></span>`;
    }).join('');

    el.phActual.innerHTML = act.map(p => {
        const isMatch = exp.includes(p);
        const cls = isMatch ? 'ok' : 'extra';
        const bgColor = isMatch ? 'background:rgba(34,197,94,0.08);' : 'background:rgba(239,68,68,0.08);';
        const ipa = ARPABET_TO_IPA[p] || '';
        const ipaLabel = ipa ? `/${ipa}/` : '';
        return `<span class="ph-chip ${cls} clickable" style="${bgColor}" title="${ipaLabel} - 点击听发音" data-arpabet="${p}" onclick="pronounceResultPhoneme(this)">${ipa ? ipa : p}<span style="font-size:9px;opacity:0.6;margin-left:2px;">${p}</span></span>`;
    }).join('');
}

async function pronounceResultPhoneme(chipEl) {
    const arpabet = chipEl.dataset.arpabet;
    if (!arpabet) return;

    chipEl.classList.add('playing');
    setTimeout(() => chipEl.classList.remove('playing'), 600);

    // Try IPA standard audio first (real human pronunciation)
    const played = await playIPAAudio(arpabet);
    if (played) return;

    // Fallback: TTS with example word
    playPhonemeTTSFallback(arpabet);
}

window.pronounceResultPhoneme = pronounceResultPhoneme;

function renderFluency(fd) {
    el.fluDuration.textContent = (fd.total_duration || 0) + 's';
    el.fluRate.textContent = (fd.speaking_rate || 0) + ' /s';
    el.fluPauses.textContent = fd.pause_count || 0;
    el.fluPauseDur.textContent = (fd.pause_duration || 0) + 's';
}

function renderTips(tips) {
    if (!tips.length) {
        el.tipsList.innerHTML = '<div class="tip-card low"><div class="tip-desc">发音很好！没有发现明显问题。</div></div>';
        return;
    }

    el.tipsList.innerHTML = tips.map(t => {
        let body = '';
        if (t.type === 'insertion') {
            body = `<p>${t.tip}</p>`;
        } else {
            body = `
                ${t.common_error ? `<p><strong>常见错误：</strong>${t.common_error}</p>` : ''}
                ${t.solution ? `<p><strong>纠正方法：</strong>${t.solution}</p>` : ''}
                ${t.mouth_shape ? `<p><strong>口型要点：</strong>${t.mouth_shape}</p>` : ''}
            `;
        }

        let practiceWords = '';
        if (t.practice_words && t.practice_words.length) {
            practiceWords = `<div class="tip-practice">${t.practice_words.map(w => `<span class="tip-pw">${w}</span>`).join('')}</div>`;
        }

        let minimalPair = '';
        if (t.minimal_pair) {
            const mp = t.minimal_pair;
            minimalPair = `
                <div class="tip-mp">
                    <strong>最小对立对训练 /${mp.pair[0]}/ vs /${mp.pair[1]}/</strong><br>
                    ${mp.native_issue ? `<em>母语干扰：${mp.native_issue}</em><br>` : ''}
                    绕口令练习：<strong>"${mp.drill_sentence}"</strong>
                </div>
            `;
        }

        const badge = t.type === 'substitution' ? '错读' : t.type === 'deletion' ? '漏读' : '多读';

        return `
        <div class="tip-card ${t.severity}">
            <div class="tip-header">
                <span class="tip-badge">${badge}</span>
                <span class="tip-desc">${t.description}</span>
            </div>
            <div class="tip-body">${body}</div>
            ${practiceWords}
            ${minimalPair}
        </div>`;
    }).join('');
}

// ============================================================
// Stats (Spaced Repetition + Error Pattern)
// ============================================================
function updateStats(data) {
    // 统计数据全部记录到服务端数据库（跨浏览器同步）
    // 不再使用 localStorage
    if (S.sentence) {
        try {
            const wordScores = (data.words || []).map(w => ({ word: w.word, accuracy: w.accuracy }));
            const errors = (data.errors || []).map(e => ({
                expected: e.expected || '',
                actual: e.actual || '',
                type: e.type || 'substitution',
            }));

            // Collect pronunciation error words (accuracy < 60)
            const pronunciationErrorWords = (data.words || [])
                .filter(w => w.accuracy < 60)
                .map(w => w.word);

            const evalBody = {
                sentence_id: `sentence_${S.sentence.id}`,
                overall_score: data.scores?.overall || 0,
                pronunciation_score: data.scores?.pronunciation || 0,
                completeness_score: data.scores?.completeness || 0,
                fluency_score: data.scores?.fluency || 0,
                errors: errors,
                word_scores: wordScores,
                duration: data.fluency_details?.total_duration || 0,
            };

            // Add pronunciation error words if any
            if (pronunciationErrorWords.length > 0) {
                evalBody.pronunciation_error_words = pronunciationErrorWords;
            }

            // Add prediction score if calibration is enabled
            if (S.calibrationEnabled && S.predictionScore !== null) {
                evalBody.prediction_score = S.predictionScore;
            }

            fetchWithAuth(`${API}/api/learning/record-evaluation`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(evalBody),
            }).catch(() => {});
        } catch {}
    }
}

function openStats() {
    // 先显示加载状态
    el.statsModalBody.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text3);"><div class="spinner" style="margin:0 auto 12px;"></div>加载统计数据...</div>';
    el.statsModal.style.display = 'flex';

    // 从服务端加载完整统计数据
    loadServerStats().then(stats => {
        if (!stats) {
            el.statsModalBody.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text3);">暂无统计数据，开始练习后即可查看</div>';
            return;
        }
        renderStatsContent(stats);
    });
}

function renderStatsContent(stats) {
    const scores = stats.recent_scores || [];
    const errors = stats.error_phonemes || {};
    const wordsLearned = stats.words_learned || {};
    const analytics = stats.analytics || {};
    const fsrsStats = stats.fsrs_stats || {};
    const weakness = stats.weakness || stats.analytics?.weakness || S.weaknessProfile;

    const totalPractice = stats.total_practice || 0;
    const avg = scores.length ? (scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(1) : 0;
    const best = scores.length ? Math.max(...scores) : 0;
    const wordsCount = Object.keys(wordsLearned).length;
    // Support both old format {phoneme: count} and new format {phoneme: {count, total, rate}}
    const totalErrorCount = Object.values(errors).reduce((a, b) => a + (typeof b === 'object' ? b.count : b), 0);
    const errorPhonemeCount = Object.keys(errors).length;

    // Greeting section
    const userName = S.user && S.user.id !== 'default' ? (S.user.display_name || S.user.username) : '学习者';
    const streakBadge = analytics.streak ?
        `<span class="streak-badge">🔥 ${analytics.streak}天连续学习</span>` : '';
    const improvementRate = analytics.improvement_rate;
    const improvementBadge = improvementRate !== undefined && improvementRate !== 0 ?
        `<span class="improvement-rate ${improvementRate > 0 ? 'positive' : improvementRate < 0 ? 'negative' : 'neutral'}">${improvementRate > 0 ? '↑' : improvementRate < 0 ? '↓' : '→'} ${Math.abs(improvementRate).toFixed(1)}分 ${improvementRate > 0 ? '进步' : '需加油'}</span>` : '';

    // Weakness heatmap
    let weaknessHTML = '';
    if (weakness && weakness.phoneme_weaknesses && weakness.phoneme_weaknesses.length > 0) {
        weaknessHTML = `
        <div class="stats-section">
            <div class="stats-section-header" onclick="toggleStatsCollapse('statsWeaknessCollapse')">
                <h4 class="stats-section-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--pri)" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
                    薄弱音素分析
                </h4>
                <div class="stats-section-summary">
                    <span class="stats-badge warn">${weakness.phoneme_weaknesses.length}个薄弱项</span>
                    <span class="stats-collapse-arrow" id="statsWeaknessCollapseArrow">▼</span>
                </div>
            </div>
            <div class="stats-section-body" id="statsWeaknessCollapse">
                <div class="weakness-heatmap">
                    ${weakness.phoneme_weaknesses.map(w => {
                        const ipa = ARPABET_TO_IPA[w.phoneme] || w.phoneme;
                        return `<span class="weakness-chip ${w.severity}" title="${w.phoneme}: 错误率${(w.error_rate*100).toFixed(0)}%, ${w.error_count}次">/${ipa}/</span>`;
                    }).join('')}
                </div>
                <p style="font-size:12px;color:var(--text3);margin-top:8px;">红色=严重困难 黄色=中等困难 蓝色=轻微困难</p>
            </div>
        </div>`;
    }

    // Recommendation
    let recommendationHTML = '';
    if (weakness && weakness.difficulty_level) {
        const diffLabel = {easy: '简单', medium: '中等', hard: '困难'}[weakness.difficulty_level] || weakness.difficulty_level;
        recommendationHTML = `
        <div class="stats-recommendation">
            <h5>💡 今日建议</h5>
            <p>根据你的学习表现，推荐练习<strong>${diffLabel}</strong>难度的句子。${weakness.word_weaknesses?.length > 0 ? `重点关注：${weakness.word_weaknesses.slice(0,5).map(w=>w.word).join('、')}` : ''}</p>
        </div>`;
    }

    // Error phonemes: full list sorted by frequency
    // Normalize error data: support both {phoneme: count} and {phoneme: {count, total, rate}}
    const allErrors = Object.entries(errors)
        .map(([p, v]) => [p, typeof v === 'object' ? v : {count: v, total: v, rate: 0}])
        .sort((a, b) => b[1].count - a[1].count);

    // Top 5 for summary
    const topErrorsSummary = allErrors.slice(0, 5)
        .map(([p, v]) => {
            const ipa = ARPABET_TO_IPA[p] || p;
            const rateStr = v.rate > 0 ? ` ${v.rate}%` : '';
            return `/${ipa}/ (${v.count}次${rateStr})`;
        })
        .join('、') || '暂无';

    // Weak words: words that have errors, low score, or are learning/relearning/due in FSRS
    const allWeakWords = Object.entries(wordsLearned)
        .filter(([_, d]) => {
            // 有 FSRS 数据的：非 mastered 状态
            if (d.fsrs_mastery) return d.fsrs_mastery !== 'mastered';
            // 有练习数据的：分数低于 70%
            if (d.attempts > 0) return d.best < 70;
            // 只有错误记录的
            return (d.dictation_errors > 0 || d.pronunciation_errors > 0);
        })
        .sort((a, b) => a[1].best - b[1].best);

    // Mastered words: FSRS mastered OR (high score AND no FSRS or FSRS mastered)
    const masteredWords = Object.entries(wordsLearned)
        .filter(([_, d]) => {
            // FSRS 标记为已掌握
            if (d.fsrs_mastery === 'mastered') return true;
            // 没有 FSRS 数据但发音分数高
            if (!d.fsrs_mastery && d.best >= 80 && d.attempts > 0) return true;
            return false;
        });

    // Score trend (last 10)
    const recentScores = scores.slice(0, 10);
    const scoreTrend = recentScores.length >= 2
        ? (recentScores[0] >= recentScores[recentScores.length - 1] ? '📈 上升趋势' : '📉 下降趋势')
        : '';

    // Build error phoneme detail HTML
    const errorDetailId = 'statsErrorDetail';
    const errorShowMoreId = 'statsErrorShowMore';
    const errorInitiallyShown = 5;
    let errorDetailHTML = '';
    if (allErrors.length === 0) {
        errorDetailHTML = '<p style="font-size:13px;color:var(--text3);padding:8px 0;">还没有发音错误记录，继续保持！</p>';
    } else {
        errorDetailHTML = allErrors.map(([p, v], i) => {
            const ipa = ARPABET_TO_IPA[p] || p;
            const c = v.count;
            const total = v.total || c;
            const severity = c >= 5 ? 'high' : c >= 3 ? 'medium' : 'low';
            const severityColor = c >= 5 ? 'var(--err)' : c >= 3 ? 'var(--warn)' : 'var(--pri)';
            const barWidth = Math.min(100, (c / (allErrors[0][1].count || 1)) * 100);
            const hidden = i >= errorInitiallyShown ? ' style="display:none;"' : '';
            const rateStr = v.rate > 0 ? `<span class="error-detail-rate" style="color:${severityColor};font-size:11px;margin-left:6px;">${v.rate}%读错</span>` : '';
            const totalStr = total > 0 ? `<span style="color:var(--text3);font-size:11px;margin-left:4px;">(${c}/${total})</span>` : '';
            return `<div class="error-detail-item" data-index="${i}"${hidden}>
                <div class="error-detail-header">
                    <span class="error-detail-ipa">/${ipa}/</span>
                    <span class="error-detail-arpabet">${p}</span>
                    <span class="error-detail-count" style="color:${severityColor};">${c}次</span>
                    ${totalStr}
                    ${rateStr}
                </div>
                <div class="error-detail-bar">
                    <div class="error-detail-bar-fill" style="width:${barWidth}%;background:${severityColor};"></div>
                </div>
            </div>`;
        }).join('');

        if (allErrors.length > errorInitiallyShown) {
            errorDetailHTML += `<button id="${errorShowMoreId}" class="stats-show-more" onclick="toggleStatsSection('${errorDetailId}', ${errorInitiallyShown}, ${allErrors.length}, '${errorShowMoreId}')">
                显示全部 ${allErrors.length} 个出错音素
            </button>`;
        }
    }

    // Build weak words detail HTML
    const weakDetailId = 'statsWeakDetail';
    const weakShowMoreId = 'statsWeakShowMore';
    const weakInitiallyShown = 8;
    let weakDetailHTML = '';
    if (allWeakWords.length === 0) {
        weakDetailHTML = '<p style="font-size:13px;color:var(--text3);padding:8px 0;">所有单词掌握良好！</p>';
    } else {
        weakDetailHTML = allWeakWords.map(([w, d], i) => {
            const barColor = d.best >= 50 ? 'var(--warn)' : 'var(--err)';
            const hidden = i >= weakInitiallyShown ? ' style="display:none;"' : '';
            return `<div class="weak-word-item" data-index="${i}"${hidden}>
                <span class="weak-word-name">${w}</span>
                <div class="weak-word-bar"><div class="weak-word-bar-fill" style="width:${d.best}%;background:${barColor};"></div></div>
                <span class="weak-word-score" style="color:${barColor};">${d.best}%</span>
                <span class="weak-word-attempts">${d.attempts}次</span>
            </div>`;
        }).join('');

        if (allWeakWords.length > weakInitiallyShown) {
            weakDetailHTML += `<button id="${weakShowMoreId}" class="stats-show-more" onclick="toggleStatsSection('${weakDetailId}', ${weakInitiallyShown}, ${allWeakWords.length}, '${weakShowMoreId}')">
                显示全部 ${allWeakWords.length} 个待复习单词
            </button>`;
        }
    }

    el.statsModalBody.innerHTML = `
        <div class="stats-greeting">
            <h4>👋 你好，${userName}！</h4>
            <p>${streakBadge} ${improvementBadge}</p>
        </div>

        ${recommendationHTML}

        <!-- Progress & Motivation Section -->
        <div class="stats-progress-section" style="margin-bottom:16px;">
            <div style="display:flex;gap:10px;flex-wrap:wrap;">
                <div class="stat-card" style="flex:1;min-width:100px;text-align:center;">
                    <div style="font-size:24px;">🎯</div>
                    <div class="sc-val">${masteredWords.length}</div>
                    <div class="sc-label">已掌握</div>
                    <div style="font-size:10px;color:var(--ok);margin-top:2px;">${wordsCount > 0 ? Math.round(masteredWords.length / wordsCount * 100) : 0}% 达标率</div>
                </div>
                <div class="stat-card" style="flex:1;min-width:100px;text-align:center;">
                    <div style="font-size:24px;">${analytics.streak > 0 ? '🔥' : '💡'}</div>
                    <div class="sc-val">${analytics.streak || 0}</div>
                    <div class="sc-label">连续天数</div>
                    <div style="font-size:10px;color:var(--warn);margin-top:2px;">${analytics.streak >= 7 ? '太棒了！' : analytics.streak >= 3 ? '坚持住！' : '加油！'}</div>
                </div>
                <div class="stat-card" style="flex:1;min-width:100px;text-align:center;">
                    <div style="font-size:24px;">${improvementRate > 0 ? '📈' : improvementRate < 0 ? '📉' : '➡️'}</div>
                    <div class="sc-val">${improvementRate > 0 ? '+' : ''}${(improvementRate || 0).toFixed(1)}</div>
                    <div class="sc-label">进步分</div>
                    <div style="font-size:10px;color:${improvementRate > 0 ? 'var(--ok)' : improvementRate < 0 ? 'var(--err)' : 'var(--text3)'};margin-top:2px;">${improvementRate > 5 ? '显著进步！' : improvementRate > 0 ? '稳步提升' : '继续努力'}</div>
                </div>
                <div class="stat-card" style="flex:1;min-width:100px;text-align:center;">
                    <div style="font-size:24px;">✏️</div>
                    <div class="sc-val">${allWeakWords.length}</div>
                    <div class="sc-label">待加强</div>
                    <div style="font-size:10px;color:var(--warn);margin-top:2px;">刻意练习</div>
                </div>
            </div>
            ${allWeakWords.length > 0 && allWeakWords.length <= 10 ? `
            <div style="margin-top:10px;padding:10px 12px;background:rgba(99,102,241,0.08);border-radius:8px;font-size:12px;color:var(--text2);">
                <strong>💡 刻意练习建议：</strong>重点练习 ${allWeakWords.slice(0,5).map(([w]) => `<span style="color:var(--pri);font-weight:600;">${w}</span>`).join('、')}，重复练习薄弱项比广撒网更有效！
            </div>` : ''}
        </div>

        <!-- 认知画像 Section -->
        <div class="stats-cognitive-profile" id="statsCognitiveProfile">
            <div class="stats-cognitive-icon">🧠</div>
            <div class="stats-cognitive-name">加载中...</div>
            <div class="stats-cognitive-mini-metrics" id="statsCognitiveMetrics"></div>
        </div>

        <div class="stats-grid">
            <div class="stat-card"><div class="sc-val">${totalPractice}</div><div class="sc-label">练习次数</div></div>
            <div class="stat-card"><div class="sc-val">${avg}</div><div class="sc-label">平均分</div></div>
            <div class="stat-card"><div class="sc-val">${best}</div><div class="sc-label">最高分</div></div>
            <div class="stat-card"><div class="sc-val">${wordsCount}</div><div class="sc-label">已学单词</div></div>
        </div>

        ${scoreTrend ? `<div style="margin-bottom:12px;padding:10px 12px;background:#f0fdf4;border-radius:8px;text-align:center;font-size:13px;font-weight:600;color:#166534;">
            ${scoreTrend}（最近${recentScores.length}次）
        </div>` : ''}

        ${S.pendingReviewCount > 0 ? `
        <div style="margin-bottom:12px;padding:12px;background:#eef2ff;border-radius:8px;text-align:center;cursor:pointer;" onclick="loadSentence()">
            <span style="font-size:14px;font-weight:700;color:var(--pri);">${S.pendingReviewCount} 句待复习</span>
            <span style="font-size:12px;color:var(--text3);margin-left:8px;">点击练习</span>
        </div>` : ''}
        ${S.pendingWordReviewCount > 0 ? `
        <div style="margin-bottom:12px;padding:12px;background:#fef3e2;border-radius:8px;text-align:center;cursor:pointer;" onclick="openWordReview()">
            <span style="font-size:14px;font-weight:700;color:var(--warn);">${S.pendingWordReviewCount} 词待复习</span>
            <span style="font-size:12px;color:var(--text3);margin-left:8px;">点击复习</span>
        </div>` : ''}

        ${weaknessHTML}

        <!-- 发音错误统计 -->
        <div class="stats-section">
            <div class="stats-section-header" onclick="toggleStatsCollapse('statsErrorCollapse')">
                <h4 class="stats-section-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--err)" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    发音错误统计
                </h4>
                <div class="stats-section-summary">
                    ${errorPhonemeCount > 0 ? `<span class="stats-badge error">${errorPhonemeCount}个音素</span><span class="stats-badge error">${totalErrorCount}次错误</span>` : '<span class="stats-badge ok">零错误</span>'}
                    <span class="stats-collapse-arrow" id="statsErrorCollapseArrow">▼</span>
                </div>
            </div>
            <div class="stats-section-body" id="statsErrorCollapse">
                ${errorPhonemeCount > 0 ? `<div class="stats-summary-bar">
                    最频繁：${topErrorsSummary}
                </div>` : ''}
                <div id="${errorDetailId}">
                    ${errorDetailHTML}
                </div>
            </div>
        </div>

        <!-- 单词掌握情况 -->
        <div class="stats-section">
            <div class="stats-section-header" onclick="toggleStatsCollapse('statsWordsCollapse')">
                <h4 class="stats-section-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--pri)" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
                    单词掌握情况
                </h4>
                <div class="stats-section-summary">
                    ${stats.word_review_stats ? `<span class="stats-badge ok">${stats.word_review_stats.mastered || 0}已掌握</span><span class="stats-badge warn">${stats.word_review_stats.due || 0}待复习</span>` : ''}
                    ${masteredWords.length > 0 ? `<span class="stats-badge ok">${masteredWords.length}发音达标</span>` : ''}
                    ${allWeakWords.length > 0 ? `<span class="stats-badge warn">${allWeakWords.length}待加强</span>` : ''}
                    <span class="stats-collapse-arrow" id="statsWordsCollapseArrow">▼</span>
                </div>
            </div>
            <div class="stats-section-body" id="statsWordsCollapse">
                ${allWeakWords.length > 0 ? `
                <div class="stats-sub-title">需要加强的单词</div>
                <div id="${weakDetailId}">
                    ${weakDetailHTML}
                </div>
                ` : '<p style="font-size:13px;color:var(--text3);padding:8px 0;">所有单词掌握良好！</p>'}

                ${masteredWords.length > 0 ? `
                <div class="stats-sub-title" style="margin-top:14px;">已掌握的单词 <span style="font-weight:400;color:var(--text3);">(${masteredWords.length}个)</span></div>
                <div class="mastered-words-grid" id="masteredWordsGrid">
                    ${masteredWords.slice(0, 30).map(([w, d]) =>
                        `<span class="mastered-word">${w}</span>`
                    ).join('')}
                    ${masteredWords.length > 30 ? `<button class="mastered-word-more" onclick="this.parentElement.querySelectorAll('.mastered-word-hidden').forEach(e=>e.style.display='');this.remove();" style="cursor:pointer;background:none;border:1px dashed var(--border);border-radius:4px;padding:2px 8px;color:var(--text3);font-size:12px;">+${masteredWords.length - 30}个 (点击展开)</button>
                    ${masteredWords.slice(30).map(([w, d]) =>
                        `<span class="mastered-word mastered-word-hidden" style="display:none;">${w}</span>`
                    ).join('')}` : ''}
                </div>
                ` : ''}
            </div>
        </div>

        <!-- 最近得分 -->
        <div class="stats-section">
            <div class="stats-section-header" onclick="toggleStatsCollapse('statsProgressCollapse')">
                <h4 class="stats-section-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--pri)" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
                    最近得分
                </h4>
                <span class="stats-collapse-arrow" id="statsProgressCollapseArrow">▼</span>
            </div>
            <div class="stats-section-body" id="statsProgressCollapse">
                ${scores.length > 0 ? `
                <div class="score-history">
                    ${scores.slice(0, 20).reverse().map((score, i) => {
                        const color = score >= 80 ? 'var(--ok)' : score >= 60 ? 'var(--pri)' : score >= 40 ? 'var(--warn)' : 'var(--err)';
                        const height = Math.max(4, score);
                        return `<div class="score-bar-item" title="${score}分">
                            <div class="score-bar-fill" style="height:${height}%;background:${color};"></div>
                        </div>`;
                    }).join('')}
                </div>
                <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text3);margin-top:4px;">
                    <span>较早</span><span>最近</span>
                </div>
                ` : '<p style="font-size:13px;color:var(--text3);padding:8px 0;">暂无得分记录</p>'}
            </div>
        </div>

        <!-- 语义场覆盖 Section -->
        <div class="stats-section">
            <div class="stats-section-header" onclick="toggleStatsCollapse('statsSemanticCollapse')">
                <h4 class="stats-section-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent-blue)" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                    语义场覆盖
                </h4>
                <span class="stats-collapse-arrow" id="statsSemanticCollapseArrow">▼</span>
            </div>
            <div class="stats-section-body" id="statsSemanticCollapse">
                <div id="statsSemanticCoverage">
                    <p style="font-size:13px;color:var(--text3);padding:8px 0;">语义场数据加载中...</p>
                </div>
            </div>
        </div>

        <!-- 探索/利用 Section -->
        <div class="stats-section">
            <div class="stats-section-header" onclick="toggleStatsCollapse('statsEECollapse')">
                <h4 class="stats-section-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent-orange)" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
                    探索/利用
                </h4>
                <span class="stats-collapse-arrow" id="statsEECollapseArrow">▼</span>
            </div>
            <div class="stats-section-body" id="statsEECollapse">
                <div class="stats-explore-exploit" id="statsEEContent">
                    <p style="font-size:13px;color:var(--text3);">探索/利用数据加载中...</p>
                </div>
            </div>
        </div>

        ${S.calibrationEnabled ? `
        <!-- 校准分数 Section -->
        <div class="stats-section">
            <div class="stats-section-header" onclick="toggleStatsCollapse('statsCalibrationCollapse')">
                <h4 class="stats-section-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--warn)" stroke-width="2"><path d="M12 20V10M18 20V4M6 20v-6"/></svg>
                    校准分数
                </h4>
                <span class="stats-collapse-arrow" id="statsCalibrationCollapseArrow">▼</span>
            </div>
            <div class="stats-section-body" id="statsCalibrationCollapse">
                <div class="stats-calibration" id="statsCalibrationContent">
                    <h5>🎯 预测校准</h5>
                    <p>校准数据加载中...</p>
                </div>
            </div>
        </div>
        ` : ''}

        <!-- 成就系统 -->
        <div class="stats-section">
            <div class="stats-section-header" onclick="toggleStatsCollapse('statsAchievementCollapse')">
                <h4 class="stats-section-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--warn)" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
                    学习成就
                </h4>
                <div class="stats-section-summary">
                    <span class="stats-badge warn" id="achievementCount">加载中...</span>
                    <span class="stats-collapse-arrow" id="statsAchievementCollapseArrow">▼</span>
                </div>
            </div>
            <div class="stats-section-body" id="statsAchievementCollapse">
                <div id="achievementContent">
                    <div style="text-align:center;padding:20px;color:var(--text3);font-size:13px;">加载成就...</div>
                </div>
            </div>
        </div>

        <!-- 针对性建议 -->
        <div class="stats-section">
            <div class="stats-section-header" onclick="toggleStatsCollapse('statsInsightCollapse')">
                <h4 class="stats-section-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--pri)" stroke-width="2"><path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>
                    针对性建议
                </h4>
                <span class="stats-collapse-arrow" id="statsInsightCollapseArrow">▼</span>
            </div>
            <div class="stats-section-body" id="statsInsightCollapse">
                <div id="insightContent">
                    <div style="text-align:center;padding:20px;color:var(--text3);font-size:13px;">分析学习中...</div>
                </div>
            </div>
        </div>

        <!-- 练习热力图 -->
        <div class="stats-section">
            <div class="stats-section-header" onclick="toggleStatsCollapse('statsHeatmapCollapse')">
                <h4 class="stats-section-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--ok)" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
                    练习热力图
                </h4>
                <span class="stats-collapse-arrow" id="statsHeatmapCollapseArrow">▼</span>
            </div>
            <div class="stats-section-body" id="statsHeatmapCollapse">
                <div class="heatmap-container" id="heatmapContainer">
                    <div style="text-align:center;padding:20px;color:var(--text3);font-size:13px;">加载热力图...</div>
                </div>
            </div>
        </div>
    `;

    // Load enhanced stats sections asynchronously
    loadEnhancedStatsSections(stats);
}

// Toggle show more/less in stats sections
function toggleStatsSection(containerId, initialCount, totalCount, buttonId) {
    const container = document.getElementById(containerId);
    const button = document.getElementById(buttonId);
    if (!container || !button) return;

    const items = container.querySelectorAll('[data-index]');
    const isExpanded = button.textContent.includes('收起');

    items.forEach(item => {
        const idx = parseInt(item.dataset.index);
        if (isExpanded) {
            item.style.display = idx >= initialCount ? 'none' : '';
        } else {
            item.style.display = '';
        }
    });

    button.textContent = isExpanded
        ? `显示全部 ${totalCount} 项`
        : '收起';
}

// Toggle collapse for stats sections
function toggleStatsCollapse(sectionId) {
    const section = document.getElementById(sectionId);
    if (!section) return;
    const isCollapsed = section.classList.contains('stats-collapsed');
    section.classList.toggle('stats-collapsed', !isCollapsed);
    const arrowId = sectionId.replace('Collapse', 'CollapseArrow');
    const arrow = document.getElementById(arrowId);
    if (arrow) arrow.style.transform = isCollapsed ? '' : 'rotate(-90deg)';
}

// ============================================================
// Heatmap Rendering
// ============================================================
function renderHeatmap(container, heatmapData) {
    const COLORS = ['#ebedf0', '#9be9a8', '#40c463', '#30a14e', '#216e39'];
    const now = new Date();
    const days = 365;
    
    // Build date array for last 365 days
    // Use local date format (YYYY-MM-DD) to match backend's DATE(..., 'localtime')
    const dates = [];
    for (let i = days - 1; i >= 0; i--) {
        const d = new Date(now);
        d.setDate(d.getDate() - i);
        // Format as local YYYY-MM-DD to match SQL's DATE(..., 'localtime')
        const key = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
        dates.push({ date: key, day: d.getDay(), count: heatmapData[key]?.count || 0, avg: heatmapData[key]?.avg_score || 0 });
    }
    
    // Calculate total and streak
    const totalDays = dates.filter(d => d.count > 0).length;
    const totalPractice = dates.reduce((s, d) => s + d.count, 0);
    
    // Current streak
    let streak = 0;
    for (let i = dates.length - 1; i >= 0; i--) {
        if (dates[i].count > 0) streak++;
        else break;
    }
    
    // Build month labels
    const months = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'];
    const monthLabels = [];
    let lastMonth = -1;
    dates.forEach((d, i) => {
        const m = new Date(d.date).getMonth();
        const week = Math.floor(i / 7);
        if (m !== lastMonth) {
            monthLabels.push({ label: months[m], week });
            lastMonth = m;
        }
    });
    
    // Render
    let html = `
    <div class="heatmap-summary">
        <span>${totalPractice} 次练习</span>
        <span>过去一年 ${totalDays} 天活跃</span>
        ${streak > 0 ? `<span style="color:var(--ok);">🔥 当前连续 ${streak} 天</span>` : ''}
    </div>
    <div class="heatmap-wrap">
        <div class="heatmap-months">${monthLabels.map(m => `<span style="grid-column:${m.week + 1}">${m.label}</span>`).join('')}</div>
        <div class="heatmap-grid">
            <div class="heatmap-weekdays">
                <span>一</span><span></span><span>三</span><span></span><span>五</span><span></span>
            </div>
            <div class="heatmap-cells">`;
    
    dates.forEach(d => {
        const level = d.count === 0 ? 0 : d.count <= 1 ? 1 : d.count <= 3 ? 2 : d.count <= 5 ? 3 : 4;
        const title = `${d.date}: ${d.count} 次练习${d.avg > 0 ? `，平均 ${d.avg} 分` : ''}`;
        html += `<span class="heatmap-cell level-${level}" title="${title}"></span>`;
    });
    
    html += `</div></div></div>
        <div class="heatmap-legend">
            <span>少</span>
            ${COLORS.map(c => `<span class="heatmap-cell" style="background:${c};"></span>`).join('')}
            <span>多</span>
        </div>
    </div>`;
    
    container.innerHTML = html;
}

// ============================================================
// Enhanced Stats Sections Loader
// ============================================================
async function loadEnhancedStatsSections(stats) {
    // Load cognitive profile
    try {
        const r = await fetchWithAuth(`${API}/api/metacognition/profile`);
        if (r.ok) {
            const profile = await r.json();
            const cpEl = document.getElementById('statsCognitiveProfile');
            const cmEl = document.getElementById('statsCognitiveMetrics');
            if (cpEl && cmEl) {
                cpEl.querySelector('.stats-cognitive-icon').textContent = profile.archetype_icon || '🧠';
                cpEl.querySelector('.stats-cognitive-name').textContent = profile.archetype_name || '学习者';
                const metrics = profile.metrics || {};
                cmEl.innerHTML = `
                    <div class="stats-cognitive-metric"><span class="val">${Math.round((metrics.speed || 0) * 100)}%</span>速度</div>
                    <div class="stats-cognitive-metric"><span class="val">${Math.round((metrics.retention || 0) * 100)}%</span>保持</div>
                    <div class="stats-cognitive-metric"><span class="val">${Math.round((metrics.coverage || 0) * 100)}%</span>覆盖</div>
                `;
            }
        }
    } catch { /* degrade */ }

    // Load semantic field coverage
    try {
        const r = await fetchWithAuth(`${API}/api/semantic/field-coverage`);
        if (r.ok) {
            const data = await r.json();
            const el = document.getElementById('statsSemanticCoverage');
            if (el) {
                // Backend returns {coverage: [{field, total_words, learned_words, coverage_ratio}]}
                const fields = data.coverage || data.fields || [];
                if (fields.length === 0) {
                    el.innerHTML = '<p style="font-size:12px;color:var(--text3);">暂无语义场数据，开始练习后将自动构建</p>';
                } else {
                    const colors = ['#3498db', '#27ae60', '#e67e22', '#8b5cf6', '#e74c3c', '#1abc9c'];
                    el.innerHTML = fields.map((f, i) => {
                        const name = f.field || f.name || '未知';
                        const pct = f.coverage_ratio !== undefined ? f.coverage_ratio : (f.pct || 0);
                        const learned = f.learned_words || 0;
                        const total = f.total_words || 0;
                        return `<div class="stats-field-bar">
                            <span class="stats-field-name">${name}</span>
                            <div class="stats-field-track">
                                <div class="stats-field-fill" style="width:${Math.round(pct * 100)}%;background:${colors[i % colors.length]};"></div>
                            </div>
                            <span class="stats-field-pct">${Math.round(pct * 100)}% <span style="font-size:10px;color:var(--text3);">(${learned}/${total})</span></span>
                        </div>`;
                    }).join('');
                }
            }
        } else {
            const el = document.getElementById('statsSemanticCoverage');
            if (el) el.innerHTML = '<p style="font-size:12px;color:var(--text3);">语义场数据暂不可用</p>';
        }
    } catch { 
        const el = document.getElementById('statsSemanticCoverage');
        if (el) el.innerHTML = '<p style="font-size:12px;color:var(--text3);">语义场数据加载失败</p>';
    }

    // Load explore/exploit ratio
    try {
        const r = await fetchWithAuth(`${API}/api/learning/explore-exploit`);
        if (r.ok) {
            const data = await r.json();
            const el = document.getElementById('statsEEContent');
            if (el) {
                const explorePct = Math.round((data.explore_ratio || 0.3) * 100);
                const exploitPct = 100 - explorePct;
                const totalReviews = data.total_reviews || 0;
                el.innerHTML = `
                    <div class="stats-ee-chart">
                        <div class="stats-pie" style="--explore-pct:${explorePct}%;">
                            <div class="stats-pie-center">${explorePct}%</div>
                        </div>
                        <div class="stats-ee-legend">
                            <div class="stats-ee-item"><span class="stats-ee-dot" style="background:var(--pri);"></span> 探索 (新内容) ${explorePct}%</div>
                            <div class="stats-ee-item"><span class="stats-ee-dot" style="background:var(--ok);"></span> 利用 (复习) ${exploitPct}%</div>
                        </div>
                    </div>
                    <p style="font-size:12px;color:var(--text3);margin-top:10px;">探索率越高越倾向学习新内容，利用率高则侧重巩固已学内容。共 ${totalReviews} 次复习</p>
                `;
            }
        } else {
            const el = document.getElementById('statsEEContent');
            if (el) el.innerHTML = '<p style="font-size:12px;color:var(--text3);">探索/利用数据暂不可用</p>';
        }
    } catch { 
        const el = document.getElementById('statsEEContent');
        if (el) el.innerHTML = '<p style="font-size:12px;color:var(--text3);">探索/利用数据加载失败</p>';
    }

    // Load calibration data
    if (S.calibrationEnabled) {
        try {
            const r = await fetchWithAuth(`${API}/api/metacognition/calibration`);
            if (r.ok) {
                const data = await r.json();
                const el = document.getElementById('statsCalibrationContent');
                if (el) {
                    const avgDeviation = data.average_deviation || 0;
                    const calibrationScore = data.calibration_score || 0;
                    const direction = avgDeviation > 0 ? '高估' : '低估';
                    el.innerHTML = `
                        <h5>🎯 预测校准</h5>
                        <p>平均偏差: <strong style="color:${Math.abs(avgDeviation) <= 10 ? 'var(--ok)' : 'var(--warn)'};">${direction} ${Math.abs(avgDeviation).toFixed(1)}分</strong></p>
                        <p>校准分数: <strong>${Math.round(calibrationScore * 100)}%</strong></p>
                        <p style="margin-top:6px;font-size:11px;color:var(--text3);">校准分数越高，你的自我评估越准确</p>
                    `;
                }
            }
        } catch { /* degrade */ }
    }

    // Load heatmap data
    try {
        const r = await fetchWithAuth(`${API}/api/stats/heatmap`);
        if (r.ok) {
            const data = await r.json();
            const container = document.getElementById('heatmapContainer');
            if (container && data.heatmap) {
                renderHeatmap(container, data.heatmap);
            }
        }
    } catch { /* degrade */ }

    // Load achievements
    try {
        const r = await fetchWithAuth(`${API}/api/achievements`);
        if (r.ok) {
            const data = await r.json();
            const el = document.getElementById('achievementContent');
            const countEl = document.getElementById('achievementCount');
            if (el) {
                const unlocked = data.unlocked || [];
                const locked = data.locked || [];
                const total = data.total_achievements || 0;
                if (countEl) countEl.textContent = `${data.total_unlocked || 0}/${total}`;
                
                let html = '';
                if (unlocked.length > 0) {
                    html += '<div class="achievement-grid">';
                    unlocked.forEach(a => {
                        html += `<div class="achievement-item unlocked" title="${a.desc}">
                            <span class="achievement-icon">${a.icon}</span>
                            <span class="achievement-name">${a.name}</span>
                        </div>`;
                    });
                    html += '</div>';
                }
                if (locked.length > 0) {
                    html += '<div class="achievement-grid locked">';
                    locked.slice(0, 6).forEach(a => {
                        html += `<div class="achievement-item locked" title="${a.desc}">
                            <span class="achievement-icon">🔒</span>
                            <span class="achievement-name">${a.name}</span>
                        </div>`;
                    });
                    if (locked.length > 6) {
                        html += `<div class="achievement-item locked more" title="还有${locked.length - 6}个成就待解锁">
                            <span class="achievement-icon">...</span>
                            <span class="achievement-name">+${locked.length - 6}更多</span>
                        </div>`;
                    }
                    html += '</div>';
                }
                if (unlocked.length === 0 && locked.length > 0) {
                    html = '<p style="font-size:13px;color:var(--text3);padding:8px 0;">继续练习来解锁你的第一个成就！🌟</p>' + html;
                }
                el.innerHTML = html;
            }
        }
    } catch { /* degrade */ }

    // Load learning insights
    try {
        const r = await fetchWithAuth(`${API}/api/learning/insights`);
        if (r.ok) {
            const data = await r.json();
            const el = document.getElementById('insightContent');
            if (el) {
                let html = '';
                if (data.top_insight) {
                    html += `<div class="insight-item main">
                        <span class="insight-icon">💡</span>
                        <span class="insight-text">${data.top_insight}</span>
                    </div>`;
                }
                if (data.action_items && data.action_items.length > 0) {
                    html += '<div class="insight-section"><h5 style="font-size:12px;color:var(--pri);margin:8px 0 4px;">🎯 行动建议</h5>';
                    data.action_items.forEach(item => {
                        html += `<div class="insight-item action">
                            <span class="insight-bullet">→</span>
                            <span class="insight-text">${item}</span>
                        </div>`;
                    });
                    html += '</div>';
                }
                if (data.positive_feedback && data.positive_feedback.length > 0) {
                    html += '<div class="insight-section"><h5 style="font-size:12px;color:var(--ok);margin:8px 0 4px;">✅ 做得好的</h5>';
                    data.positive_feedback.forEach(item => {
                        html += `<div class="insight-item positive">
                            <span class="insight-text">${item}</span>
                        </div>`;
                    });
                    html += '</div>';
                }
                if (!html) {
                    html = '<p style="font-size:13px;color:var(--text3);padding:8px 0;">练习更多内容后，系统将为你生成个性化建议</p>';
                }
                el.innerHTML = html;
            }
        }
    } catch { /* degrade */ }
}

// ============================================================
// Phoneme Guide (with IPA prominent + clickable to pronounce)
// ============================================================
function openPhonemeGuide() {
    if (!S.phonemeTips) { alert('音素指南加载中...'); return; }

    const groups = {
        '元音 - 短元音': ['AA','AE','AH','EH','IH','UH'],
        '元音 - 长元音/双元音': ['AY','AW','EY','OW','OY','IY','UW'],
        '元音 - R色元音': ['ER'],
        '辅音 - 塞音': ['P','B','T','D','K','G'],
        '辅音 - 擦音': ['F','V','S','Z','SH','ZH','TH','DH'],
        '辅音 - 塞擦音': ['CH','JH'],
        '辅音 - 鼻音': ['M','N','NG'],
        '辅音 - 流音/滑音': ['L','R','W','Y','HH'],
    };

    let html = '';
    for (const [group, phonemes] of Object.entries(groups)) {
        html += `<h4 style="font-size:13px;font-weight:700;color:var(--text2);margin:14px 0 8px;padding-top:10px;border-top:1px solid var(--border);">${group}</h4>`;
        html += '<div class="phoneme-guide-grid">';
        for (const p of phonemes) {
            const t = S.phonemeTips[p];
            if (!t) continue;
            const ipa = t.ipa || ARPABET_TO_IPA[p] || '';
            html += `
            <div class="pg-item" onclick="pronouncePhonemeGuide('${p}')" title="点击听发音">
                <div class="pg-header">
                    <span class="pg-ipa" style="font-size:22px;font-weight:800;color:var(--pri);">/${ipa}/</span>
                    <span class="pg-symbol" style="font-size:13px;color:var(--text3);">${p}</span>
                </div>
                <div class="pg-desc">${t.description}</div>
                <div class="pg-detail">
                    <p><strong>常见错误：</strong>${t.common_error}</p>
                    <p><strong>纠正方法：</strong>${t.solution}</p>
                    <p><strong>口型：</strong>${t.mouth_shape}</p>
                </div>
                ${t.practice_words?.length ? `<div class="pg-words">${t.practice_words.map(w => `<span class="tip-pw">${w}</span>`).join('')}</div>` : ''}
            </div>`;
        }
        html += '</div>';
    }

    el.phonemeModalBody.innerHTML = html;
    el.phonemeModal.style.display = 'flex';
}

async function pronouncePhonemeGuide(arpabet) {
    // Try IPA standard audio first (real human pronunciation)
    const played = await playIPAAudio(arpabet);
    if (played) return;

    // Fallback: use browser SpeechSynthesis with practice word
    if ('speechSynthesis' in window && S.phonemeTips && S.phonemeTips[arpabet]) {
        const words = S.phonemeTips[arpabet].practice_words;
        if (words && words.length > 0) {
            const word = words[0].split(' ')[0];
            const utter = new SpeechSynthesisUtterance(word);
            utter.lang = 'en-US';
            utter.rate = 0.6;
            const voices = speechSynthesis.getVoices();
            const usVoice = voices.find(v => v.lang === 'en-US') || voices.find(v => v.lang.startsWith('en'));
            if (usVoice) utter.voice = usVoice;
            speechSynthesis.cancel();
            speechSynthesis.speak(utter);
        }
    }
}

window.pronouncePhonemeGuide = pronouncePhonemeGuide;

// ============================================================
// Resize
// ============================================================
window.addEventListener('resize', initCanvas);

// ============================================================
// Learning Mode Management
// ============================================================
function loadLearningMode() {
    try {
        const saved = localStorage.getItem('phonos_learning_mode');
        if (saved === 'sequential' || saved === 'smart') {
            S.learningMode = saved;
        }
    } catch {}
    updateModeSelectorUI();
}

function saveLearningMode(mode) {
    S.learningMode = mode;
    try {
        localStorage.setItem('phonos_learning_mode', mode);
    } catch {}
    updateModeSelectorUI();
}

function updateModeSelectorUI() {
    if (el.btnModeSmart && el.btnModeSequential && el.btnModeSettings) {
        if (S.learningMode === 'sequential') {
            el.btnModeSequential.classList.add('active');
            el.btnModeSmart.classList.remove('active');
            el.btnModeSettings.style.display = '';
        } else {
            el.btnModeSmart.classList.add('active');
            el.btnModeSequential.classList.remove('active');
            el.btnModeSettings.style.display = 'none';
        }
    }
}

async function fetchModeStatus() {
    try {
        const r = await fetchWithAuth(`${API}/api/mode/status`);
        if (r.ok) {
            S.modeStatus = await r.json();
            // Update ID range dialog info
            if (el.idRangeInfo && S.modeStatus) {
                const total = S.modeStatus.sentences_count || S.modeStatus.stored_sentences_count || 0;
                el.idRangeInfo.textContent = `共 ${total} 句`;
            }
        }
    } catch { /* ignore */ }
}

function switchLearningMode(mode) {
    if (mode === S.learningMode) return;
    saveLearningMode(mode);
    // Reload sentence with new mode
    loadSentence();
}

// ============================================================
// Data Change Detection
// ============================================================
function showDataChangeBanner() {
    if (el.dataChangeBanner) {
        el.dataChangeBanner.style.display = 'flex';
    }
    // Auto-open ID range dialog if in sequential mode
    if (S.learningMode === 'sequential') {
        openIdRangeDialog();
    }
}

function hideDataChangeBanner() {
    if (el.dataChangeBanner) {
        el.dataChangeBanner.style.display = 'none';
    }
}

// ============================================================
// Sequential Mode ID Range Dialog
// ============================================================
function openIdRangeDialog() {
    if (!el.idRangeModal) return;
    el.idRangeError.style.display = 'none';

    // Populate current values from modeStatus
    if (S.modeStatus) {
        const total = S.modeStatus.sentences_count || S.modeStatus.stored_sentences_count || 0;
        el.idRangeInfo.textContent = `共 ${total} 句`;
        if (S.modeStatus.start_id) el.idRangeStart.value = S.modeStatus.start_id;
        if (S.modeStatus.end_id) el.idRangeEnd.value = S.modeStatus.end_id;
        else el.idRangeEnd.value = '';
    }

    el.idRangeModal.style.display = 'flex';
}

async function confirmIdRange() {
    const startId = parseInt(el.idRangeStart.value);
    const endId = el.idRangeEnd.value ? parseInt(el.idRangeEnd.value) : null;

    // Validate
    if (!startId || startId < 1) {
        el.idRangeError.textContent = '起始ID必须大于0';
        el.idRangeError.style.display = '';
        return;
    }
    if (endId !== null && endId < startId) {
        el.idRangeError.textContent = '结束ID不能小于起始ID';
        el.idRangeError.style.display = '';
        return;
    }

    try {
        const body = { start_id: startId };
        if (endId !== null) body.end_id = endId;

        const r = await fetchWithAuth(`${API}/api/mode/sequential/set-range`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (r.ok) {
            // Update cached mode status
            S.modeStatus = S.modeStatus || {};
            S.modeStatus.start_id = startId;
            S.modeStatus.end_id = endId;
            // Close dialog and hide banner
            el.idRangeModal.style.display = 'none';
            hideDataChangeBanner();
            // Load next sentence in range
            loadSentence();
        } else {
            const d = await r.json().catch(() => ({}));
            el.idRangeError.textContent = d.detail || '设置范围失败';
            el.idRangeError.style.display = '';
        }
    } catch (e) {
        el.idRangeError.textContent = '网络错误，请重试';
        el.idRangeError.style.display = '';
    }
}

// ============================================================
// Word Review
// ============================================================
async function openWordReview() {
    if (!el.wordReviewModal) return;
    el.wordReviewModal.style.display = 'flex';
    el.wordReviewCards.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text3);"><div class="spinner" style="margin:0 auto 12px;"></div>加载复习队列...</div>';
    el.wordReviewEmpty.style.display = 'none';

    // 重置复习状态
    S.wordReviewQueue = [];
    S.wordReviewIndex = 0;
    S.wordReviewReviewed = 0;
    S.wordReviewCorrect = 0;

    // 动态获取待复习数量（从后端获取 total_reviewable = 新词+待复习）
    try {
        const r = await fetchWithAuth(`${API}/api/fsrs/due-count?card_type=word`);
        if (r.ok) {
            const d = await r.json();
            S.wordReviewTotal = d.total_reviewable || d.pending_count || d.count || 0;
        } else {
            S.wordReviewTotal = 0;
        }
    } catch {
        S.wordReviewTotal = 0;
    }

    // 即使 total 为 0 也尝试加载（可能 total 不准确但实际有单词可复习）
    await loadNextReviewWord();
}

async function loadNextReviewWord() {
    const idx = S.wordReviewReviewed;
    const total = S.wordReviewTotal;

    if (total > 0 && idx >= total) {
        // 达到本次复习上限
        renderWordReviewComplete();
        return;
    }

    el.wordReviewProgress.textContent = total > 0 ? `${idx}/${total} 复习完成` : '加载中...';

    try {
        const r = await fetchWithAuth(`${API}/api/words/next-review`);
        if (r.ok) {
            const data = await r.json();
            if (!data.word) {
                // 没有更多需要复习的单词
                if (S.wordReviewReviewed === 0) {
                    // 一个单词都没复习就返回空了，显示空状态
                    el.wordReviewProgress.textContent = '0/0 复习完成';
                    el.wordReviewEmpty.style.display = 'block';
                    el.wordReviewCards.innerHTML = '';
                } else {
                    renderWordReviewComplete();
                }
                return;
            }
            // 动态更新待复习总数（随着复习推进，pending_count会变化）
            if (data.review_stats) {
                const newDue = (data.review_stats.due || 0) + (data.review_stats.new || 0);
                if (newDue > 0) {
                    S.wordReviewTotal = S.wordReviewReviewed + newDue;
                }
            }
            S.currentReviewWord = data;
            S.wordReviewStats = data.review_stats || null;
            renderSingleWordReviewCard(data);
        } else {
            el.wordReviewCards.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text3);">加载失败</div>';
        }
    } catch {
        el.wordReviewCards.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text3);">网络错误</div>';
    }
}

function renderSingleWordReviewCard(data) {
    const idx = S.wordReviewReviewed;
    const total = S.wordReviewTotal;
    const dictErrors = data.dictation_errors || 0;
    const pronErrors = data.pronunciation_errors || 0;
    const fsrsState = data.fsrs_state || 'new';
    const fsrsDifficulty = data.fsrs_difficulty || 0;
    const fsrsReps = data.fsrs_reps || 0;
    const fsrsRetrievability = data.fsrs_retrievability || 0;
    const fsrsScheduledDays = data.fsrs_scheduled_days || 0;

    // 掌握度标签
    const masteryMap = {
        'new': { label: '未学习', color: '#888', bg: '#f0f0f0' },
        'learning': { label: '学习中', color: '#e67e22', bg: '#fef3e2' },
        'review': { label: '复习中', color: '#3498db', bg: '#e8f4fd' },
        'relearning': { label: '重新学习', color: '#e74c3c', bg: '#fde8e8' },
        'due': { label: '待复习', color: '#e67e22', bg: '#fef3e2' },
        'mastered': { label: '已掌握', color: '#27ae60', bg: '#e8f8f0' },
    };
    const mastery = masteryMap[fsrsState] || masteryMap['new'];

    // 可回忆率条
    const retPercent = Math.round(fsrsRetrievability * 100);
    const retColor = retPercent >= 80 ? '#27ae60' : retPercent >= 50 ? '#e67e22' : '#e74c3c';

    // 复习统计
    const stats = S.wordReviewStats || {};
    const statsHTML = stats.total > 0 ? `
        <div class="word-review-stats-bar">
            <span class="word-review-stat-item">总计 <strong>${stats.total}</strong></span>
            <span class="word-review-stat-item" style="color:#27ae60">已掌握 <strong>${stats.mastered || 0}</strong></span>
            <span class="word-review-stat-item" style="color:#e67e22">待复习 <strong>${stats.due || 0}</strong></span>
            <span class="word-review-stat-item" style="color:#888">新词 <strong>${stats.new || 0}</strong></span>
        </div>
    ` : '';

    let html = `
    <div class="word-review-card" id="wordReviewCurrentCard">
        <div class="word-review-card-header">
            <span class="word-review-card-word">${data.word || ''}</span>
            <span class="word-review-card-pos">${data.pos || ''}</span>
            <span class="word-review-mastery-badge" style="background:${mastery.bg};color:${mastery.color}">${mastery.label}</span>
        </div>
        ${data.ipa ? `<div class="word-review-card-ipa">/${data.ipa}/</div>` : ''}
        <div class="word-review-card-meaning">${data.meaning || ''}</div>
        
        <!-- FSRS 掌握度信息 -->
        <div class="word-review-fsrs-info">
            ${fsrsReps > 0 ? `
            <div class="word-review-progress-bar">
                <div class="word-review-progress-label">
                    <span>可回忆率</span>
                    <span style="color:${retColor};font-weight:600">${retPercent}%</span>
                </div>
                <div class="word-review-progress-track">
                    <div class="word-review-progress-fill" style="width:${retPercent}%;background:${retColor}"></div>
                </div>
            </div>
            <div class="word-review-fsrs-details">
                <span>复习 ${fsrsReps} 次</span>
                <span>难度 ${fsrsDifficulty.toFixed(1)}</span>
                ${fsrsScheduledDays > 0 ? `<span>间隔 ${fsrsScheduledDays.toFixed(0)}天</span>` : ''}
            </div>` : '<div class="word-review-fsrs-details"><span>首次学习</span></div>'}
        </div>
        
        ${(dictErrors > 0 || pronErrors > 0) ? `
        <div class="word-review-card-errors">
            ${dictErrors > 0 ? `<span class="word-review-error-badge dictation">听写×${dictErrors}</span>` : ''}
            ${pronErrors > 0 ? `<span class="word-review-error-badge pronunciation">发音×${pronErrors}</span>` : ''}
        </div>` : ''}
        
        <div class="word-review-rating">
            <button class="word-review-rating-btn r1" data-rating="1">
                Again
                <span class="word-review-rating-label">完全忘记</span>
            </button>
            <button class="word-review-rating-btn r2" data-rating="2">
                Hard
                <span class="word-review-rating-label">困难回忆</span>
            </button>
            <button class="word-review-rating-btn r3" data-rating="3">
                Good
                <span class="word-review-rating-label">犹豫想起</span>
            </button>
            <button class="word-review-rating-btn r4" data-rating="4">
                Easy
                <span class="word-review-rating-label">轻松回忆</span>
            </button>
        </div>
    </div>
    ${statsHTML}`;

    el.wordReviewCards.innerHTML = html;
    el.wordReviewProgress.textContent = `${idx}/${total} 复习完成`;

    // Bind rating buttons
    el.wordReviewCards.querySelectorAll('.word-review-rating-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const rating = parseInt(btn.dataset.rating);
            submitWordReviewRatingSingle(rating);
        });
    });
}

function renderWordReviewComplete() {
    const reviewed = S.wordReviewReviewed;
    const total = S.wordReviewTotal;
    el.wordReviewProgress.textContent = `${reviewed}/${total} 复习完成`;
    
    const stats = S.wordReviewStats || {};
    el.wordReviewCards.innerHTML = `
        <div style="text-align:center;padding:30px 20px;">
            <div style="font-size:32px;margin-bottom:12px;">🎉</div>
            <div style="font-size:16px;font-weight:700;color:var(--ok);margin-bottom:8px;">
                本次复习完成！
            </div>
            <div style="font-size:13px;color:var(--text2);">
                已复习 ${reviewed} 个单词
            </div>
            ${stats.total > 0 ? `
            <div style="margin-top:16px;padding:12px;background:var(--bg2);border-radius:8px;font-size:13px;">
                <div>总计 ${stats.total} 词 | 已掌握 ${stats.mastered || 0} | 待复习 ${stats.due || 0} | 新词 ${stats.new || 0}</div>
            </div>` : ''}
        </div>`;
}

async function submitWordReviewRatingSingle(rating) {
    const data = S.currentReviewWord;
    if (!data || !data.word) return;

    // Animate card fading out
    const card = document.getElementById('wordReviewCurrentCard');
    if (card) card.classList.add('fading');

    // Submit to backend
    try {
        await fetchWithAuth(`${API}/api/words/review`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                word: data.word,
                rating: rating,
            }),
        });
    } catch { /* still advance */ }

    // Track progress
    S.wordReviewReviewed++;
    if (rating >= 3) S.wordReviewCorrect++;

    // Load next word
    setTimeout(() => {
        loadNextReviewWord();
    }, 300);
}

// ============================================================
// Auto-record Dictation Errors
// ============================================================
async function recordDictationErrors(inputs, expectedWords) {
    if (!S.sentence) return;

    // 优先使用后端返回的详细错误词信息（含编辑距离/相似度）
    if (S._dictationErrorWords && S._dictationErrorWords.length > 0) {
        try {
            await fetchWithAuth(`${API}/api/dictation/record-errors`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    error_words: S._dictationErrorWords,
                    sentence_id: S.sentence.id,
                }),
            });
        } catch { /* ignore */ }
        S._dictationErrorWords = null;
        return;
    }

    // 回退：前端检测的错误（旧逻辑）
    const errorWords = [];
    inputs.forEach((input, i) => {
        if (input.classList.contains('incorrect')) {
            const userVal = input.value.trim().toLowerCase();
            const expected = expectedWords[i] || '';
            if (userVal && expected) {
                errorWords.push({
                    word: expected,
                    user_input: userVal,
                });
            }
        }
    });

    if (errorWords.length === 0) return;

    // Send to backend (fire-and-forget)
    try {
        await fetchWithAuth(`${API}/api/dictation/record-errors`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                error_words: errorWords,
                sentence_id: S.sentence.id,
            }),
        });
    } catch { /* ignore */ }
}

// ============================================================
// Auto-record Pronunciation Errors (enhanced in updateStats)
// ============================================================

// ============================================================
// Word Practice Modal (跟读+听写+错误统计)
// ============================================================

// Practice state
const PS = {
    tab: 'pronunciation',  // 'pronunciation' | 'dictation' | 'errors'
    currentWord: null,
    practiced: 0,
    total: 0,
    isRecording: false,
    mediaRecorder: null,
    audioChunks: [],
    ttsAudio: null,
};

function initWordPractice() {
    // Button
    if (el.btnWordPractice) {
        el.btnWordPractice.addEventListener('click', openWordPractice);
    }
    // Modal elements
    const modal = document.getElementById('wordPracticeModal');
    const closeBtn = document.getElementById('closeWordPracticeModal');
    if (closeBtn) closeBtn.addEventListener('click', () => { modal.style.display = 'none'; stopTTS(); });
    if (modal) modal.addEventListener('click', (e) => { if (e.target === modal) { modal.style.display = 'none'; stopTTS(); } });

    // Tab switching
    document.querySelectorAll('.practice-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.practice-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            PS.tab = tab.dataset.tab;
            PS.practiced = 0;  // 切换标签页时重置计数
            if (PS.tab === 'errors') {
                loadErrorStats();
            } else {
                loadNextPracticeWord();
            }
        });
    });
}

function stopTTS() {
    if (PS.ttsAudio) {
        PS.ttsAudio.pause();
        PS.ttsAudio = null;
    }
}

async function playWordTTS(word) {
    stopTTS();
    try {
        const url = `${API}/api/tts?text=${encodeURIComponent(word)}`;
        PS.ttsAudio = new Audio(url);
        await PS.ttsAudio.play();
    } catch {
        // Fallback to browser TTS
        if ('speechSynthesis' in window) {
            const u = new SpeechSynthesisUtterance(word);
            u.lang = 'en-US';
            speechSynthesis.speak(u);
        }
    }
}

async function openWordPractice() {
    const modal = document.getElementById('wordPracticeModal');
    if (!modal) return;
    modal.style.display = 'flex';

    // Reset state
    PS.practiced = 0;
    PS.tab = 'pronunciation';

    // Reset tabs
    document.querySelectorAll('.practice-tab').forEach(t => t.classList.remove('active'));
    document.querySelector('.practice-tab[data-tab="pronunciation"]').classList.add('active');

    // Get total reviewable for pronunciation mode (跟读=读错的单词)
    // We don't use due-count here because each mode has its own total
    PS.total = 0;
    document.getElementById('practiceProgress').textContent = `0/? 练习完成`;
    await loadNextPracticeWord();
}

async function loadNextPracticeWord() {
    const content = document.getElementById('practiceContent');
    content.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text3);"><div class="spinner" style="margin:0 auto 12px;"></div>加载中...</div>';

    try {
        // 根据当前标签页传递 mode 参数给后端，让后端返回对应类型的单词
        const modeParam = PS.tab === 'pronunciation' ? 'pronunciation' : PS.tab === 'dictation' ? 'dictation' : 'all';
        let url = `${API}/api/words/practice-next?mode=${modeParam}`;
        // Pass exclude list to prevent LEARNING/RELEARNING cards from re-appearing
        if (S._reviewedCardIds && S._reviewedCardIds.length > 0) {
            url += `&exclude=${encodeURIComponent(S._reviewedCardIds.join(','))}`;
        }
        const r = await fetchWithAuth(url);
        if (r.ok) {
            const data = await r.json();
            if (!data.word) {
                const msg = data.message || '暂无可练习的单词！';
                content.innerHTML = `<div style="text-align:center;padding:30px;"><div style="font-size:32px;margin-bottom:12px;">🎉</div><div style="font-size:16px;font-weight:700;color:var(--ok);">${msg}</div></div>`;
                return;
            }
            PS.currentWord = data;
            // Update total dynamically
            if (data.total_reviewable) PS.total = data.total_reviewable;
            document.getElementById('practiceProgress').textContent = `${PS.practiced}/${PS.total} 练习完成`;

            if (PS.tab === 'pronunciation') {
                renderPronunciationCard(data);
            } else if (PS.tab === 'dictation') {
                renderDictationCard(data);
            } else {
                renderPronunciationCard(data);
            }
        }
    } catch {
        content.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text3);">加载失败</div>';
    }
}

function renderPronunciationCard(data) {
    const content = document.getElementById('practiceContent');
    const stateColors = { new: { bg: '#f0f0f0', color: '#888' }, learning: { bg: '#fef3e2', color: '#e67e22' }, review: { bg: '#e8f4fd', color: '#3498db' }, relearning: { bg: '#fde8e8', color: '#e74c3c' } };
    const sc = stateColors[data.fsrs_state] || stateColors.new;
    const stateLabels = { new: '新词', learning: '学习中', review: '复习', relearning: '重学' };

    content.innerHTML = `
    <div class="practice-card" id="practiceCard">
        <div class="practice-word">${data.word}</div>
        <div class="practice-ipa">/${data.ipa || ''}/</div>
        <div class="practice-meaning">${data.meaning || ''}</div>
        <span class="practice-badge" style="background:${sc.bg};color:${sc.color}">${stateLabels[data.fsrs_state] || '新词'}</span>
        ${data.pronunciation_errors > 0 ? `<div class="practice-error-info"><span class="practice-error-badge" style="background:#fde8e8;color:#e74c3c">读错×${data.pronunciation_errors}</span></div>` : ''}
        <div class="practice-actions">
            <button class="btn-practice-play" id="btnPlayWord">🔊 播放</button>
            <button class="btn-practice-record" id="btnRecordWord">🎤 跟读</button>
        </div>
        <div id="practiceResultArea"></div>
    </div>`;

    document.getElementById('btnPlayWord').addEventListener('click', () => playWordTTS(data.word));
    document.getElementById('btnRecordWord').addEventListener('click', startPracticeRecording);
}

function renderDictationCard(data) {
    const content = document.getElementById('practiceContent');
    const stateColors = { new: { bg: '#f0f0f0', color: '#888' }, learning: { bg: '#fef3e2', color: '#e67e22' }, review: { bg: '#e8f4fd', color: '#3498db' }, relearning: { bg: '#fde8e8', color: '#e74c3c' } };
    const sc = stateColors[data.fsrs_state] || stateColors.new;
    const stateLabels = { new: '新词', learning: '学习中', review: '复习', relearning: '重学' };

    content.innerHTML = `
    <div class="practice-card" id="practiceCard">
        <div style="font-size:14px;color:var(--text3);margin-bottom:12px;">听发音，拼写单词</div>
        <div class="practice-meaning" style="margin-bottom:8px;">${data.meaning || ''}</div>
        <span class="practice-badge" style="background:${sc.bg};color:${sc.color}">${stateLabels[data.fsrs_state] || '新词'}</span>
        ${data.dictation_errors > 0 ? `<div class="practice-error-info"><span class="practice-error-badge" style="background:#fef3e2;color:#e67e22">听错×${data.dictation_errors}</span></div>` : ''}
        <div class="practice-actions" style="margin-bottom:12px;">
            <button class="btn-practice-play" id="btnPlayWord">🔊 播放</button>
        </div>
        <input type="text" class="practice-dictation-input" id="dictationInput" placeholder="输入单词..." autocomplete="off" autocapitalize="none" spellcheck="false">
        <button class="btn-practice-check" id="btnCheckDictation">确认</button>
        <div id="practiceResultArea"></div>
    </div>`;

    document.getElementById('btnPlayWord').addEventListener('click', () => playWordTTS(data.word));
    document.getElementById('btnCheckDictation').addEventListener('click', submitDictationPractice);
    document.getElementById('dictationInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') submitDictationPractice();
    });

    // Auto-play TTS
    setTimeout(() => playWordTTS(data.word), 300);
}

async function startPracticeRecording() {
    if (PS.isRecording) {
        stopPracticeRecording();
        return;
    }

    const btn = document.getElementById('btnRecordWord');
    if (!btn) return;

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        PS.audioChunks = [];
        PS.mediaRecorder = new MediaRecorder(stream);
        PS.isRecording = true;
        btn.classList.add('recording');
        btn.innerHTML = '⏹ 停止';

        PS.mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) PS.audioChunks.push(e.data);
        };

        PS.mediaRecorder.onstop = async () => {
            stream.getTracks().forEach(t => t.stop());
            btn.classList.remove('recording');
            btn.innerHTML = '🎤 跟读';
            PS.isRecording = false;
            await submitPronunciationPractice();
        };

        PS.mediaRecorder.start();
        // Auto-stop after 5 seconds
        setTimeout(() => {
            if (PS.isRecording) stopPracticeRecording();
        }, 5000);
    } catch {
        btn.classList.remove('recording');
        PS.isRecording = false;
    }
}

function stopPracticeRecording() {
    if (PS.mediaRecorder && PS.mediaRecorder.state !== 'inactive') {
        PS.mediaRecorder.stop();
    }
}

async function submitPronunciationPractice() {
    if (!PS.currentWord || PS.audioChunks.length === 0) return;
    const resultArea = document.getElementById('practiceResultArea');
    resultArea.innerHTML = '<div style="text-align:center;padding:10px;color:var(--text3);font-size:13px;">评分中...</div>';

    try {
        const audioBlob = new Blob(PS.audioChunks, { type: 'audio/webm' });
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');
        formData.append('word', PS.currentWord.word);

        const r = await fetchWithAuth(`${API}/api/words/practice-evaluate`, {
            method: 'POST',
            body: formData,
        });

        if (r.ok) {
            const data = await r.json();
            const score = data.effective_score || 0;
            const rating = data.auto_rating || 1;
            const ratingNames = { 1: 'Again', 2: 'Hard', 3: 'Good', 4: 'Easy' };
            const ratingColors = { 1: 'var(--fsrs-again)', 2: 'var(--fsrs-hard)', 3: 'var(--fsrs-good)', 4: 'var(--fsrs-easy)' };

            const resultClass = score >= 70 ? 'correct' : score >= 50 ? 'partial-result' : 'incorrect';

            // Add word to session reviewed list (prevent same word re-appearing in this session)
            const cardId = `word_${PS.currentWord.word}`;
            if (!S._reviewedCardIds.includes(cardId)) {
                S._reviewedCardIds.push(cardId);
                if (S._reviewedCardIds.length > 50) S._reviewedCardIds.shift();
            }

            // Show detailed pronunciation errors
            let errorDetail = '';
            if (data.words && data.words.length > 0) {
                const wordErrors = data.words.filter(w => w.has_error);
                if (wordErrors.length > 0) {
                    errorDetail = '<div class="practice-word-errors">' +
                        wordErrors.map(w => {
                            const acc = Math.round(calibrateScore(w.accuracy));
                            const errClass = acc >= 50 ? 'partial' : 'wrong';
                            return `<span class="word-error-chip ${errClass}">${w.word} <small>${acc}%</small></span>`;
                        }).join('') +
                        '</div>';
                }
            }
            if (data.errors && data.errors.length > 0) {
                const phonErrors = data.errors.filter(e => e.type === 'substitution' || e.type === 'deletion');
                if (phonErrors.length > 0) {
                    errorDetail += '<div class="practice-phoneme-errors">' +
                        phonErrors.slice(0, 5).map(e => {
                            const ipaExp = ARPABET_TO_IPA[e.expected] || e.expected;
                            const ipaAct = e.actual ? (ARPABET_TO_IPA[e.actual] || e.actual) : '—';
                            return `<span class="phoneme-error-chip">/${ipaExp}/→/${ipaAct}/</span>`;
                        }).join('') +
                        '</div>';
                }
            }

            resultArea.innerHTML = `
            <div class="practice-result ${resultClass}">
                <div class="practice-score-value" style="position:static;font-size:32px;color:${ratingColors[rating]}">${Math.round(score)}</div>
                <div style="font-size:13px;margin-top:4px;">发音分数</div>
            </div>
            ${errorDetail}
            <div class="practice-fsrs-result">
                自动评级: <strong style="color:${ratingColors[rating]}">${ratingNames[rating]}</strong>
                ${data.fsrs_result ? ` · 下次复习: ${data.fsrs_result.scheduled_days.toFixed(1)}天后` : ''}
            </div>
            <button class="practice-next-btn" id="btnNextWord">下一个 →</button>`;

            PS.practiced++;
            document.getElementById('practiceProgress').textContent = `${PS.practiced}/${PS.total} 练习完成`;
            document.getElementById('btnNextWord').addEventListener('click', loadNextPracticeWord);
        } else {
            resultArea.innerHTML = '<div class="practice-result incorrect">评分失败，请重试</div>';
        }
    } catch {
        resultArea.innerHTML = '<div class="practice-result incorrect">网络错误</div>';
    }
}

async function submitDictationPractice() {
    if (!PS.currentWord) return;
    const input = document.getElementById('dictationInput');
    if (!input) return;
    const userInput = input.value.trim().toLowerCase();
    if (!userInput) return;

    const resultArea = document.getElementById('practiceResultArea');
    resultArea.innerHTML = '<div style="text-align:center;padding:10px;color:var(--text3);font-size:13px;">检查中...</div>';

    try {
        const r = await fetchWithAuth(`${API}/api/words/dictation-practice`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ word: PS.currentWord.word, user_input: userInput }),
        });

        if (r.ok) {
            const data = await r.json();
            const ratingNames = { 1: 'Again', 2: 'Hard', 3: 'Good', 4: 'Easy' };
            const ratingColors = { 1: 'var(--fsrs-again)', 2: 'var(--fsrs-hard)', 3: 'var(--fsrs-good)', 4: 'var(--fsrs-easy)' };
            const resultClass = data.correct ? 'correct' : data.type === 'partial' ? 'partial-result' : 'incorrect';
            const resultIcon = data.correct ? '✅' : data.type === 'partial' ? '🔶' : '❌';

            // Add word to session reviewed list
            const cardId = `word_${PS.currentWord.word}`;
            if (!S._reviewedCardIds.includes(cardId)) {
                S._reviewedCardIds.push(cardId);
                if (S._reviewedCardIds.length > 50) S._reviewedCardIds.shift();
            }

            let detail = '';
            if (data.type === 'match') detail = '完全正确！';
            else if (data.type === 'near_correct') detail = `近似正确（相似度${Math.round(data.similarity * 100)}%）`;
            else if (data.type === 'partial') detail = `部分正确（相似度${Math.round(data.similarity * 100)}%）<br>正确: <strong>${data.word}</strong>`;
            else detail = `错误<br>正确: <strong>${data.word}</strong>`;

            // Show character-level diff for wrong dictation
            let diffHtml = '';
            if (!data.correct && data.word && userInput) {
                const expected = data.word.toLowerCase();
                const typed = userInput.toLowerCase();
                // Simple character comparison
                let diffChars = '';
                const maxLen = Math.max(expected.length, typed.length);
                for (let i = 0; i < maxLen; i++) {
                    const e = expected[i] || '';
                    const t = typed[i] || '';
                    if (e === t) {
                        diffChars += `<span class="dict-char correct">${e}</span>`;
                    } else if (e && !t) {
                        diffChars += `<span class="dict-char missing">${e}</span>`;
                    } else if (!e && t) {
                        diffChars += `<span class="dict-char extra">${t}</span>`;
                    } else {
                        diffChars += `<span class="dict-char wrong">${t}</span><span class="dict-char expected">${e}</span>`;
                    }
                }
                diffHtml = `<div class="dict-diff">${diffChars}</div>`;
            }

            resultArea.innerHTML = `
            <div class="practice-result ${resultClass}">
                <div style="font-size:28px;margin-bottom:6px;">${resultIcon}</div>
                <div style="font-size:14px;">${detail}</div>
            </div>
            ${diffHtml}
            <div class="practice-fsrs-result">
                自动评级: <strong style="color:${ratingColors[data.auto_rating]}">${ratingNames[data.auto_rating]}</strong>
                ${data.fsrs_result ? ` · 下次复习: ${data.fsrs_result.scheduled_days.toFixed(1)}天后` : ''}
            </div>
            <button class="practice-next-btn" id="btnNextWord">下一个 →</button>`;

            input.disabled = true;
            PS.practiced++;
            document.getElementById('practiceProgress').textContent = `${PS.practiced}/${PS.total} 练习完成`;
            document.getElementById('btnNextWord').addEventListener('click', loadNextPracticeWord);
        }
    } catch {
        resultArea.innerHTML = '<div class="practice-result incorrect">网络错误</div>';
    }
}

async function loadErrorStats() {
    const content = document.getElementById('practiceContent');
    content.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text3);"><div class="spinner" style="margin:0 auto 12px;"></div>加载统计...</div>';

    try {
        const r = await fetchWithAuth(`${API}/api/words/error-stats`);
        if (r.ok) {
            const data = await r.json();
            renderErrorStats(data);
        }
    } catch {
        content.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text3);">加载失败</div>';
    }
}

function renderErrorStats(data) {
    const content = document.getElementById('practiceContent');
    const pronErrors = data.pronunciation_errors || [];
    const dictErrors = data.dictation_errors || [];
    const summary = data.summary || {};

    let html = `
    <div style="text-align:center;margin-bottom:16px;font-size:13px;color:var(--text2);">
        🎤 读错 <strong style="color:#e74c3c">${summary.total_pron_errors || 0}</strong> 词 · 
        ✏️ 听写错 <strong style="color:#e67e22">${summary.total_dict_errors || 0}</strong> 词 · 
        合计 <strong>${summary.total_unique_errors || 0}</strong> 词
    </div>
    <div style="text-align:center;margin-bottom:16px;">
        <button class="practice-tab ${PS.tab === 'pronunciation' ? 'active' : ''}" onclick="switchErrorTab('pronunciation')" style="padding:6px 14px;font-size:12px;border-radius:16px;border:1px solid var(--border);background:${PS.tab === 'pronunciation' ? 'rgba(99,102,241,0.2)' : 'transparent'};color:${PS.tab === 'pronunciation' ? 'var(--pri)' : 'var(--text3)'};cursor:pointer;">🎤 发音错误</button>
        <button class="practice-tab ${PS.tab === 'dictation' ? 'active' : ''}" onclick="switchErrorTab('dictation')" style="padding:6px 14px;font-size:12px;border-radius:16px;border:1px solid var(--border);background:${PS.tab === 'dictation' ? 'rgba(99,102,241,0.2)' : 'transparent'};color:${PS.tab === 'dictation' ? 'var(--pri)' : 'var(--text3)'};cursor:pointer;">✏️ 听写错误</button>
    </div>`;

    // Pronunciation errors - show based on active tab
    const showPron = PS.tab === 'pronunciation' || PS.tab === 'errors';
    const showDict = PS.tab === 'dictation' || PS.tab === 'errors';

    if (showPron) {
        html += `<div class="error-stats-section">
            <div class="error-stats-title">🎤 经常读错的单词</div>`;
    if (pronErrors.length === 0) {
        html += '<div class="error-stats-empty">暂无读错记录 ✨</div>';
    } else {
        html += '<ul class="error-stats-list">';
        pronErrors.slice(0, 15).forEach(ew => {
            const rateInfo = ew.pronunciation_rate !== undefined ? `<span style="color:#e74c3c;font-weight:600;margin-left:6px;">${ew.pronunciation_rate}%</span>` : '';
            const totalInfo = ew.pronunciation_total ? `/${ew.pronunciation_total}` : '';
            html += `<li class="error-stats-item">
                <span class="error-stats-word">${ew.word} <span style="color:var(--text3);font-size:11px;">/${ew.ipa}/</span></span>
                <span class="error-stats-count" style="color:#e74c3c">${ew.pronunciation_errors}次${totalInfo} ${rateInfo}</span>
            </li>`;
        });
        html += '</ul>';
    }
    html += '</div>';
    } // end if showPron

    if (showDict) {
    html += `<div class="error-stats-section">
        <div class="error-stats-title">✏️ 经常听写错的单词</div>`;
    if (dictErrors.length === 0) {
        html += '<div class="error-stats-empty">暂无听写错误 ✨</div>';
    } else {
        html += '<ul class="error-stats-list">';
        dictErrors.slice(0, 15).forEach(ew => {
            const rateInfo = ew.dictation_rate !== undefined ? `<span style="color:#e67e22;font-weight:600;margin-left:6px;">${ew.dictation_rate}%</span>` : '';
            const totalInfo = ew.dictation_total ? `/${ew.dictation_total}` : '';
            html += `<li class="error-stats-item">
                <span class="error-stats-word">${ew.word} <span style="color:var(--text3);font-size:11px;">/${ew.ipa}/</span></span>
                <span class="error-stats-count" style="color:#e67e22">${ew.dictation_errors}次${totalInfo} ${rateInfo}</span>
            </li>`;
        });
        html += '</ul>';
    }
    html += '</div>';
    } // end if showDict

    content.innerHTML = html;
}

function switchErrorTab(tab) {
    PS.tab = tab;
    loadErrorStats();
}

// ============================================================
// Boot
// ============================================================
document.addEventListener('DOMContentLoaded', init);

// ============================================================
// Metacognition / Prediction Calibration
// ============================================================
async function loadMetacognitionProfile() {
    try {
        const r = await fetchWithAuth(`${API}/api/metacognition/profile`);
        if (r.ok) {
            const data = await r.json();
            S.calibrationEnabled = data.calibration_enabled || false;
        }
    } catch { /* feature not available, degrade gracefully */ }
}

function showPredictionUI() {
    if (!S.calibrationEnabled || !el.predictionSection) return;
    el.predictionSection.style.display = '';
    S.predictionScore = parseInt(el.predictionSlider?.value || 50);
    if (el.predictionValue) el.predictionValue.textContent = S.predictionScore;
}

function hidePredictionUI() {
    if (el.predictionSection) el.predictionSection.style.display = 'none';
}

function showCalibrationResult(actualScore) {
    if (!S.calibrationEnabled || S.predictionScore === null) return;
    if (el.calibrationDisplay) el.calibrationDisplay.style.display = '';
    const pred = S.predictionScore;
    const deviation = pred - actualScore;
    if (el.calPrediction) el.calPrediction.textContent = pred;
    if (el.calActual) el.calActual.textContent = actualScore;
    if (el.calDeviation) {
        el.calDeviation.textContent = (deviation >= 0 ? '+' : '') + deviation;
        el.calDeviation.style.color = Math.abs(deviation) <= 10 ? 'var(--ok)' : Math.abs(deviation) <= 25 ? 'var(--warn)' : 'var(--err)';
    }
}

function hideCalibrationResult() {
    if (el.calibrationDisplay) el.calibrationDisplay.style.display = 'none';
}

// ============================================================
// Cognitive Mirror Modal
// ============================================================
async function openCognitiveMirror() {
    if (!el.cognitiveMirrorModal) return;
    el.cognitiveMirrorModal.style.display = 'flex';
    el.cognitiveMirrorBody.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text3);"><div class="spinner" style="margin:0 auto 12px;"></div>加载认知画像...</div>';

    let profile = null;
    try {
        const r = await fetchWithAuth(`${API}/api/metacognition/profile`);
        if (r.ok) profile = await r.json();
    } catch { /* degrade */ }

    if (!profile) {
        el.cognitiveMirrorBody.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text3);">认知画像暂不可用，开始练习后即可查看</div>';
        return;
    }

    const metrics = profile.metrics || {};
    const metricNames = {
        speed: { label: '学习速度', color: 'var(--pri)' },
        retention: { label: '记忆保持', color: 'var(--ok)' },
        coverage: { label: '知识覆盖', color: 'var(--accent-blue)' },
        confidence_gap: { label: '自信偏差', color: 'var(--warn)' },
        again_rate: { label: '重复率', color: 'var(--fsrs-again)' },
        easy_rate: { label: '轻松率', color: 'var(--fsrs-easy)' },
    };

    let metricsHTML = '';
    for (const [key, info] of Object.entries(metricNames)) {
        const val = metrics[key] !== undefined ? Math.round(metrics[key] * 100) : 0;
        metricsHTML += `
        <div class="metric-bar-item">
            <span class="metric-bar-label">${info.label}</span>
            <div class="metric-bar-track">
                <div class="metric-bar-fill" style="width:${val}%;background:${info.color};"></div>
            </div>
            <span class="metric-bar-val" style="color:${info.color};">${val}%</span>
        </div>`;
    }

    let strengthsHTML = '';
    if (profile.strengths && profile.strengths.length > 0) {
        strengthsHTML = '<ul class="cognitive-mirror-list">' +
            profile.strengths.map(s => `<li><span class="icon">💪</span>${s}</li>`).join('') +
            '</ul>';
    }

    let weaknessesHTML = '';
    if (profile.weaknesses && profile.weaknesses.length > 0) {
        weaknessesHTML = '<ul class="cognitive-mirror-list">' +
            profile.weaknesses.map(w => `<li><span class="icon">⚠️</span>${w}</li>`).join('') +
            '</ul>';
    }

    // Fetch strategies
    let strategiesHTML = '';
    try {
        const sr = await fetchWithAuth(`${API}/api/metacognition/strategies`);
        if (sr.ok) {
            const strategies = await sr.json();
            if (strategies.recommendations && strategies.recommendations.length > 0) {
                strategiesHTML = `
                <div class="cognitive-mirror-strategies">
                    <h5>📋 策略推荐</h5>
                    <ul class="cognitive-mirror-list">
                        ${strategies.recommendations.map(r => `<li><span class="icon">✅</span>${r}</li>`).join('')}
                    </ul>
                    ${strategies.param_adjustments ? `<button class="btn-apply-strategy" onclick="applyStrategyRecommendations()">应用推荐设置</button>` : ''}
                </div>`;
            }
        }
    } catch { /* no strategies available */ }

    el.cognitiveMirrorBody.innerHTML = `
        <div class="cognitive-mirror-hero">
            <div class="cognitive-mirror-icon">${profile.archetype_icon || '🧠'}</div>
            <div class="cognitive-mirror-name">${profile.archetype_name || '学习者'}</div>
            <div class="cognitive-mirror-desc">${profile.description || ''}</div>
        </div>

        <div class="cognitive-mirror-section">
            <h5>📊 认知指标</h5>
            ${metricsHTML}
        </div>

        ${strengthsHTML ? `<div class="cognitive-mirror-section"><h5>💪 优势</h5>${strengthsHTML}</div>` : ''}
        ${weaknessesHTML ? `<div class="cognitive-mirror-section"><h5>⚠️ 待改善</h5>${weaknessesHTML}</div>` : ''}

        ${strategiesHTML}
    `;
}

async function applyStrategyRecommendations() {
    try {
        const r = await fetchWithAuth(`${API}/api/metacognition/strategies`);
        if (r.ok) {
            const strategies = await r.json();
            if (strategies.param_adjustments) {
                await fetchWithAuth(`${API}/api/settings`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(strategies.param_adjustments),
                });
                loadSettings();
                alert('已应用推荐设置！');
            }
        }
    } catch { alert('应用设置失败'); }
}
window.applyStrategyRecommendations = applyStrategyRecommendations;

// ============================================================
// Semantic Network Viewer
// ============================================================
async function lookupSemanticNetwork(word) {
    if (!el.semanticNetworkSection || !el.semanticNetworkContent) return;
    el.semanticNetworkSection.style.display = '';
    el.semanticNetworkContent.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text3);"><div class="spinner" style="margin:0 auto 12px;"></div>加载词汇网络...</div>';

    try {
        const r = await fetchWithAuth(`${API}/api/semantic/network/${encodeURIComponent(word)}?depth=1`);
        if (!r.ok) throw new Error('not available');
        const data = await r.json();

        const relationGroups = {
            COOCCURRENCE: { label: '搭配词', cls: 'cooccurrence', color: 'var(--tag-cooccurrence)' },
            SEMANTIC_SIMILARITY: { label: '相似词', cls: 'similar', color: 'var(--tag-similar)' },
            SYNTAGMATIC: { label: '同位词', cls: 'syntagmatic', color: 'var(--tag-syntagmatic)' },
            PARADIGMATIC: { label: '近义词', cls: 'paradigmatic', color: 'var(--tag-paradigmatic)' },
        };

        let html = `<div style="font-size:14px;font-weight:700;color:var(--text);margin-bottom:10px;">"${word}" 的词汇网络</div>`;

        const relations = data.relations || {};
        let hasAny = false;

        for (const [type, group] of Object.entries(relationGroups)) {
            const words = relations[type] || [];
            if (words.length === 0) continue;
            hasAny = true;
            html += `
            <div class="semantic-group">
                <div class="semantic-group-title">
                    <span class="dot" style="background:${group.color};"></span>
                    ${group.label}
                </div>
                <div class="semantic-tags">
                    ${words.map(w => {
                        const strength = w.strength !== undefined ? w.strength : 1;
                        const opacity = 0.4 + strength * 0.6;
                        const weight = strength > 0.7 ? 800 : strength > 0.4 ? 600 : 400;
                        return `<span class="semantic-tag ${group.cls}" style="opacity:${opacity};font-weight:${weight};" onclick="lookupSemanticNetwork('${escapeAttr(w.word || w)}')">${w.word || w}<span class="strength">${Math.round(strength * 100)}%</span></span>`;
                    }).join('')}
                </div>
            </div>`;
        }

        if (!hasAny) {
            html += '<div style="text-align:center;padding:20px;color:var(--text3);font-size:13px;">暂无关联词汇数据</div>';
        }

        el.semanticNetworkContent.innerHTML = html;
    } catch {
        el.semanticNetworkContent.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text3);font-size:13px;">词汇网络暂不可用</div>';
    }
}
window.lookupSemanticNetwork = lookupSemanticNetwork;

// ============================================================
// Settings Modal
// ============================================================
async function loadSettings() {
    try {
        const r = await fetchWithAuth(`${API}/api/settings`);
        if (r.ok) {
            S.settings = await r.json();
            return S.settings;
        }
    } catch { /* degrade */ }
    S.settings = S.settings || {};
    return S.settings;
}

function openSettingsModal() {
    if (!el.settingsModal) return;
    el.settingsModal.style.display = 'flex';

    const s = S.settings || {};
    const fsrs = s.fsrs || {};
    const learning = s.learning || {};
    const display = s.display || {};
    const scoring = s.scoring_weights || { pronunciation: 0.55, completeness: 0.25, fluency: 0.20 };
    const ttsPriority = s.tts_priority || 'browser';
    const showTranslationFirst = s.show_translation_first || false;
    const fitInterval = s.fsrs_fit_interval || 30;

    el.settingsModalBody.innerHTML = `
        <!-- FSRS Settings -->
        <div class="settings-group">
            <div class="settings-group-title">
                🧠 FSRS 间隔重复
            </div>
            <div class="settings-row">
                <span class="settings-row-label">期望记忆率</span>
                <div class="settings-row-value">
                    <input type="range" class="settings-slider" id="setDesiredRetention" min="0.8" max="0.99" step="0.01" value="${fsrs.desired_retention || 0.9}">
                    <span class="settings-slider-val" id="setDesiredRetentionVal">${fsrs.desired_retention || 0.9}</span>
                </div>
            </div>
            <div class="settings-row">
                <span class="settings-row-label">每日新卡</span>
                <div class="settings-row-value">
                    <input type="number" class="settings-input" id="setNewCardsDay" min="1" max="20" value="${fsrs.new_cards_per_day || 5}">
                </div>
            </div>
            <div class="settings-row">
                <span class="settings-row-label">最大间隔(天)</span>
                <div class="settings-row-value">
                    <input type="number" class="settings-input" id="setMaxInterval" min="1" max="36500" value="${fsrs.maximum_interval || 36500}">
                </div>
            </div>
            <div class="settings-row">
                <span class="settings-row-label">学习步骤(分钟)</span>
                <div class="settings-row-value">
                    <input type="text" class="settings-input settings-input-wide" id="setLearningSteps" value="${(fsrs.learning_steps || ['1','10']).join(',')}">
                </div>
            </div>
            <div class="settings-row">
                <span class="settings-row-label">重学步骤(分钟)</span>
                <div class="settings-row-value">
                    <input type="text" class="settings-input settings-input-wide" id="setRelearningSteps" value="${(fsrs.relearning_steps || ['10']).join(',')}">
                </div>
            </div>
            <div class="settings-row">
                <span class="settings-row-label">拟合间隔(次)</span>
                <div class="settings-row-value">
                    <input type="number" class="settings-input" id="setFitInterval" min="10" max="200" value="${fitInterval}">
                    <span style="font-size:11px;color:var(--text3);margin-left:4px;">每N次复习拟合一次</span>
                </div>
            </div>
            <div style="text-align:right;margin-top:8px;">
                <button class="settings-btn-fit" id="btnFsrsFit">优化参数</button>
            </div>
        </div>

        <!-- Scoring Weights -->
        <div class="settings-group">
            <div class="settings-group-title">
                📊 评分权重
            </div>
            <div class="settings-row">
                <span class="settings-row-label">发音准确度</span>
                <div class="settings-row-value">
                    <input type="range" class="settings-slider" id="setWeightPron" min="0" max="1" step="0.05" value="${scoring.pronunciation}">
                    <span class="settings-slider-val" id="setWeightPronVal">${Math.round(scoring.pronunciation * 100)}%</span>
                </div>
            </div>
            <div class="settings-row">
                <span class="settings-row-label">完整度</span>
                <div class="settings-row-value">
                    <input type="range" class="settings-slider" id="setWeightComp" min="0" max="1" step="0.05" value="${scoring.completeness}">
                    <span class="settings-slider-val" id="setWeightCompVal">${Math.round(scoring.completeness * 100)}%</span>
                </div>
            </div>
            <div class="settings-row">
                <span class="settings-row-label">流利度</span>
                <div class="settings-row-value">
                    <input type="range" class="settings-slider" id="setWeightFlu" min="0" max="1" step="0.05" value="${scoring.fluency}">
                    <span class="settings-slider-val" id="setWeightFluVal">${Math.round(scoring.fluency * 100)}%</span>
                </div>
            </div>
            <div class="settings-row-hint" id="weightHint">
                权重自动归一化，当前: 发音${Math.round(scoring.pronunciation / (scoring.pronunciation + scoring.completeness + scoring.fluency) * 100)}% / 完整${Math.round(scoring.completeness / (scoring.pronunciation + scoring.completeness + scoring.fluency) * 100)}% / 流利${Math.round(scoring.fluency / (scoring.pronunciation + scoring.completeness + scoring.fluency) * 100)}%
            </div>
        </div>

        <!-- Learning Settings -->
        <div class="settings-group">
            <div class="settings-group-title">
                📚 学习设置
            </div>
            <div class="settings-row">
                <span class="settings-row-label">探索率</span>
                <div class="settings-row-value">
                    <input type="range" class="settings-slider" id="setExplorationRate" min="0" max="1" step="0.05" value="${learning.exploration_rate !== undefined ? learning.exploration_rate : 0.3}">
                    <span class="settings-slider-val" id="setExplorationRateVal">${learning.exploration_rate !== undefined ? learning.exploration_rate : 0.3}</span>
                </div>
            </div>
            <div class="settings-row">
                <span class="settings-row-label">启用预测校准</span>
                <button class="settings-toggle ${S.calibrationEnabled ? 'active' : ''}" id="setCalibration">
                    <div class="settings-toggle-knob"></div>
                </button>
            </div>
            <div class="settings-row">
                <span class="settings-row-label">自动应用策略推荐</span>
                <button class="settings-toggle ${learning.auto_apply_strategy ? 'active' : ''}" id="setAutoStrategy">
                    <div class="settings-toggle-knob"></div>
                </button>
            </div>
        </div>

        <!-- Display Settings -->
        <div class="settings-group">
            <div class="settings-group-title">
                🎨 显示设置
            </div>
            <div class="settings-row">
                <span class="settings-row-label">默认显示音标</span>
                <button class="settings-toggle ${display.show_ipa_default ? 'active' : ''}" id="setShowIPA">
                    <div class="settings-toggle-knob"></div>
                </button>
            </div>
            <div class="settings-row">
                <span class="settings-row-label">自动播放TTS</span>
                <button class="settings-toggle ${display.auto_play_tts ? 'active' : ''}" id="setAutoTTS">
                    <div class="settings-toggle-knob"></div>
                </button>
            </div>
            <div class="settings-row">
                <span class="settings-row-label">听写默认速度</span>
                <div class="settings-row-value">
                    <select class="settings-select" id="setDictationSpeed">
                        <option value="0.5" ${display.dictation_speed === 0.5 ? 'selected' : ''}>0.5x</option>
                        <option value="0.75" ${display.dictation_speed === 0.75 ? 'selected' : ''}>0.75x</option>
                        <option value="1.0" ${(!display.dictation_speed || display.dictation_speed === 1.0) ? 'selected' : ''}>1.0x</option>
                    </select>
                </div>
            </div>
            <div class="settings-row">
                <span class="settings-row-label">优先显示翻译</span>
                <button class="settings-toggle ${showTranslationFirst ? 'active' : ''}" id="setTranslationFirst">
                    <div class="settings-toggle-knob"></div>
                </button>
            </div>
            <div class="settings-row">
                <span class="settings-row-label">TTS引擎</span>
                <div class="settings-row-value">
                    <select class="settings-select" id="setTTSPriority">
                        <option value="browser" ${ttsPriority === 'browser' ? 'selected' : ''}>浏览器优先</option>
                        <option value="server" ${ttsPriority === 'server' ? 'selected' : ''}>服务端优先</option>
                    </select>
                </div>
            </div>
            <div class="settings-row">
                <span class="settings-row-label">翻译引擎</span>
                <div class="settings-row-value">
                    <select class="settings-select" id="setTranslationPriority">
                        <option value="auto" ${!s.translation_priority || s.translation_priority === 'auto' ? 'selected' : ''}>自动（网络优先）</option>
                        <option value="local" ${s.translation_priority === 'local' ? 'selected' : ''}>本地优先（离线）</option>
                        <option value="online" ${s.translation_priority === 'online' ? 'selected' : ''}>在线优先</option>
                    </select>
                </div>
            </div>
            <div class="settings-row">
                <span class="settings-row-label">翻译显示</span>
                <div class="settings-row-value">
                    <select class="settings-select" id="setTranslationDisplay">
                        <option value="after" ${!s.translation_priority || s.translation_display !== 'first' ? 'selected' : ''}>原文后显示</option>
                        <option value="first" ${s.translation_display === 'first' ? 'selected' : ''}>优先显示翻译</option>
                    </select>
                </div>
            </div>
        </div>

        <!-- Action Buttons -->
        <div class="settings-btn-row">
            <button class="settings-btn-secondary" id="btnResetSettings">恢复默认</button>
            <button class="settings-btn-primary" id="btnSaveSettings">保存设置</button>
        </div>
    `;

    // Bind settings modal interactions
    const sliderRetention = document.getElementById('setDesiredRetention');
    const sliderRetentionVal = document.getElementById('setDesiredRetentionVal');
    if (sliderRetention && sliderRetentionVal) {
        sliderRetention.addEventListener('input', () => { sliderRetentionVal.textContent = sliderRetention.value; });
    }

    const sliderExplore = document.getElementById('setExplorationRate');
    const sliderExploreVal = document.getElementById('setExplorationRateVal');
    if (sliderExplore && sliderExploreVal) {
        sliderExplore.addEventListener('input', () => { sliderExploreVal.textContent = sliderExplore.value; });
    }

    // Scoring weight sliders - update hint text dynamically
    const wPron = document.getElementById('setWeightPron');
    const wComp = document.getElementById('setWeightComp');
    const wFlu = document.getElementById('setWeightFlu');
    const wPronVal = document.getElementById('setWeightPronVal');
    const wCompVal = document.getElementById('setWeightCompVal');
    const wFluVal = document.getElementById('setWeightFluVal');
    const weightHint = document.getElementById('weightHint');
    function updateWeightHint() {
        if (!wPron || !wComp || !wFlu) return;
        const p = parseFloat(wPron.value), c = parseFloat(wComp.value), f = parseFloat(wFlu.value);
        const t = p + c + f || 1;
        wPronVal.textContent = Math.round(p * 100) + '%';
        wCompVal.textContent = Math.round(c * 100) + '%';
        wFluVal.textContent = Math.round(f * 100) + '%';
        if (weightHint) {
            weightHint.textContent = `权重自动归一化，当前: 发音${Math.round(p/t*100)}% / 完整${Math.round(c/t*100)}% / 流利${Math.round(f/t*100)}%`;
        }
    }
    [wPron, wComp, wFlu].forEach(s => { if (s) s.addEventListener('input', updateWeightHint); });

    // Toggle buttons
    document.querySelectorAll('.settings-toggle').forEach(toggle => {
        toggle.addEventListener('click', () => toggle.classList.toggle('active'));
    });

    // FSRS fit button
    const btnFit = document.getElementById('btnFsrsFit');
    if (btnFit) btnFit.addEventListener('click', async () => {
        btnFit.textContent = '优化中...';
        btnFit.disabled = true;
        try {
            const r = await fetchWithAuth(`${API}/api/settings/fsrs-fit`, { method: 'POST' });
            if (r.ok) {
                btnFit.textContent = '✓ 优化完成';
                await loadSettings();
                setTimeout(() => openSettingsModal(), 500);
            } else {
                btnFit.textContent = '优化失败';
            }
        } catch { btnFit.textContent = '优化失败'; }
        setTimeout(() => { btnFit.textContent = '优化参数'; btnFit.disabled = false; }, 2000);
    });

    // Reset button
    const btnReset = document.getElementById('btnResetSettings');
    if (btnReset) btnReset.addEventListener('click', async () => {
        if (!confirm('确定要恢复默认设置吗？')) return;
        try {
            await fetchWithAuth(`${API}/api/settings/reset`, { method: 'POST' });
            await loadSettings();
            openSettingsModal();
        } catch { alert('重置失败'); }
    });

    // Save button
    const btnSave = document.getElementById('btnSaveSettings');
    if (btnSave) btnSave.addEventListener('click', async () => {
        const settings = {
            fsrs: {
                desired_retention: parseFloat(document.getElementById('setDesiredRetention')?.value || 0.9),
                new_cards_per_day: parseInt(document.getElementById('setNewCardsDay')?.value || 5),
                maximum_interval: parseInt(document.getElementById('setMaxInterval')?.value || 36500),
                learning_steps: (document.getElementById('setLearningSteps')?.value || '1,10').split(',').map(s => s.trim()),
                relearning_steps: (document.getElementById('setRelearningSteps')?.value || '10').split(',').map(s => s.trim()),
            },
            scoring_weights: {
                pronunciation: parseFloat(document.getElementById('setWeightPron')?.value || 0.55),
                completeness: parseFloat(document.getElementById('setWeightComp')?.value || 0.25),
                fluency: parseFloat(document.getElementById('setWeightFlu')?.value || 0.20),
            },
            fsrs_fit_interval: parseInt(document.getElementById('setFitInterval')?.value || 30),
            learning: {
                exploration_rate: parseFloat(document.getElementById('setExplorationRate')?.value || 0.3),
                calibration_enabled: document.getElementById('setCalibration')?.classList.contains('active') || false,
                auto_apply_strategy: document.getElementById('setAutoStrategy')?.classList.contains('active') || false,
            },
            display: {
                show_ipa_default: document.getElementById('setShowIPA')?.classList.contains('active') || false,
                auto_play_tts: document.getElementById('setAutoTTS')?.classList.contains('active') || false,
                dictation_speed: parseFloat(document.getElementById('setDictationSpeed')?.value || 1.0),
            },
            show_translation_first: document.getElementById('setTranslationFirst')?.classList.contains('active') || false,
            tts_priority: document.getElementById('setTTSPriority')?.value || 'browser',
            translation_priority: document.getElementById('setTranslationPriority')?.value || 'auto',
            translation_display: document.getElementById('setTranslationDisplay')?.value || 'after',
        };

        try {
            await fetchWithAuth(`${API}/api/settings`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings),
            });
            S.settings = settings;
            S.calibrationEnabled = settings.learning.calibration_enabled;
            alert('设置已保存！');
        } catch { alert('保存失败'); }
    });
}

// ============================================================
// Enhanced Stats Dashboard
// ============================================================

// ============================================================
// Bookmarks Modal - 收藏句子查看
// ============================================================
async function openBookmarksModal() {
    let modal = document.getElementById('bookmarksModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'bookmarksModal';
        modal.className = 'modal-overlay';
        modal.innerHTML = `
            <div class="modal" style="max-width:600px;max-height:80vh;">
                <div class="modal-header">
                    <h3>⭐ 我的收藏</h3>
                    <button class="btn-icon modal-close" onclick="document.getElementById('bookmarksModal').style.display='none'">x</button>
                </div>
                <div class="modal-body" id="bookmarksBody" style="overflow-y:auto;max-height:65vh;">
                    <div style="text-align:center;padding:40px;color:var(--text3);"><div class="spinner" style="margin:0 auto 12px;"></div>加载收藏列表...</div>
                </div>
            </div>
        `;
        modal.addEventListener('click', e => { if (e.target === modal) modal.style.display = 'none'; });
        document.body.appendChild(modal);
    }
    modal.style.display = '';
    const body = document.getElementById('bookmarksBody');
    body.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text3);"><div class="spinner" style="margin:0 auto 12px;"></div>加载收藏列表...</div>';
    
    try {
        const r = await fetchWithAuth(`${API}/api/sentences/bookmarked`);
        const data = await r.json();
        const sentences = data.sentences || [];
        
        if (sentences.length === 0) {
            body.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text3);font-size:14px;">暂无收藏的句子<br><span style="font-size:12px;">练习时点击书签按钮收藏句子</span></div>';
            return;
        }
        
        body.innerHTML = sentences.map(s => `
            <div class="bookmark-item" style="padding:12px;border-bottom:1px solid var(--border);cursor:pointer;" onclick="loadBookmarkedSentence('${s.id}')">
                <div style="font-size:14px;font-weight:500;margin-bottom:4px;">${s.text}</div>
                <div style="font-size:12px;color:var(--text3);">${s.translation || ''}</div>
                <div style="font-size:11px;color:var(--text3);margin-top:4px;">
                    <span class="diff-badge ${s.difficulty || 'medium'}" style="font-size:10px;padding:1px 6px;">${(s.difficulty || 'medium').toUpperCase()}</span>
                </div>
            </div>
        `).join('');
    } catch {
        body.innerHTML = '<div style="text-align:center;padding:40px;color:var(--err);">加载失败，请重试</div>';
    }
}

async function loadBookmarkedSentence(sentenceId) {
    const modal = document.getElementById('bookmarksModal');
    if (modal) modal.style.display = 'none';
    try {
        const r = await fetchWithAuth(`${API}/api/sentence/${sentenceId}`);
        if (r.ok) {
            const data = await r.json();
            if (data && data.text) {
                S.sentence = data;
                S.sentenceType = 'review';
                S.mode = 'practice';
                S.fsrsRated = false;
                renderSentence();
                updateModeUI();
            }
        }
    } catch { /* ignore */ }
}

// ============================================================
// Dark/Light Theme Toggle - 夜间/日间模式切换
// ============================================================
function initTheme() {
    const saved = localStorage.getItem('phonos_theme');
    if (saved === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
        updateThemeIcon(true);
    }
}

function toggleTheme() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    if (isDark) {
        document.documentElement.removeAttribute('data-theme');
        localStorage.setItem('phonos_theme', 'light');
    } else {
        document.documentElement.setAttribute('data-theme', 'dark');
        localStorage.setItem('phonos_theme', 'dark');
    }
    updateThemeIcon(!isDark);
}

function updateThemeIcon(isDark) {
    const icon = document.getElementById('themeIcon');
    if (icon) {
        icon.innerHTML = isDark 
            ? '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>'
            : '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
    }
}
