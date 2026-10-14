/* ============================================================
 *  CodeForge — Complete Application Engine (v2.0)
 *  LeetCode-inspired platform, Monaco Editor integration,
 *  test case runner, audio synthesis, and real-time execution.
 * ============================================================ */

(function () {
    'use strict';

    // Storage can be unavailable in private browsing or restricted embeds.
    const Storage = {
        get(key, session = false) {
            try { return window[session ? 'sessionStorage' : 'localStorage'].getItem(key); }
            catch (_) { return null; }
        },
        set(key, value, session = false) {
            try {
                const storage = window[session ? 'sessionStorage' : 'localStorage'];
                if (value === null) storage.removeItem(key);
                else storage.setItem(key, value);
                return true;
            } catch (_) { return false; }
        }
    };
    const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g,
        character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
    const normalizeOutput = value => String(value || '').replace(/\r\n/g, '\n').trim();
    const executionPassed = (result, expected) => result.exit_code === 0 && !result.resource_usage?.output_truncated &&
        !result.timed_out && !result.resource_usage?.timed_out &&
        (!normalizeOutput(expected) || normalizeOutput(result.stdout) === normalizeOutput(expected));
    const reportedTime = result => {
        const value = result.wall_time ?? result.resource_usage?.wall_time;
        return typeof value === 'number' && Number.isFinite(value) ? value : null;
    };
    const copyText = async value => {
        try {
            if (!navigator.clipboard) throw new Error('Clipboard access is unavailable.');
            await navigator.clipboard.writeText(value);
            Toast.show('Copied to clipboard', 'success');
        } catch (_) { Toast.show('Clipboard unavailable. Select the text and copy it manually.', 'error'); }
    };

    // ==========================================================
    //  1. PROBLEM CATALOG & TEST CASES
    // ==========================================================
    const PROBLEMS = {
        'two-sum': {
            id: 'two-sum',
            title: '1. Two Sum',
            difficulty: 'Easy',
            tag: 'Array · Hash Table',
            description: `
                <p>Given an array of integers <code>nums</code> and an integer <code>target</code>, return <em>indices of the two numbers such that they add up to <code>target</code></em>.</p>
                <p>You may assume that each input has <strong>exactly one solution</strong>, and you may not use the same element twice.</p>
                <div class="code-example">
                    <div class="example-title">Example 1:</div>
                    <div class="example-box">
                        <strong>Input:</strong> nums = [2,7,11,15], target = 9<br>
                        <strong>Output:</strong> [0, 1]<br>
                        <strong>Explanation:</strong> Because nums[0] + nums[1] == 9, we return [0, 1].
                    </div>
                </div>
                <div class="code-example">
                    <div class="example-title">Example 2:</div>
                    <div class="example-box">
                        <strong>Input:</strong> nums = [3,2,4], target = 6<br>
                        <strong>Output:</strong> [1, 2]
                    </div>
                </div>
                <div class="problem-constraints">
                    <div class="constraints-title">Constraints:</div>
                    <ul>
                        <li><code>2 &le; nums.length &le; 10<sup>4</sup></code></li>
                        <li><code>-10<sup>9</sup> &le; nums[i] &le; 10<sup>9</sup></code></li>
                        <li>Only one valid answer exists.</li>
                    </ul>
                </div>
            `,
            starter: {
                python: `# 1. Two Sum (LeetCode #1)
# Complexity Target: O(n) time, O(n) space

def two_sum(nums, target):
    seen = {}
    for i, num in enumerate(nums):
        complement = target - num
        if complement in seen:
            return [seen[complement], i]
        seen[num] = i
    return []

if __name__ == "__main__":
    lines = []
    while True:
        try:
            line = input().strip()
            if line:
                lines.append(line)
        except EOFError:
            break
    if lines:
        nums = list(map(int, lines[0].split()))
        target = int(lines[1])
        print(two_sum(nums, target))
    else:
        # Default test
        print(two_sum([2, 7, 11, 15], 9))
`,
                c: `/* 1. Two Sum in C */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    int nums[10000], n = 0, target;
    char line[150000];
    if (!fgets(line, sizeof(line), stdin)) return 1;
    char *token = strtok(line, " \\t\\r\\n");
    while (token && n < 10000) {
        nums[n++] = atoi(token);
        token = strtok(NULL, " \\t\\r\\n");
    }
    if (scanf("%d", &target) != 1) return 1;

    for (int i = 0; i < n; i++) {
        for (int j = i + 1; j < n; j++) {
            if (nums[i] + nums[j] == target) {
                printf("[%d, %d]\\n", i, j);
                return 0;
            }
        }
    }
    printf("[]\\n");
    return 0;
}
`
            },
            testcases: [
                { stdin: "2 7 11 15\n9", expected: "[0, 1]" },
                { stdin: "3 2 4\n6", expected: "[1, 2]" },
                { stdin: "3 3\n6", expected: "[0, 1]" }
            ]
        },

        'palindrome-number': {
            id: 'palindrome-number',
            title: '9. Palindrome Number',
            difficulty: 'Easy',
            tag: 'Math · Two Pointer',
            description: `
                <p>Given an integer <code>x</code>, return <code>true</code> if <code>x</code> is a palindrome, and <code>false</code> otherwise.</p>
                <div class="code-example">
                    <div class="example-title">Example 1:</div>
                    <div class="example-box">
                        <strong>Input:</strong> x = 121<br>
                        <strong>Output:</strong> true<br>
                        <strong>Explanation:</strong> 121 reads as 121 from left to right and from right to left.
                    </div>
                </div>
                <div class="code-example">
                    <div class="example-title">Example 2:</div>
                    <div class="example-box">
                        <strong>Input:</strong> x = -121<br>
                        <strong>Output:</strong> false
                    </div>
                </div>
            `,
            starter: {
                python: `# 9. Palindrome Number
def is_palindrome(x: int) -> bool:
    if x < 0 or (x % 10 == 0 and x != 0):
        return False
    reverted = 0
    while x > reverted:
        reverted = reverted * 10 + x % 10
        x //= 10
    return x == reverted or x == reverted // 10

if __name__ == "__main__":
    try:
        val = input().strip()
    except EOFError:
        val = ""
    x = int(val) if val else 121
    print(str(is_palindrome(x)).lower())
`,
                c: `#include <stdio.h>
#include <stdbool.h>

bool isPalindrome(int x) {
    if (x < 0 || (x % 10 == 0 && x != 0)) return false;
    int reverted = 0;
    while (x > reverted) {
        reverted = reverted * 10 + x % 10;
        x /= 10;
    }
    return x == reverted || x == reverted / 10;
}

int main(void) {
    int x = 121;
    scanf("%d", &x);
    printf("%s\\n", isPalindrome(x) ? "true" : "false");
    return 0;
}
`
            },
            testcases: [
                { stdin: "121", expected: "true" },
                { stdin: "-121", expected: "false" },
                { stdin: "10", expected: "false" }
            ]
        },

        'valid-parentheses': {
            id: 'valid-parentheses',
            title: '20. Valid Parentheses',
            difficulty: 'Easy',
            tag: 'String · Stack',
            description: `
                <p>Given a string <code>s</code> containing just the characters <code>'('</code>, <code>')'</code>, <code>'{'</code>, <code>'}'</code>, <code>'['</code> and <code>']'</code>, determine if the input string is valid.</p>
                <div class="code-example">
                    <div class="example-title">Example 1:</div>
                    <div class="example-box">
                        <strong>Input:</strong> s = "()[]{}"<br>
                        <strong>Output:</strong> true
                    </div>
                </div>
            `,
            starter: {
                python: `# 20. Valid Parentheses
def is_valid(s: str) -> bool:
    stack = []
    mapping = {')': '(', '}': '{', ']': '['}
    for char in s:
        if char in mapping:
            top = stack.pop() if stack else '#'
            if mapping[char] != top:
                return False
        else:
            stack.append(char)
    return not stack

if __name__ == "__main__":
    try:
        s = input().strip()
    except EOFError:
        s = "()[]{}"
    print(str(is_valid(s)).lower())
`,
                c: `#include <stdio.h>
#include <stdbool.h>
#include <string.h>

int main(void) {
    char s[100];
    if (scanf("%99s", s) != 1) {
        strcpy(s, "()[]{}");
    }
    char stack[100];
    int top = -1;
    bool valid = true;

    for (int i = 0; s[i] != '\\0'; i++) {
        char c = s[i];
        if (c == '(' || c == '{' || c == '[') {
            stack[++top] = c;
        } else {
            if (top < 0) { valid = false; break; }
            char open = stack[top--];
            if ((c == ')' && open != '(') ||
                (c == '}' && open != '{') ||
                (c == ']' && open != '[')) {
                valid = false;
                break;
            }
        }
    }
    if (top >= 0) valid = false;
    printf("%s\\n", valid ? "true" : "false");
    return 0;
}
`
            },
            testcases: [
                { stdin: "()[]{}", expected: "true" },
                { stdin: "(]", expected: "false" },
                { stdin: "([{}])", expected: "true" }
            ]
        },

        'max-subarray': {
            id: 'max-subarray',
            title: '53. Maximum Subarray',
            difficulty: 'Medium',
            tag: 'Array · Dynamic Programming',
            description: `
                <p>Given an integer array <code>nums</code>, find the subarray with the largest sum, and return <em>its sum</em> (Kadane's Algorithm).</p>
            `,
            starter: {
                python: `# 53. Maximum Subarray (Kadane's Algorithm)
def max_sub_array(nums):
    max_sum = nums[0]
    current = nums[0]
    for x in nums[1:]:
        current = max(x, current + x)
        max_sum = max(max_sum, current)
    return max_sum

if __name__ == "__main__":
    try:
        raw = input().strip()
    except EOFError:
        raw = ""
    nums = list(map(int, raw.split())) if raw else [-2,1,-3,4,-1,2,1,-5,4]
    print(max_sub_array(nums))
`,
                c: `#include <stdio.h>

int main(void) {
    int nums[10000], n = 0;
    while (n < 10000 && scanf("%d", &nums[n]) == 1) n++;
    if (!n) return 1;
    int max_sum = nums[0], current = nums[0];
    for (int i = 1; i < n; i++) {
        current = (nums[i] > current + nums[i]) ? nums[i] : current + nums[i];
        if (current > max_sum) max_sum = current;
    }
    printf("%d\\n", max_sum);
    return 0;
}
`
            },
            testcases: [
                { stdin: "-2 1 -3 4 -1 2 1 -5 4", expected: "6" },
                { stdin: "1", expected: "1" },
                { stdin: "5 4 -1 7 8", expected: "23" }
            ]
        },

        'prime-sieve': {
            id: 'prime-sieve',
            title: '204. Prime Sieve Benchmark',
            difficulty: 'Medium',
            tag: 'Math · Performance Benchmark',
            description: `
                <p>Count and list all prime numbers strictly less than non-negative integer <code>n</code> using the <strong>Sieve of Eratosthenes</strong>.</p>
            `,
            starter: {
                python: `# 204. Sieve of Eratosthenes Benchmark
def count_primes(n: int):
    if n <= 2:
        return 0, []
    is_prime = [True] * n
    is_prime[0] = is_prime[1] = False
    for p in range(2, int(n**0.5) + 1):
        if is_prime[p]:
            for i in range(p * p, n, p):
                is_prime[i] = False
    primes = [i for i, prime in enumerate(is_prime) if prime]
    return len(primes), primes

if __name__ == "__main__":
    try:
        val = input().strip()
    except EOFError:
        val = ""
    n = int(val) if val else 30
    count, primes = count_primes(n)
    print(f"{count} primes found: {primes}")
`,
                c: `#include <stdio.h>
#include <stdbool.h>

int main(void) {
    int n = 30;
    scanf("%d", &n);
    if (n <= 2) {
        printf("0 primes found: []\\n");
        return 0;
    }
    if (n > 10000) { fprintf(stderr, "Use n <= 10000\\n"); return 1; }
    bool prime[10000];
    for (int i = 0; i < n; i++) prime[i] = true;
    prime[0] = prime[1] = false;

    for (int p = 2; p * p < n; p++) {
        if (prime[p]) {
            for (int i = p * p; i < n; i += p)
                prime[i] = false;
        }
    }
    int count = 0;
    for (int i = 2; i < n; i++) {
        if (prime[i]) count++;
    }
    printf("%d primes found: [", count);
    int printed = 0;
    for (int i = 2; i < n; i++) {
        if (prime[i]) { printf("%s%d", printed ? ", " : "", i); printed++; }
    }
    printf("]\\n");
    return 0;
}
`
            },
            testcases: [
                { stdin: "30", expected: "10 primes found: [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]" },
                { stdin: "10", expected: "4 primes found: [2, 3, 5, 7]" }
            ]
        },

        'sec-fork-bomb': {
            id: 'sec-fork-bomb',
            title: '🛡️ Exploit: Fork Bomb Trap',
            difficulty: 'Hard',
            tag: 'Security Jail · Process Limit',
            description: `
                <p><strong>Security Demo:</strong> This test attempts to spawn infinite child processes (fork bomb) to exhaust host PIDs.</p>
                <p><strong>Defense:</strong> This exact Python sample is rejected by a source-text filter. Filters are bypassable; use Docker for untrusted code.</p>
            `,
            starter: {
                python: `# 🛡️ SECURITY DEMO: Fork Bomb Attack Attempt
# The Sandbox pre-checker & runtime jailing will intercept this!

import os

print("⚡ Attempting rogue process proliferation...")
while True:
    try:
        os.fork()
    except AttributeError:
        # On Windows/platforms without fork
        print("Blocked / fork prohibited by runtime environment!")
        break
    except Exception as e:
        print(f"Jail defended: {e}")
        break
`,
                c: `/* Security Demo: Fork Bomb Attempt */
#include <stdio.h>
#include <unistd.h>

int main(void) {
    printf("Attempting process bomb...\\n");
    // Pre-checker / GCC analysis blocks prohibited system calls
    return 0;
}
`
            },
            testcases: [{ stdin: "", expected: "" }]
        },

        'sec-fs-escape': {
            id: 'sec-fs-escape',
            title: '🛡️ Exploit: Filesystem Traversal',
            difficulty: 'Hard',
            tag: 'Source Filter · File Access',
            description: `
                <p><strong>Security Demo:</strong> Attempts to read sensitive host files (<code>/etc/passwd</code> or root directories).</p>
                <p><strong>Defense:</strong> The Python source filter rejects this example. A temporary work directory alone does not isolate the host filesystem.</p>
            `,
            starter: {
                python: `# 🛡️ SECURITY DEMO: Prohibited Filesystem Access
# The source filter looks for disallowed text patterns before execution.

print("⚡ Testing sandbox directory confinement...")

try:
    with open('/etc/passwd', 'r') as f:
        print("LEAKED:", f.read())
except Exception as e:
    print(f"Defended successfully: {type(e).__name__} - {e}")
`,
                c: `/* Security Demo: Host File Access */
#include <stdio.h>

int main(void) {
    puts("C file access is unrestricted in process mode.");
    puts("Use Docker mode for filesystem isolation.");
    return 0;
}
`
            },
            testcases: [{ stdin: "", expected: "" }]
        },

        'sec-infinite-loop': {
            id: 'sec-infinite-loop',
            title: '🛡️ Exploit: Runaway CPU Hang',
            difficulty: 'Medium',
            tag: 'Security Jail · Watchdog Timer',
            description: `
                <p><strong>Security Demo:</strong> Starts an infinite busy-wait loop.</p>
                <p><strong>Defense:</strong> The configured wall-clock limit terminates this run. Process startup and cleanup add a small overhead.</p>
            `,
            starter: {
                python: `# 🛡️ SECURITY DEMO: Infinite Busy Loop
# Watch the Watchdog terminate this runaway task at the configured time limit.

print("⚡ Initiating infinite computation loop...")
count = 0
while True:
    count += 1
`,
                c: `/* Infinite Loop Watchdog Test */
#include <stdio.h>

int main(void) {
    printf("Entering infinite loop...\\n");
    while (1) {}
    return 0;
}
`
            },
            testcases: [{ stdin: "", expected: "" }]
        },

        'sec-mem-bomb': {
            id: 'sec-mem-bomb',
            title: '🛡️ Exploit: Memory Exhaustion',
            difficulty: 'Hard',
            tag: 'Security Jail · Memory Cap',
            description: `
                <p><strong>Security Demo:</strong> Attempts to allocate 1 GB of memory.</p>
                <p><strong>Defense:</strong> Sandbox memory limits cap memory allocation and prevent system OOM.</p>
            `,
            starter: {
                python: `# 🛡️ SECURITY DEMO: 1GB Memory Exhaustion
# Sandbox sets strict memory limits (256MB cap).

print("⚡ Attempting 1 GB memory chunk allocation...")
try:
    huge_str = "A" * (1024 * 1024 * 1024)  # 1GB
    print("Allocated successfully?")
except MemoryError:
    print("MemoryError triggered! Sandbox memory ceiling held safely.")
`,
                c: `/* Memory Limit Test */
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    printf("Allocating 500MB...\\n");
    void *ptr = malloc(500 * 1024 * 1024);
    if (!ptr) {
        printf("Memory allocation safely denied!\\n");
    }
    return 0;
}
`
            },
            testcases: [{ stdin: "", expected: "" }]
        },

        'custom': {
            id: 'custom',
            title: '⚡ Freeform Sandbox',
            difficulty: 'Easy',
            tag: 'Interactive Code Playground',
            description: `
                <p>Welcome to <strong>CodeForge Freeform Sandbox</strong>!</p>
                <p>Write any Python 3 or C code, pass custom input via standard input (stdin), and execute with captured output, exit codes and measured wall time.</p>
            `,
            starter: {
                python: `# ⚡ Welcome to CodeForge Sandbox!
# Write your code here and press Ctrl+Enter to run.

def main():
    print("⚡ CodeForge Sandbox Engine Active")
    numbers = [3, 1, 4, 1, 5, 9, 2, 6, 5]
    print(f"Sorted numbers: {sorted(numbers)}")
    print("Try choosing a LeetCode problem from the top dropdown!")

if __name__ == "__main__":
    main()
`,
                c: `#include <stdio.h>

int main(void) {
    printf("⚡ CodeForge C Sandbox Online!\\n");
    printf("✨ Compiled with GCC warnings treated as errors.\\n");
    return 0;
}
`
            },
            testcases: [
                { stdin: "", expected: "" }
            ]
        }
    };

    // ==========================================================
    //  2. WEB AUDIO SYNTHESIZER
    // ==========================================================
    const Sound = {
        _ctx: null,
        _enabled: false,

        init() {
            const saved = Storage.get('codeforge-sound');
            this._enabled = saved !== 'false';
            this._updateUI();
        },

        _getContext() {
            if (!this._ctx) {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                if (AudioCtx) this._ctx = new AudioCtx();
            }
            if (this._ctx && this._ctx.state === 'suspended') {
                this._ctx.resume();
            }
            return this._ctx;
        },

        toggle() {
            this._enabled = !this._enabled;
            Storage.set('codeforge-sound', this._enabled);
            this._updateUI();
            if (this._enabled) this.click();
        },

        _updateUI() {
            const btn = document.getElementById('btn-sound-toggle');
            if (!btn) return;
            const iconOn = btn.querySelector('.icon-sound-on');
            const iconOff = btn.querySelector('.icon-sound-off');
            if (iconOn && iconOff) {
                iconOn.hidden = !this._enabled;
                iconOff.hidden = this._enabled;
            }
        },

        click() {
            if (!this._enabled) return;
            try {
                const ctx = this._getContext();
                if (!ctx) return;
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = 'sine';
                osc.frequency.setValueAtTime(600, ctx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(800, ctx.currentTime + 0.04);
                gain.gain.setValueAtTime(0.08, ctx.currentTime);
                gain.gain.linearRampToValueAtTime(0.001, ctx.currentTime + 0.04);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start();
                osc.stop(ctx.currentTime + 0.04);
            } catch {}
        },

        success() {
            if (!this._enabled) return;
            try {
                const ctx = this._getContext();
                if (!ctx) return;
                const notes = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6
                notes.forEach((freq, idx) => {
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.type = 'triangle';
                    osc.frequency.setValueAtTime(freq, ctx.currentTime + idx * 0.07);
                    gain.gain.setValueAtTime(0.12, ctx.currentTime + idx * 0.07);
                    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + idx * 0.07 + 0.28);
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    osc.start(ctx.currentTime + idx * 0.07);
                    osc.stop(ctx.currentTime + idx * 0.07 + 0.28);
                });
            } catch {}
        },

        error() {
            if (!this._enabled) return;
            try {
                const ctx = this._getContext();
                if (!ctx) return;
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = 'sawtooth';
                osc.frequency.setValueAtTime(220, ctx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(130, ctx.currentTime + 0.2);
                gain.gain.setValueAtTime(0.1, ctx.currentTime);
                gain.gain.linearRampToValueAtTime(0.001, ctx.currentTime + 0.2);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start();
                osc.stop(ctx.currentTime + 0.2);
            } catch {}
        }
    };

    // ==========================================================
    //  3. CONFETTI CELEBRATION EFFECT
    // ==========================================================
    const Confetti = {
        _particles: [],
        _animId: null,

        fire() {
            const canvas = document.getElementById('confetti-canvas');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;

            const colors = ['#6366f1', '#38bdf8', '#10b981', '#f59e0b', '#ec4899', '#a855f7'];
            this._particles = [];
            for (let i = 0; i < 90; i++) {
                this._particles.push({
                    x: canvas.width / 2 + (Math.random() - 0.5) * 200,
                    y: canvas.height * 0.45,
                    vx: (Math.random() - 0.5) * 16,
                    vy: (Math.random() - 0.7) * 18,
                    size: Math.random() * 7 + 4,
                    color: colors[Math.floor(Math.random() * colors.length)],
                    rot: Math.random() * 360,
                    vrot: (Math.random() - 0.5) * 10,
                    life: 1.0,
                    decay: Math.random() * 0.015 + 0.008
                });
            }

            if (this._animId) cancelAnimationFrame(this._animId);
            const render = () => {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                let alive = false;
                this._particles.forEach(p => {
                    p.x += p.vx;
                    p.y += p.vy;
                    p.vy += 0.4; // gravity
                    p.rot += p.vrot;
                    p.life -= p.decay;
                    if (p.life > 0) {
                        alive = true;
                        ctx.save();
                        ctx.translate(p.x, p.y);
                        ctx.rotate((p.rot * Math.PI) / 180);
                        ctx.fillStyle = p.color;
                        ctx.globalAlpha = Math.max(0, p.life);
                        ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
                        ctx.restore();
                    }
                });
                if (alive) {
                    this._animId = requestAnimationFrame(render);
                } else {
                    ctx.clearRect(0, 0, canvas.width, canvas.height);
                }
            };
            this._animId = requestAnimationFrame(render);
        }
    };

    // ==========================================================
    //  4. API CLIENT
    // ==========================================================
    const API = {
        async request(path, options = {}, protectedEndpoint = true) {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 12000);
            const headers = { Accept: 'application/json', ...options.headers };
            const token = Storage.get('codeforge-api-token', true);
            if (protectedEndpoint && token) headers.Authorization = `Bearer ${token}`;
            try {
                const response = await fetch(path, { ...options, headers, signal: controller.signal, cache: 'no-store' });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    if (response.status === 401) {
                        Access.open();
                        throw new Error('A valid API token is required. Open Access to connect.');
                    }
                    const error = new Error(data.error || data.detail || `Request failed (${response.status}).`);
                    error.status = response.status;
                    error.payload = data;
                    throw error;
                }
                return data;
            } catch (error) {
                if (error.name === 'AbortError') throw new Error('The server took too long to respond. Please retry.');
                if (error instanceof TypeError) throw new Error('Cannot reach the engine. Check your connection and retry.');
                throw error;
            } finally { clearTimeout(timeout); }
        },
        async submit(language, source, stdin) {
            const limits = Capabilities.config?.limits || {};
            if (limits.max_code_bytes && new TextEncoder().encode(source).length > limits.max_code_bytes)
                throw new Error(`Code exceeds the ${limits.max_code_bytes.toLocaleString()} byte limit.`);
            if (limits.max_stdin_bytes && new TextEncoder().encode(stdin || '').length > limits.max_stdin_bytes)
                throw new Error(`Input exceeds the ${limits.max_stdin_bytes.toLocaleString()} byte limit.`);
            return this.request('/submit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ language, source, stdin: stdin || '' }),
            });
        },

        async status(id) {
            return this.request(`/status/${encodeURIComponent(id)}`);
        },

        async result(id) {
            return this.request(`/result/${encodeURIComponent(id)}`);
        },

        async health() {
            return this.request('/health', {}, false);
        },

        async submissions(limit = 25) {
            return this.request(`/submissions?limit=${limit}`);
        }
    };

    const Access = {
        open() {
            const dialog = document.getElementById('modal-access');
            if (!dialog.open) dialog.showModal();
            document.getElementById('api-token').focus();
        },
        init() {
            document.getElementById('btn-access').addEventListener('click', () => this.open());
            document.getElementById('btn-close-access').addEventListener('click', () => document.getElementById('modal-access').close());
            document.getElementById('access-form').addEventListener('submit', async event => {
                event.preventDefault();
                const input = document.getElementById('api-token');
                const token = input.value.trim();
                if (!token) return;
                if (!Storage.set('codeforge-api-token', token, true)) {
                    Toast.show('Session storage is unavailable. Enable it to connect.', 'error');
                    return;
                }
                input.value = '';
                document.getElementById('modal-access').close();
                this.render();
                await History.load();
            });
            document.getElementById('btn-disconnect').addEventListener('click', () => {
                Storage.set('codeforge-api-token', null, true);
                document.getElementById('api-token').value = '';
                this.render();
                History.render([]);
                document.getElementById('modal-access').close();
                Toast.show('API token removed from this tab', 'info');
            });
            this.render();
        },
        render() {
            const saved = Boolean(Storage.get('codeforge-api-token', true));
            const required = Capabilities.config?.authentication_required;
            document.getElementById('btn-access').textContent = saved ? 'Access • token set' : required ? 'Access • required' : 'Access';
            document.getElementById('btn-disconnect').hidden = !saved;
            document.getElementById('access-status').textContent = required
                ? 'This engine requires an API token from its administrator.'
                : 'Add a token if your engine requires authentication.';
        }
    };

    // ==========================================================
    //  5. THEME MANAGER
    // ==========================================================
    const Theme = {
        _key: 'codeforge-theme',

        init() {
            const saved = Storage.get(this._key);
            const preferred = saved || (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
            this.set(preferred, false);
            const btn = document.getElementById('theme-toggle');
            if (btn) btn.addEventListener('click', () => this.toggle());
        },

        get() {
            return document.documentElement.getAttribute('data-theme') || 'dark';
        },

        set(theme, save = true) {
            document.documentElement.setAttribute('data-theme', theme);
            if (save) Storage.set(this._key, theme);
            const btn = document.getElementById('theme-toggle');
            if (btn) {
                const iconDark = btn.querySelector('.theme-icon--dark');
                const iconLight = btn.querySelector('.theme-icon--light');
                if (iconDark && iconLight) {
                    iconDark.hidden = theme !== 'dark';
                    iconLight.hidden = theme === 'dark';
                }
            }
            if (window.monaco && Editor._instance) {
                monaco.editor.setTheme(theme === 'dark' ? 'codeforge-dark' : 'codeforge-light');
            }
        },

        toggle() {
            this.set(this.get() === 'dark' ? 'light' : 'dark');
            Sound.click();
        }
    };

    // ==========================================================
    //  6. MONACO EDITOR & RESILIENT FALLBACK
    // ==========================================================
    const Editor = {
        _instance: null,
        _fallbackEl: null,
        _currentLang: 'python',
        _fontSize: 14,
        _wordWrap: false,

        init() {
            this._fallbackEl = document.getElementById('editor-fallback');
            const loadingEl = document.getElementById('editor-loading');
            this._activateFallback();
            if (loadingEl) loadingEl.hidden = true;
            // Editing and running work immediately, even when the optional CDN is offline.
            const loader = document.createElement('script');
            loader.src = 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/loader.js';
            loader.async = true;
            loader.onload = () => this._loadMonaco(() => {}, null, loadingEl);
            loader.onerror = () => { document.getElementById('editor-mode').textContent = 'Plain text editor'; };
            document.head.appendChild(loader);
            return Promise.resolve();
        },

        _loadMonaco(resolve, timer, loadingEl) {
            try {
                require.config({
                    paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs' }
                });

                require(['vs/editor/editor.main'], () => {
                    clearTimeout(timer);
                    this._defineThemes();
                    const container = document.getElementById('editor-container');
                    const initialTheme = Theme.get() === 'dark' ? 'codeforge-dark' : 'codeforge-light';

                    this._instance = monaco.editor.create(container, {
                        value: this._fallbackEl.value,
                        language: this._currentLang,
                        theme: initialTheme,
                        fontFamily: "'JetBrains Mono', 'Fira Code', Consolas, monospace",
                        fontSize: this._fontSize,
                        lineHeight: 22,
                        minimap: { enabled: false },
                        scrollBeyondLastLine: false,
                        padding: { top: 14, bottom: 14 },
                        renderLineHighlight: 'all',
                        smoothScrolling: true,
                        cursorBlinking: 'smooth',
                        cursorSmoothCaretAnimation: 'on',
                        bracketPairColorization: { enabled: true },
                        automaticLayout: true,
                        wordWrap: this._wordWrap ? 'on' : 'off',
                        tabSize: 4,
                        lineNumbers: 'on',
                        scrollbar: { verticalScrollbarSize: 6, horizontalScrollbarSize: 6 }
                    });
                    this._fallbackEl.hidden = true;
                    this._instance.onDidChangeModelContent(() => App.saveDraft());
                    document.getElementById('editor-mode').textContent = 'Monaco editor';

                    // Hotkey: Ctrl+Enter -> Run Active Case
                    this._instance.addAction({
                        id: 'run-active-testcase',
                        label: 'Run Code',
                        keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter],
                        run: () => App.runActiveCase()
                    });

                    // Hotkey: Ctrl+Shift+Enter -> Submit All Cases
                    this._instance.addAction({
                        id: 'submit-all-cases',
                        label: 'Submit All Cases',
                        keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.Enter],
                        run: () => App.submitAllCases()
                    });

                    this._instance.onDidChangeCursorPosition((e) => {
                        const cursorEl = document.getElementById('status-cursor');
                        if (cursorEl) cursorEl.textContent = `Ln ${e.position.lineNumber}, Col ${e.position.column}`;
                    });

                    if (loadingEl) loadingEl.hidden = true;
                    resolve();
                }, (err) => {
                    console.warn('Monaco require failed:', err);
                    clearTimeout(timer);
                    this._activateFallback();
                    if (loadingEl) loadingEl.hidden = true;
                    resolve();
                });
            } catch (e) {
                console.warn('Monaco init error:', e);
                clearTimeout(timer);
                this._activateFallback();
                if (loadingEl) loadingEl.hidden = true;
                resolve();
            }
        },

        _activateFallback() {
            if (this._fallbackEl) {
                this._fallbackEl.hidden = false;
                if (this._fallbackBound) return;
                this._fallbackBound = true;
                this._fallbackEl.addEventListener('input', () => App.saveDraft());
                // Add tab support
                this._fallbackEl.addEventListener('keydown', (e) => {
                    if (e.key === 'Tab') {
                        e.preventDefault();
                        const start = this._fallbackEl.selectionStart;
                        const end = this._fallbackEl.selectionEnd;
                        this._fallbackEl.value = this._fallbackEl.value.substring(0, start) + "    " + this._fallbackEl.value.substring(end);
                        this._fallbackEl.selectionStart = this._fallbackEl.selectionEnd = start + 4;
                        App.saveDraft();
                    }
                });
            }
        },

        _defineThemes() {
            monaco.editor.defineTheme('codeforge-dark', {
                base: 'vs-dark',
                inherit: true,
                rules: [
                    { token: 'comment', foreground: '64748b', fontStyle: 'italic' },
                    { token: 'keyword', foreground: 'c084fc', fontStyle: 'bold' },
                    { token: 'string', foreground: '34d399' },
                    { token: 'number', foreground: 'fbbf24' },
                    { token: 'type', foreground: '38bdf8' },
                    { token: 'identifier', foreground: 'f0f6fc' }
                ],
                colors: {
                    'editor.background': '#0d1117',
                    'editor.foreground': '#f0f6fc',
                    'editor.lineHighlightBackground': '#161b2270',
                    'editor.selectionBackground': '#264f7860',
                    'editorCursor.foreground': '#818cf8',
                    'editorLineNumber.foreground': '#475569',
                    'editorLineNumber.activeForeground': '#94a3b8',
                    'editorIndentGuide.background1': '#21262d',
                    'editorIndentGuide.activeBackground1': '#30363d'
                }
            });

            monaco.editor.defineTheme('codeforge-light', {
                base: 'vs',
                inherit: true,
                rules: [
                    { token: 'comment', foreground: '64748b', fontStyle: 'italic' },
                    { token: 'keyword', foreground: '7c3aed', fontStyle: 'bold' },
                    { token: 'string', foreground: '059669' },
                    { token: 'number', foreground: 'd97706' }
                ],
                colors: {
                    'editor.background': '#ffffff',
                    'editor.foreground': '#0f172a',
                    'editor.lineHighlightBackground': '#f1f5f980',
                    'editor.selectionBackground': '#cbd5e180',
                    'editorCursor.foreground': '#6366f1'
                }
            });
        },

        getValue() {
            if (this._instance) return this._instance.getValue();
            return this._fallbackEl ? this._fallbackEl.value : '';
        },

        setValue(val) {
            if (this._instance) this._instance.setValue(val);
            if (this._fallbackEl) this._fallbackEl.value = val;
        },

        setLanguage(lang) {
            this._currentLang = lang;
            if (this._instance) {
                const model = this._instance.getModel();
                if (model) monaco.editor.setModelLanguage(model, lang);
            }
        },

        layout() {
            if (this._instance) this._instance.layout();
        },

        changeFontSize(delta) {
            this._fontSize = Math.max(10, Math.min(26, this._fontSize + delta));
            if (this._instance) {
                this._instance.updateOptions({ fontSize: this._fontSize });
            }
            if (this._fallbackEl) {
                this._fallbackEl.style.fontSize = `${this._fontSize}px`;
            }
        },

        toggleWordWrap() {
            this._wordWrap = !this._wordWrap;
            const btn = document.getElementById('btn-word-wrap');
            if (btn) {
                btn.classList.toggle('active', this._wordWrap);
                btn.setAttribute('aria-pressed', String(this._wordWrap));
            }
            if (this._instance) {
                this._instance.updateOptions({ wordWrap: this._wordWrap ? 'on' : 'off' });
            }
            if (this._fallbackEl) {
                this._fallbackEl.style.whiteSpace = this._wordWrap ? 'pre-wrap' : 'pre';
            }
        },

        focus() {
            if (this._instance) this._instance.focus();
            else if (this._fallbackEl) this._fallbackEl.focus();
        }
    };

    // ==========================================================
    //  7. TESTCASE MANAGER (LeetCode Style)
    // ==========================================================
    const Testcases = {
        _cases: [],
        _activeIdx: 0,

        loadProblem(problemId) {
            const prob = PROBLEMS[problemId] || PROBLEMS['custom'];
            this._cases = JSON.parse(JSON.stringify(prob.testcases || [{ stdin: '', expected: '' }]));
            this._activeIdx = 0;
            this.render();
        },

        render() {
            const chips = document.getElementById('testcase-chips');
            if (!chips) return;
            chips.innerHTML = '';

            this._cases.forEach((tc, idx) => {
                const btn = document.createElement('button');
                btn.className = `testcase-chip ${idx === this._activeIdx ? 'active' : ''}`;
                btn.textContent = `Case ${idx + 1}`;
                btn.dataset.index = idx;
                btn.addEventListener('click', () => {
                    this.saveCurrentInputs();
                    this._activeIdx = idx;
                    this.render();
                    Sound.click();
                });
                chips.appendChild(btn);
            });

            this.populateInputs();
        },

        populateInputs() {
            const tc = this._cases[this._activeIdx] || { stdin: '', expected: '' };
            const stdinEl = document.getElementById('testcase-stdin');
            const expEl = document.getElementById('testcase-expected');
            if (stdinEl) stdinEl.value = tc.stdin || '';
            if (expEl) expEl.value = tc.expected || '';
        },

        saveCurrentInputs() {
            const stdinEl = document.getElementById('testcase-stdin');
            const expEl = document.getElementById('testcase-expected');
            if (this._cases[this._activeIdx]) {
                if (stdinEl) this._cases[this._activeIdx].stdin = stdinEl.value;
                if (expEl) this._cases[this._activeIdx].expected = expEl.value;
            }
        },

        getActiveCase() {
            this.saveCurrentInputs();
            return this._cases[this._activeIdx] || { stdin: '', expected: '' };
        },

        getAllCases() {
            this.saveCurrentInputs();
            return this._cases;
        },

        addCase() {
            this.saveCurrentInputs();
            this._cases.push({ stdin: '', expected: '' });
            this._activeIdx = this._cases.length - 1;
            this.render();
            Sound.click();
            Toast.show(`Added Testcase ${this._cases.length}`, 'info');
        },

        markResult(idx, passed) {
            const chip = document.querySelector(`.testcase-chip[data-index="${idx}"]`);
            if (chip) {
                chip.classList.toggle('passed', passed);
                chip.classList.toggle('failed', !passed);
            }
        },

        clearMarks() {
            document.querySelectorAll('.testcase-chip').forEach(c => {
                c.classList.remove('passed', 'failed');
            });
            const suiteBox = document.getElementById('testcase-suite-results');
            if (suiteBox) suiteBox.hidden = true;
        }
    };

    // ==========================================================
    //  8. OUTPUT MANAGER & VERDICT BANNERS
    // ==========================================================
    const Output = {
        _activeTab: 'testcases',

        switchTab(tab) {
            this._activeTab = tab;
            document.querySelectorAll('.output-tab').forEach((btn) => {
                const isActive = btn.dataset.tab === tab;
                btn.classList.toggle('active', isActive);
                btn.setAttribute('aria-selected', isActive);
            });
            ['testcases', 'stdout', 'stderr', 'details'].forEach((name) => {
                const pane = document.getElementById(`pane-${name}`);
                if (pane) {
                    const isActive = name === tab;
                    pane.classList.toggle('active', isActive);
                    pane.hidden = !isActive;
                }
            });
            Sound.click();
        },

        clear() {
            const stdoutEl = document.getElementById('output-stdout');
            const stderrEl = document.getElementById('output-stderr');
            const detailsEl = document.getElementById('output-details');
            const badge = document.getElementById('stderr-badge');
            const banner = document.getElementById('verdict-banner');

            if (stdoutEl) stdoutEl.innerHTML = '<span class="output-placeholder">Output will appear here after you run your code…</span>';
            if (stderrEl) stderrEl.innerHTML = '<span class="output-placeholder">No errors reported.</span>';
            if (detailsEl) detailsEl.innerHTML = '<span class="output-placeholder">Run code to see sandbox process telemetry &amp; resource consumption.</span>';
            if (badge) badge.hidden = true;
            if (banner) banner.hidden = true;

            Testcases.clearMarks();
            const timeEl = document.getElementById('status-exec-time');
            if (timeEl) timeEl.textContent = '';
        },

        showRunning() {
            const stdoutEl = document.getElementById('output-stdout');
            const stderrEl = document.getElementById('output-stderr');
            const badge = document.getElementById('stderr-badge');
            const banner = document.getElementById('verdict-banner');

            if (stdoutEl) stdoutEl.innerHTML = '<span class="output-placeholder">⏳ Sandboxed Execution in progress…</span>';
            if (stderrEl) stderrEl.innerHTML = '<span class="output-placeholder">Waiting…</span>';
            if (badge) badge.hidden = true;
            if (banner) banner.hidden = true;
        },

        display(result, expectedOutput = '') {
            const stdoutEl = document.getElementById('output-stdout');
            const stderrEl = document.getElementById('output-stderr');
            const detailsEl = document.getElementById('output-details');
            const badge = document.getElementById('stderr-badge');
            const banner = document.getElementById('verdict-banner');
            const bannerTitle = document.getElementById('verdict-title');
            const bannerSub = document.getElementById('verdict-subtitle');
            const bannerIcon = document.getElementById('verdict-icon');
            const bannerTime = document.getElementById('verdict-time');
            const bannerMem = document.getElementById('verdict-mem');

            // Stdout
            const stdout = (result.stdout || '').trim();
            if (stdoutEl) {
                if (stdout) stdoutEl.textContent = result.stdout;
                else stdoutEl.innerHTML = '<span class="output-placeholder">(Program completed with empty stdout)</span>';
            }

            // Stderr
            const stderr = (result.stderr || '').trim();
            if (stderrEl) {
                if (stderr) {
                    stderrEl.textContent = result.stderr;
                    if (badge) badge.hidden = false;
                    if (result.exit_code !== 0 && !stdout) {
                        this.switchTab('stderr');
                    }
                } else {
                    stderrEl.innerHTML = '<span class="output-placeholder">No errors reported.</span>';
                    if (badge) badge.hidden = true;
                }
            }

            // Diagnostics Details
            const exitCode = result.exit_code ?? '—';
            const timedOut = Boolean(result.timed_out || (result.resource_usage && result.resource_usage.timed_out));
            const wallTime = result.wall_time ?? (result.resource_usage && result.resource_usage.wall_time) ?? null;
            const status = result.status || (exitCode === 0 ? 'completed' : 'failed');

            if (detailsEl) {
                detailsEl.innerHTML = `
                    <div class="detail-card">
                        <div class="detail-card__label">Engine Status</div>
                        <div class="detail-card__value ${status === 'completed' ? 'detail-card__value--success' : 'detail-card__value--error'}">${status}</div>
                    </div>
                    <div class="detail-card">
                        <div class="detail-card__label">Exit Code</div>
                        <div class="detail-card__value ${exitCode === 0 ? 'detail-card__value--success' : 'detail-card__value--error'}">${exitCode}</div>
                    </div>
                    <div class="detail-card">
                        <div class="detail-card__label">Wall Time</div>
                        <div class="detail-card__value">${wallTime != null ? (wallTime * 1000).toFixed(1) + ' ms' : '—'}</div>
                    </div>
                    <div class="detail-card">
                        <div class="detail-card__label">Timed Out</div>
                        <div class="detail-card__value ${timedOut ? 'detail-card__value--warn' : ''}">${timedOut ? 'Yes ⏱️' : 'No'}</div>
                    </div>
                `;
            }

            if (wallTime != null) {
                const execEl = document.getElementById('status-exec-time');
                if (execEl) execEl.textContent = `${(wallTime * 1000).toFixed(1)}ms`;
            }

            // Testcase comparison verdict if expectedOutput is provided
            if (banner && expectedOutput.trim()) {
                const normActual = stdout.replace(/\r\n/g, '\n').trim();
                const normExp = expectedOutput.replace(/\r\n/g, '\n').trim();
                banner.hidden = false;

                if (executionPassed(result, expectedOutput)) {
                    banner.className = 'verdict-banner';
                    bannerIcon.textContent = '✅';
                    bannerTitle.textContent = 'Accepted';
                    bannerSub.textContent = 'Output matched expected result perfectly!';
                    Sound.success();
                    Confetti.fire();
                } else if (result.exit_code !== 0) {
                    banner.className = 'verdict-banner verdict-error';
                    bannerIcon.textContent = '❌';
                    bannerTitle.textContent = timedOut ? 'Time Limit Exceeded' : 'Runtime Error';
                    bannerSub.textContent = `Process exited with error code ${exitCode}`;
                    Sound.error();
                } else {
                    banner.className = 'verdict-banner verdict-warn';
                    bannerIcon.textContent = '⚠️';
                    bannerTitle.textContent = 'Wrong Answer';
                    bannerSub.textContent = `Expected: "${normExp}" | Got: "${normActual}"`;
                    Sound.error();
                }

                if (bannerTime) bannerTime.textContent = wallTime != null ? `⚡ ${(wallTime * 1000).toFixed(0)} ms` : 'Time unavailable';
                if (bannerMem) bannerMem.hidden = true;
            }
        }
    };

    // ==========================================================
    //  9. SUBMISSION HISTORY
    // ==========================================================
    const History = {
        async load() {
            try {
                const data = await API.submissions(25);
                this.render(data.submissions || []);
            } catch (e) {
                console.warn('Failed to load history:', e);
            }
        },

        render(items) {
            const listEl = document.getElementById('history-list');
            const emptyEl = document.getElementById('history-empty');
            const countBadge = document.getElementById('history-count');
            if (!listEl) return;

            if (countBadge) {
                countBadge.textContent = items.length;
                countBadge.hidden = items.length === 0;
            }

            if (!items.length) {
                listEl.innerHTML = '<p class="history-empty">No submissions yet. Run a program to begin.</p>';
                if (emptyEl) listEl.appendChild(emptyEl);
                return;
            }
            if (emptyEl) emptyEl.hidden = true;
            listEl.innerHTML = '';

            items.forEach((sub, i) => {
                const el = document.createElement('div');
                el.className = 'history-item';
                el.innerHTML = `
                    <span class="history-item__dot history-item__dot--${sub.status}"></span>
                    <div class="history-item__info">
                        <div class="history-item__id">${sub.id}</div>
                        <div class="history-item__meta">
                            <span>${sub.language === 'python' ? '🐍 Python' : '⚙️ C'}</span>
                            <span>·</span>
                            <span>${this._timeAgo(sub.submitted_at)}</span>
                        </div>
                    </div>
                `;
                el.addEventListener('click', () => this.viewItem(sub.id));
                listEl.appendChild(el);
            });
        },

        _timeAgo(epoch) {
            if (!epoch) return '';
            const s = Math.floor(Date.now() / 1000 - epoch);
            if (s < 5) return 'just now';
            if (s < 60) return `${s}s ago`;
            const m = Math.floor(s / 60);
            if (m < 60) return `${m}m ago`;
            const h = Math.floor(m / 60);
            if (h < 24) return `${h}h ago`;
            return `${Math.floor(h / 24)}d ago`;
        },

        async viewItem(id) {
            try {
                StatusBar.set('running', `Loading ${id.slice(0, 8)}…`);
                const res = await API.result(id);
                Output.display(res);
                Output.switchTab('stdout');
                StatusBar.set('ready', 'Loaded submission result');
                Toast.show(`Loaded submission ${id.slice(0, 8)}`, 'info');
            } catch (e) {
                Toast.show(`Could not load submission: ${e.message}`, 'error');
                StatusBar.set('ready', 'Ready');
            }
        }
    };

    // ==========================================================
    //  10. CAPABILITIES & SYSTEM LIMITS
    // ==========================================================
    const Capabilities = {
        config: null,
        async load() {
            try {
                const [health, settings] = await Promise.all([API.health(), API.request('/api/config', {}, false)]);
                this.config = settings;
                this._render(health.sandbox || {}, settings.limits || {});
                const isolated = settings.sandbox?.isolated;
                document.getElementById('deployment-mode').textContent = isolated
                    ? 'Docker isolation · Network disabled · Ephemeral runs'
                    : 'Local demo · Trusted code only · Process resource limits';
                document.getElementById('status-engine').textContent = isolated ? 'Docker backend' : 'Local process';
                Access.render();
                await this.refreshReadiness();
            } catch (error) {
                document.getElementById('deployment-mode').textContent = 'Engine unavailable — start python run.py';
                this.showOffline();
                ['caps-skeleton', 'limits-skeleton'].forEach(id => document.getElementById(id).hidden = true);
            }
        },
        showOffline() {
            const indicator = document.getElementById('navbar-engine-status');
            indicator.dataset.state = 'offline';
            indicator.querySelector('.engine-status-text').textContent = 'Workers offline';
            document.getElementById('queue-status').textContent = 'Workers offline · Start the worker pool';
        },
        async refreshReadiness() {
            try {
                const data = await API.request('/ready', {}, false);
                const workers = data.workers;
                const indicator = document.getElementById('navbar-engine-status');
                indicator.dataset.state = 'online';
                indicator.title = 'Live worker heartbeat';
                indicator.querySelector('.engine-status-text').textContent = 'Engine online';
                document.getElementById('queue-status').textContent = `${workers.active_workers} workers · ${workers.queued} queued · ${workers.running} running`;
            } catch (_) { this.showOffline(); }
        },
        _render(caps, limits) {
            document.getElementById('caps-skeleton').hidden = true;
            document.getElementById('limits-skeleton').hidden = true;
            document.getElementById('caps-list').innerHTML = Object.entries(caps).map(([key, value]) =>
                `<dt>${escapeHtml(key.replaceAll('_', ' '))}</dt><dd>${escapeHtml(value)}</dd>`).join('');
            document.getElementById('limits-list').innerHTML = [
                ['Wall timeout', `${limits.timeout_seconds}s`], ['CPU budget', `${limits.cpu_seconds}s`],
                ['Memory limit', `${limits.memory_mb} MB`], ['Workers', limits.max_workers],
                ['Output cap', `${limits.max_result_bytes / 1024} KiB`], ['Queue capacity', limits.max_pending_jobs]
            ].map(([label, value]) => `<dt>${label}</dt><dd>${escapeHtml(value)}</dd>`).join('');
        }
    };

    // ==========================================================
    //  11. STATUS BAR & TOASTS
    // ==========================================================
    const StatusBar = {
        set(state, text) {
            const dot = document.getElementById('status-dot');
            const txt = document.getElementById('status-text');
            if (dot) dot.className = `status-dot status-dot--${state}`;
            if (txt) txt.textContent = text;
        },
        setLang(name) {
            const el = document.getElementById('status-lang');
            if (el) el.textContent = name;
        },
        setProblem(title) {
            const el = document.getElementById('status-problem-title');
            if (el) el.textContent = title;
        }
    };

    const Toast = {
        show(msg, type = 'info') {
            const c = document.getElementById('toast-container');
            if (!c) return;
            const el = document.createElement('div');
            el.className = `toast toast--${type}`;
            el.textContent = msg;
            c.appendChild(el);
            setTimeout(() => {
                el.classList.add('removing');
                el.addEventListener('animationend', () => el.remove());
            }, 3600);
        }
    };

    // ==========================================================
    //  12. DRAGGABLE SPLIT PANES
    // ==========================================================
    const SplitPane = {
        init() {
            this._initVertical();
            this._initHorizontal();
        },

        _initVertical() {
            let dragging = false;
            const gutter = document.getElementById('gutter-v');
            const sidebar = document.getElementById('sidebar');
            const workspace = document.getElementById('workspace');
            if (!gutter || !sidebar || !workspace) return;

            const onMove = (e) => {
                if (!dragging) return;
                const clientX = e.clientX || (e.touches && e.touches[0].clientX);
                const rect = workspace.getBoundingClientRect();
                const pct = ((clientX - rect.left) / rect.width) * 100;
                const clamped = Math.max(18, Math.min(50, pct));
                sidebar.style.width = `${clamped}%`;
                Editor.layout();
                e.preventDefault();
            };

            const onEnd = () => {
                dragging = false;
                gutter.classList.remove('active');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onEnd);
                document.removeEventListener('touchmove', onMove);
                document.removeEventListener('touchend', onEnd);
                Editor.layout();
            };

            gutter.addEventListener('mousedown', (e) => {
                dragging = true;
                gutter.classList.add('active');
                document.body.style.cursor = 'col-resize';
                document.body.style.userSelect = 'none';
                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onEnd);
                e.preventDefault();
            });
        },

        _initHorizontal() {
            let dragging = false;
            const gutter = document.getElementById('gutter-h');
            const editorSection = document.getElementById('editor-section');
            const mainPanel = document.getElementById('main-panel');
            if (!gutter || !editorSection || !mainPanel) return;

            const onMove = (e) => {
                if (!dragging) return;
                const clientY = e.clientY || (e.touches && e.touches[0].clientY);
                const rect = mainPanel.getBoundingClientRect();
                const pct = ((clientY - rect.top) / rect.height) * 100;
                const clamped = Math.max(20, Math.min(80, pct));
                editorSection.style.flex = 'none';
                editorSection.style.height = `${clamped}%`;
                Editor.layout();
                e.preventDefault();
            };

            const onEnd = () => {
                dragging = false;
                gutter.classList.remove('active');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onEnd);
                Editor.layout();
            };

            gutter.addEventListener('mousedown', (e) => {
                dragging = true;
                gutter.classList.add('active');
                document.body.style.cursor = 'row-resize';
                document.body.style.userSelect = 'none';
                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onEnd);
                e.preventDefault();
            });
        }
    };

    // ==========================================================
    //  13. MAIN APPLICATION ORCHESTRATION
    // ==========================================================
    const App = {
        _running: false,
        _currentProblemId: 'two-sum',

        setBusy(busy) {
            ['btn-run', 'btn-submit-all', 'problem-select', 'lang-select', 'btn-reset', 'btn-add-testcase'].forEach(id => {
                document.getElementById(id).disabled = busy;
            });
        },

        async init() {
            Theme.init();
            Access.init();
            Sound.init();
            SplitPane.init();
            this._bindEvents();

            // Load editor
            await Editor.init();

            // Load initial problem
            this.setProblem(Storage.get('codeforge-problem') || 'two-sum');

            // Load capabilities and history
            await Capabilities.load();
            if (!Capabilities.config?.authentication_required || Storage.get('codeforge-api-token', true)) History.load();
            setInterval(() => Capabilities.refreshReadiness(), 10000);

            StatusBar.set('ready', 'Ready to edit');
            Editor.focus();
        },

        _bindEvents() {
            // Problem picker
            const probSelect = document.getElementById('problem-select');
            if (probSelect) {
                probSelect.addEventListener('change', (e) => {
                    this.setProblem(e.target.value);
                    Sound.click();
                });
            }

            // Audio toggle button
            const soundBtn = document.getElementById('btn-sound-toggle');
            if (soundBtn) {
                soundBtn.addEventListener('click', () => Sound.toggle());
            }

            // Shortcuts modal
            const shortcutsBtn = document.getElementById('btn-shortcuts-help');
            const modal = document.getElementById('modal-shortcuts');
            const closeBtn = document.getElementById('btn-close-modal');
            if (shortcutsBtn && modal) {
                shortcutsBtn.addEventListener('click', () => {
                    modal.hidden = false;
                    Sound.click();
                });
            }
            if (closeBtn && modal) {
                closeBtn.addEventListener('click', () => {
                    modal.hidden = true;
                    Sound.click();
                });
            }
            if (modal) {
                modal.addEventListener('click', (e) => {
                    if (e.target === modal) modal.hidden = true;
                });
            }

            // Sidebar Tabs (Problem / Sandbox / History)
            document.querySelectorAll('.sidebar-tab').forEach((tab) => {
                tab.addEventListener('click', () => {
                    const target = tab.dataset.sideTab;
                    document.querySelectorAll('.sidebar-tab').forEach(t => {
                        t.classList.toggle('active', t === tab);
                        t.setAttribute('aria-selected', String(t === tab));
                    });
                    ['problem', 'security', 'history'].forEach(name => {
                        const panel = document.getElementById(`side-panel-${name}`);
                        if (panel) {
                            panel.classList.toggle('active', name === target);
                            panel.hidden = name !== target;
                        }
                    });
                    Sound.click();
                    if (target === 'history') History.load();
                });
            });

            // Output Tabs
            const outTabs = document.getElementById('output-tabs');
            if (outTabs) {
                outTabs.addEventListener('click', (e) => {
                    const btn = e.target.closest('.output-tab');
                    if (btn && btn.dataset.tab) Output.switchTab(btn.dataset.tab);
                });
            }

            // Language Selector
            const langSelect = document.getElementById('lang-select');
            if (langSelect) {
                langSelect.addEventListener('change', (e) => {
                    const lang = e.target.value;
                    this.saveDraft();
                    this._loadingDraft = true;
                    this._draftLanguage = lang;
                    Editor.setLanguage(lang);
                    StatusBar.setLang(lang === 'python' ? 'Python 3' : 'C (GCC)');
                    const starter = PROBLEMS[this._currentProblemId].starter[lang];
                    Editor.setValue(Storage.get(`codeforge-draft:${this._currentProblemId}:${lang}`) ?? starter ?? '');
                    this._loadingDraft = false;
                    Sound.click();
                    Editor.focus();
                });
            }

            // Font Controls & Word Wrap
            const fontInc = document.getElementById('btn-font-inc');
            const fontDec = document.getElementById('btn-font-dec');
            const wordWrap = document.getElementById('btn-word-wrap');
            if (fontInc) fontInc.addEventListener('click', () => { Editor.changeFontSize(1); Sound.click(); });
            if (fontDec) fontDec.addEventListener('click', () => { Editor.changeFontSize(-1); Sound.click(); });
            if (wordWrap) wordWrap.addEventListener('click', () => { Editor.toggleWordWrap(); Sound.click(); });

            // Copy Code Button
            const copyCodeBtn = document.getElementById('btn-copy-code');
            if (copyCodeBtn) {
                copyCodeBtn.addEventListener('click', () => {
                    const val = Editor.getValue();
                    if (val) {
                        copyText(val);
                    }
                });
            }

            // Reset Code Button
            const resetBtn = document.getElementById('btn-reset');
            if (resetBtn) {
                resetBtn.addEventListener('click', () => {
                    const lang = document.getElementById('lang-select').value;
                    const starter = PROBLEMS[this._currentProblemId].starter[lang];
                    if (starter) {
                        Editor.setValue(starter);
                        this.saveDraft();
                        Toast.show('Code reset to starter template', 'info');
                        Sound.click();
                        Editor.focus();
                    }
                });
            }

            // Add Testcase Button
            const addCaseBtn = document.getElementById('btn-add-testcase');
            if (addCaseBtn) {
                addCaseBtn.addEventListener('click', () => Testcases.addCase());
            }

            // Run Active Case Button
            const runBtn = document.getElementById('btn-run');
            if (runBtn) {
                runBtn.addEventListener('click', () => this.runActiveCase());
            }

            // Submit All Cases Button (LeetCode Submit)
            const submitAllBtn = document.getElementById('btn-submit-all');
            if (submitAllBtn) {
                submitAllBtn.addEventListener('click', () => this.submitAllCases());
            }

            // Copy & Clear Output
            const copyOut = document.getElementById('btn-copy-output');
            const clearOut = document.getElementById('btn-clear-output');
            if (copyOut) {
                copyOut.addEventListener('click', () => {
                    const pre = document.getElementById('output-stdout');
                    if (pre && pre.textContent) {
                        copyText(pre.textContent);
                    }
                });
            }
            if (clearOut) {
                clearOut.addEventListener('click', () => {
                    Output.clear();
                    Sound.click();
                });
            }

            // Refresh History
            const refreshHist = document.getElementById('btn-refresh-history');
            if (refreshHist) {
                refreshHist.addEventListener('click', () => {
                    History.load();
                    Sound.click();
                });
            }

            // Global Shortcuts
            window.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'Enter') {
                    e.preventDefault();
                    this.submitAllCases();
                } else if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                    e.preventDefault();
                    this.runActiveCase();
                } else if ((e.ctrlKey || e.metaKey) && e.key === 'l') {
                    e.preventDefault();
                    Output.clear();
                } else if ((e.ctrlKey || e.metaKey) && (e.key === '=' || e.key === '+')) {
                    e.preventDefault();
                    Editor.changeFontSize(1);
                } else if ((e.ctrlKey || e.metaKey) && e.key === '-') {
                    e.preventDefault();
                    Editor.changeFontSize(-1);
                } else if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                    e.preventDefault();
                    this.saveDraft();
                    Toast.show('Draft saved in this browser', 'info');
                } else if (e.key === 'Escape') {
                    const m = document.getElementById('modal-shortcuts');
                    if (m && !m.hidden) m.hidden = true;
                }
            });

            // Window resize -> relayout Monaco
            window.addEventListener('resize', () => Editor.layout());
        },

        saveDraft() {
            if (this._loadingDraft) return;
            const lang = this._draftLanguage || document.getElementById('lang-select').value;
            Storage.set(`codeforge-draft:${this._currentProblemId}:${lang}`, Editor.getValue());
        },

        setProblem(problemId) {
            if (this._draftLanguage) this.saveDraft();
            if (!PROBLEMS[problemId]) problemId = 'two-sum';
            this._currentProblemId = problemId;
            Storage.set('codeforge-problem', problemId);
            const prob = PROBLEMS[problemId] || PROBLEMS['custom'];

            // Update Sidebar Description
            const titleEl = document.getElementById('problem-title');
            const diffEl = document.getElementById('problem-difficulty');
            const tagEl = document.getElementById('problem-tag');
            const descEl = document.getElementById('problem-description');

            if (titleEl) titleEl.textContent = prob.title;
            if (diffEl) {
                diffEl.textContent = prob.difficulty;
                diffEl.className = `difficulty-badge difficulty-${prob.difficulty.toLowerCase()}`;
            }
            if (tagEl) tagEl.textContent = prob.tag;
            if (descEl) descEl.innerHTML = prob.description;

            // Update Dropdown
            const selectEl = document.getElementById('problem-select');
            if (selectEl) selectEl.value = problemId;

            // Update Status Bar
            StatusBar.setProblem(prob.title);

            // Update Editor Starter Code
            const lang = document.getElementById('lang-select').value;
            const starter = prob.starter[lang] || prob.starter.python || '';
            this._loadingDraft = true;
            this._draftLanguage = lang;
            Editor.setValue(Storage.get(`codeforge-draft:${problemId}:${lang}`) ?? starter);
            this._loadingDraft = false;

            // Load Testcases
            Testcases.loadProblem(problemId);
            Output.clear();
        },

        async runActiveCase() {
            if (this._running) return;
            this._running = true;
            this.setBusy(true);

            const runBtn = document.getElementById('btn-run');
            if (runBtn) runBtn.classList.add('running');
            Sound.click();

            const language = document.getElementById('lang-select').value;
            const source = Editor.getValue();
            const activeTc = Testcases.getActiveCase();

            if (!source.trim()) {
                Toast.show('Code is empty!', 'error');
                if (runBtn) runBtn.classList.remove('running');
                this._running = false;
                this.setBusy(false);
                return;
            }

            StatusBar.set('running', 'Executing Sandbox task…');
            Output.showRunning();

            try {
                const sub = await API.submit(language, source, activeTc.stdin);
                StatusBar.set('running', `Job Queued: ${sub.id.slice(0, 8)}…`);
                const res = await this._pollUntilDone(sub.id);
                Output.display(res, activeTc.expected);
                Output.switchTab(res.exit_code === 0 ? 'stdout' : 'stderr');

                if (res.exit_code === 0) {
                    StatusBar.set('ready', 'Execution Completed');
                } else {
                    StatusBar.set('error', `Exited with code ${res.exit_code}`);
                }
            } catch (err) {
                StatusBar.set('error', 'Execution Error');
                Toast.show(`Execution Error: ${err.message}`, 'error');
                Sound.error();
            } finally {
                if (runBtn) runBtn.classList.remove('running');
                this._running = false;
                this.setBusy(false);
                setTimeout(() => History.load(), 500);
            }
        },

        async submitAllCases() {
            if (this._running) return;
            this._running = true;
            this.setBusy(true);

            const submitBtn = document.getElementById('btn-submit-all');
            if (submitBtn) submitBtn.classList.add('running');
            Sound.click();

            const language = document.getElementById('lang-select').value;
            const source = Editor.getValue();
            const allCases = Testcases.getAllCases().map(tc => ({ ...tc }));

            if (!source.trim()) {
                Toast.show('Code is empty!', 'error');
                if (submitBtn) submitBtn.classList.remove('running');
                this._running = false;
                this.setBusy(false);
                return;
            }

            Output.switchTab('testcases');
            const suiteBox = document.getElementById('testcase-suite-results');
            const itemsBox = document.getElementById('suite-items-container');
            if (suiteBox) suiteBox.hidden = false;
            if (itemsBox) itemsBox.innerHTML = '';

            let allPassed = true;
            let lastResult = null;
            let totalTime = 0;

            try {
                for (let i = 0; i < allCases.length; i++) {
                    const tc = allCases[i];
                    StatusBar.set('running', `Testing Case ${i + 1}/${allCases.length}…`);

                    const sub = await API.submit(language, source, tc.stdin);
                    const res = await this._pollUntilDone(sub.id);
                    lastResult = res;

                    const wallTime = res.wall_time ?? (res.resource_usage && res.resource_usage.wall_time) ?? 0;
                    totalTime += wallTime;

                    const normActual = (res.stdout || '').replace(/\r\n/g, '\n').trim();
                    const normExpected = (tc.expected || '').replace(/\r\n/g, '\n').trim();

                    const passed = executionPassed(res, tc.expected);
                    Testcases.markResult(i, passed);

                    if (!passed) allPassed = false;

                    if (itemsBox) {
                        const itemEl = document.createElement('div');
                        itemEl.className = `suite-item ${passed ? 'passed' : 'failed'}`;
                        itemEl.innerHTML = `
                            <span><strong>Case ${i + 1}:</strong> ${passed ? '✅ Passed' : '❌ Failed'}</span>
                            <span style="font-family: var(--font-mono); color: var(--text-3);">${(wallTime * 1000).toFixed(0)} ms</span>
                        `;
                        itemsBox.appendChild(itemEl);
                    }

                    if (!passed && allCases.length > 1) {
                        // Stop or display first failure
                        break;
                    }
                }

                if (lastResult) {
                    Output.display(lastResult);
                    const banner = document.getElementById('verdict-banner');
                    banner.hidden = false;
                    banner.className = allPassed ? 'verdict-banner' : 'verdict-banner verdict-banner--wrong';
                    document.getElementById('verdict-title').textContent = allPassed ? 'All cases passed' : 'Test case failed';
                    document.getElementById('verdict-icon').textContent = allPassed ? '✓' : '!';
                    document.getElementById('verdict-subtitle').textContent = allPassed
                        ? `${allCases.length} cases executed successfully. Cases without expected output check exit status only.`
                        : 'Execution stopped at the first failing case. Review its output below.';
                    document.getElementById('verdict-time').textContent = `${(totalTime * 1000).toFixed(1)} ms total`;
                    document.getElementById('verdict-mem').hidden = true;
                }

                if (allPassed) {
                    StatusBar.set('ready', 'All Test Cases Passed!');
                    Toast.show('Accepted! All test cases passed ✅', 'success');
                    Sound.success();
                    Confetti.fire();
                } else {
                    StatusBar.set('error', 'Some Test Cases Failed');
                    Toast.show('Test case failure detected ❌', 'error');
                    Sound.error();
                }

            } catch (err) {
                StatusBar.set('error', 'Execution Error');
                Toast.show(`Test Suite Error: ${err.message}`, 'error');
                Sound.error();
            } finally {
                if (submitBtn) submitBtn.classList.remove('running');
                this._running = false;
                this.setBusy(false);
                setTimeout(() => History.load(), 500);
            }
        },

        async _pollUntilDone(id) {
            const deadline = Date.now() + 45000;
            while (Date.now() < deadline) {
                const statusData = await API.status(id);
                if (statusData.status === 'completed' || statusData.status === 'failed') {
                    return await API.result(id);
                }
                await new Promise((r) => setTimeout(r, 350));
            }
            throw new Error('Still waiting for a worker. Your job is saved; check History for its result.');
        }
    };

    // ==========================================================
    //  14. LAUNCH
    // ==========================================================
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => App.init());
    } else {
        App.init();
    }

    // Expose for debugging if needed
    window.CodeForge = { App, Editor, Testcases, Output, Sound, PROBLEMS };
})();
