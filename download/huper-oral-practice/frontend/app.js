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
    stats: loadStats(),
    // --- New state ---
    mode: 'dictation',          // 'dictation' | 'practice'
    ttsFailCount: 0,
    ttsMode: 'browser',         // 'browser' | 'server'
    dictationResults: null,     // { words: [...], checked: bool }
    fsrsRated: false,           // whether user has rated this sentence
    sentenceType: 'new',        // 'new' | 'review'
    pendingReviewCount: 0,
    ttsSpeed: 1.0,              // TTS playback speed for dictation
    phonemeAudioCache: {},      // Cache for IPA audio blobs
};

function loadStats() {
    try {
        const d = localStorage.getItem('phonos_stats');
        return d ? JSON.parse(d) : { total: 0, scores: [], errors: {}, words_learned: {}, sessions: 0 };
    } catch { return { total: 0, scores: [], errors: {}, words_learned: {}, sessions: 0 }; }
}

function saveStats() {
    try { localStorage.setItem('phonos_stats', JSON.stringify(S.stats)); } catch {}
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

    // Non-critical: load in parallel, don't block
    checkHealth();
    loadPhonemeTips();
    fetchReviewCount();

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
        const r = await fetch(`${API}/api/fsrs/due-count`);
        if (r.ok) {
            const d = await r.json();
            S.pendingReviewCount = d.count || 0;
            updateReviewCounter();
        }
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
                const r = await fetch(`${API}/api/sentence?force_new=true&_t=${seed}`, {signal: AbortSignal.timeout(10000)});
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

        // Try FSRS queue first (only when not forceNew)
        if (!loaded && !forceNew) {
            try {
                const r = await fetch(`${API}/api/fsrs/next`, {signal: AbortSignal.timeout(8000)});
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

        // Fallback: get a random sentence (ensure different from previous)
        if (!loaded) {
            let attempts = 0;
            do {
                try {
                    const seed = Date.now() + attempts;
                    const r = await fetch(`${API}/api/sentence?_t=${seed}`, {signal: AbortSignal.timeout(8000)});
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
        S.fsrsRated = false;

        renderSentence();
        renderDictationInputs();
        updateModeUI();
        fetchReviewCount();
    } catch (e) {
        console.error('loadSentence error:', e);
        el.sentenceEn.textContent = '加载失败，请点击刷新重试';
        el.diffBadge.textContent = '--';
        el.diffBadge.className = 'diff-badge';
    }
}

function renderSentence() {
    const s = S.sentence;
    el.sentenceEn.textContent = s.text;
    el.sentenceZh.textContent = s.translation || '';
    el.diffBadge.textContent = s.difficulty.toUpperCase();
    el.diffBadge.className = 'diff-badge ' + s.difficulty;

    // Review badge
    if (S.sentenceType === 'review') {
        el.reviewBadge.style.display = '';
        el.reviewBadge.textContent = '复习';
        el.reviewBadge.className = 'review-badge review';
    } else {
        el.reviewBadge.style.display = '';
        el.reviewBadge.textContent = '新句';
        el.reviewBadge.className = 'review-badge new';
    }

    // IPA section
    el.ipaSection.style.display = S.ipaVisible ? '' : 'none';
    if (S.ipaVisible) renderIPAChips();

    // Key phrases
    if (s.key_phrases && s.key_phrases.length) {
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
    S.recordedBlob = null;
    S.recordedUrl = null;
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
        <div class="word-item">
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
    if (S.ttsMode === 'browser') {
        speakBrowserTTS(useSpeed);
    } else {
        speakServerTTS(useSpeed);
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

    const words = S.sentence.text.split(/\s+/);
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
        const r = await fetch(`${API}/api/dictation/check`, {
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
        const alignmentResults = backendResults.results;
        const inputMap = new Map();

        let ei = 0, ui = 0;
        for (const r of alignmentResults) {
            if (r.type === 'match') {
                inputMap.set(ui, { correct: true, expected: r.expected });
                ei++; ui++;
            } else if (r.type === 'substitution') {
                inputMap.set(ui, { correct: false, expected: r.expected });
                ei++; ui++;
            } else if (r.type === 'deletion') {
                ei++;
            } else if (r.type === 'insertion') {
                ui++;
            }
        }

        inputs.forEach((input, i) => {
            const mapped = inputMap.get(i);
            input.classList.remove('correct', 'incorrect');
            if (mapped) {
                input.classList.add(mapped.correct ? 'correct' : 'incorrect');
                if (mapped.correct) {
                    correctCount++;
                } else {
                    const answerEl = document.getElementById(`dictAnswer${i}`);
                    if (answerEl) {
                        answerEl.textContent = mapped.expected;
                        answerEl.style.display = '';
                    }
                }
            } else {
                input.classList.add('incorrect');
            }
            input.disabled = true;
        });

        const totalExpected = expectedWords.filter(w => w).length;
        el.dictationResults.style.display = '';
        el.dictationResults.innerHTML = `
            <div class="dict-result-summary">
                <span class="correct-count">${correctCount}</span>
                <span class="total-count">/ ${totalExpected} 正确</span>
            </div>
        `;
        el.dictationActions.style.display = 'none';
        el.dictationTransition.style.display = '';
        S.dictationResults = { correct: correctCount, total: totalExpected, checked: true };
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
}

function transitionToPractice() {
    S.mode = 'practice';
    updateModeUI();

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
        const r = await fetch(`${API}/api/fsrs/review`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                card_id: cardId,
                rating: rating,
            }),
        });

        if (r.ok) {
            S.fsrsRated = true;
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
        S.recTimer = setInterval(updateRecTime, 200);

        // Start waveform visualization
        startWaveform();
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
    if (r.width === 0 || r.height === 0) return; // Canvas not visible yet
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

        const res = await fetch(`${API}/api/evaluate`, { method: 'POST', body: fd });
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
// Results
// ============================================================
function renderResults(d) {
    el.resultCard.style.display = '';

    S.fsrsRated = false;
    document.querySelectorAll('.fsrs-btn').forEach(btn => btn.classList.remove('selected'));

    animNum(el.overallScore, d.scores.overall, 1200);
    animRing(d.scores.overall);
    animSub(el.pronVal, el.pronFill, d.scores.pronunciation);
    animSub(el.compVal, el.compFill, d.scores.completeness);
    animSub(el.fluVal, el.fluFill, d.scores.fluency);

    renderWordScores(d.words || []);
    renderPhonemes(d);
    renderFluency(d.fluency_details || {});
    renderTips(d.tips || []);

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
        const c = w.accuracy >= 80 ? 'hi' : w.accuracy >= 50 ? 'md' : 'lo';
        return `<div class="ws-item${w.has_error ? ' err' : ''}"><div class="ws-word">${w.word}</div><div class="ws-acc ${c}">${w.accuracy}%</div></div>`;
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
        const cls = errPos.has(i) ? 'bad' : 'ok';
        const ipa = ARPABET_TO_IPA[p] || '';
        const ipaLabel = ipa ? `/${ipa}/` : '';
        return `<span class="ph-chip ${cls} clickable" title="${ipaLabel} - 点击听发音" data-arpabet="${p}" onclick="pronounceResultPhoneme(this)">${ipa ? ipa : p}<span style="font-size:9px;opacity:0.6;margin-left:2px;">${p}</span></span>`;
    }).join('');

    el.phActual.innerHTML = act.map(p => {
        const cls = exp.includes(p) ? 'ok' : 'extra';
        const ipa = ARPABET_TO_IPA[p] || '';
        const ipaLabel = ipa ? `/${ipa}/` : '';
        return `<span class="ph-chip ${cls} clickable" title="${ipaLabel} - 点击听发音" data-arpabet="${p}" onclick="pronounceResultPhoneme(this)">${ipa ? ipa : p}<span style="font-size:9px;opacity:0.6;margin-left:2px;">${p}</span></span>`;
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
    S.stats.total++;
    S.stats.sessions++;
    S.stats.scores.push(data.scores.overall);
    if (S.stats.scores.length > 50) S.stats.scores = S.stats.scores.slice(-50);

    (data.errors || []).forEach(e => {
        if (e.expected && e.type !== 'insertion') {
            if (!S.stats.errors[e.expected]) S.stats.errors[e.expected] = 0;
            S.stats.errors[e.expected]++;
        }
    });

    (data.words || []).forEach(w => {
        S.stats.words_learned[w.word] = S.stats.words_learned[w.word] || { attempts: 0, best: 0 };
        S.stats.words_learned[w.word].attempts++;
        S.stats.words_learned[w.word].best = Math.max(S.stats.words_learned[w.word].best, w.accuracy);
    });

    saveStats();
}

function openStats() {
    const s = S.stats;
    const avg = s.scores.length ? (s.scores.reduce((a, b) => a + b, 0) / s.scores.length).toFixed(1) : 0;
    const best = s.scores.length ? Math.max(...s.scores) : 0;
    const wordsCount = Object.keys(s.words_learned).length;

    const topErrors = Object.entries(s.errors)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5)
        .map(([p, c]) => {
            const ipa = ARPABET_TO_IPA[p] || p;
            return `/${ipa}/ (${c}次)`;
        })
        .join('、') || '暂无';

    const weakWords = Object.entries(s.words_learned)
        .filter(([_, d]) => d.best < 70)
        .map(([w, d]) => w)
        .slice(0, 10);

    el.statsModalBody.innerHTML = `
        <div class="stats-grid">
            <div class="stat-card"><div class="sc-val">${s.total}</div><div class="sc-label">练习次数</div></div>
            <div class="stat-card"><div class="sc-val">${avg}</div><div class="sc-label">平均分</div></div>
            <div class="stat-card"><div class="sc-val">${best}</div><div class="sc-label">最高分</div></div>
            <div class="stat-card"><div class="sc-val">${wordsCount}</div><div class="sc-label">已学单词</div></div>
        </div>
        ${S.pendingReviewCount > 0 ? `
        <div style="margin-bottom:12px;padding:12px;background:#eef2ff;border-radius:8px;text-align:center;">
            <span style="font-size:14px;font-weight:700;color:var(--pri);">${S.pendingReviewCount} 句待复习</span>
        </div>` : ''}
        <div class="error-pattern">
            <h4>最常出错音素</h4>
            <p>${topErrors}</p>
        </div>
        ${weakWords.length ? `
        <div style="margin-top:12px;padding:12px;background:#fef3c7;border-radius:8px;">
            <h4 style="font-size:13px;color:#92400e;margin-bottom:6px;">需要复习的单词</h4>
            <p style="font-size:12px;color:#92400e;">${weakWords.map(w => `<span style="display:inline-block;padding:2px 8px;margin:2px;background:#fde68a;border-radius:4px;font-weight:600;">${w}</span>`).join('')}</p>
        </div>` : ''}
    `;
    el.statsModal.style.display = 'flex';
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
// Boot
// ============================================================
document.addEventListener('DOMContentLoaded', init);
