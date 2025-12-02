document.addEventListener('DOMContentLoaded', function () {
    loadConfig();
    updateStatus();

    // 5초마다 상태 갱신
    setInterval(updateStatus, 5000);

    // 3초마다 로그 갱신
    setInterval(updateLogs, 3000);

    // 계정 설정 저장
    document.querySelector('#account-form button[type="submit"]').addEventListener('click', function (e) {
        e.preventDefault();
        saveConfig('account');
    });

    // 구매 설정 저장
    document.querySelector('#purchase-form button[type="submit"]').addEventListener('click', function (e) {
        e.preventDefault();
        saveConfig('purchase');
    });

    // 예치금 설정 저장
    document.querySelector('#deposit-form button[type="submit"]').addEventListener('click', function (e) {
        e.preventDefault();
        saveConfig('deposit');
    });

    // 스케줄 설정 저장
    document.querySelector('#schedule-form button[type="submit"]').addEventListener('click', function (e) {
        e.preventDefault();
        saveConfig('schedule');
    });

    // 시스템 설정 저장
    document.querySelector('#system-form button[type="submit"]').addEventListener('click', function (e) {
        e.preventDefault();
        saveConfig('system');
    });

    // 봇 시작
    document.getElementById('btn-start').addEventListener('click', function () {
        fetch('/api/bot/start', { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                alert(data.message);
                updateStatus();
            })
            .catch(error => console.error('Error starting bot:', error));
    });

    // 봇 중지
    document.getElementById('btn-stop').addEventListener('click', function () {
        fetch('/api/bot/stop', { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                alert(data.message);
                updateStatus();
            })
            .catch(error => console.error('Error stopping bot:', error));
    });

    // 로그인 테스트
    document.getElementById('btn-test-login').addEventListener('click', function () {
        const userId = document.getElementById('user_id').value;
        const userPw = document.getElementById('user_pw').value;

        if (!userId || !userPw) {
            alert('아이디와 비밀번호를 입력해주세요.');
            return;
        }

        this.disabled = true;
        this.textContent = '테스트 중...';

        fetch('/api/test/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_id: userId,
                user_pw: userPw
            })
        })
            .then(response => response.json())
            .then(data => {
                alert(data.message);
            })
            .catch(error => {
                console.error('Error:', error);
                alert('로그인 테스트 중 오류가 발생했습니다.');
            })
            .finally(() => {
                document.getElementById('btn-test-login').disabled = false;
                document.getElementById('btn-test-login').textContent = '로그인 테스트';
            });
    });

    // 예치금 충전 테스트 (OCR)
    document.getElementById('btn-test-deposit').addEventListener('click', function () {
        if (!confirm("충전 테스트를 시작하시겠습니까?\n실제 브라우저가 열리고 5,000원 충전을 시도합니다.\n(결제 비밀번호 입력까지만 진행하고 실제 결제는 하지 않을 수 있습니다.)")) {
            return;
        }

        this.disabled = true;
        this.textContent = '테스트 중...';

        fetch('/api/test/deposit', { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                alert(data.message);
            })
            .catch(error => {
                console.error('Error:', error);
                alert('충전 테스트 중 오류가 발생했습니다.');
            })
            .finally(() => {
                document.getElementById('btn-test-deposit').disabled = false;
                document.getElementById('btn-test-deposit').textContent = '충전 테스트 (OCR)';
            });
    });
});

function renderGameSlots(games) {
    const container = document.getElementById('games-container');
    container.innerHTML = '';

    games.forEach((game, index) => {
        const slot = document.createElement('div');
        slot.className = `game-slot ${getSlotClass(game.mode)}`;
        // active 속성이 없으면 기본값 true
        const isActive = game.active !== undefined ? game.active : true;

        slot.innerHTML = `
            <div class="slot-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <h4 style="margin: 0;">Game ${index + 1}</h4>
                <label class="switch">
                    <input type="checkbox" id="game_active_${index}" ${isActive ? 'checked' : ''}>
                    <span class="slider round"></span>
                </label>
            </div>
            <div class="mode-select">
                <select id="game_mode_${index}" onchange="toggleInputs(this, ${index})" ${!isActive ? 'disabled' : ''}>
                    <option value="auto" ${game.mode === 'auto' ? 'selected' : ''}>자동 (Auto)</option>
                    <option value="semi_auto" ${game.mode === 'semi_auto' ? 'selected' : ''}>반자동 (Semi-Auto)</option>
                    <option value="manual" ${game.mode === 'manual' ? 'selected' : ''}>수동 (Manual)</option>
                    <option value="ai" ${game.mode === 'ai' ? 'selected' : ''}>AI 추천 (Deep Learning)</option>
                    <option value="max_first" ${game.mode === 'max_first' ? 'selected' : ''}>1등 최다 번호 (Max 1st)</option>
                </select>
            </div>
            <div class="analysis-input" id="game_analysis_div_${index}" style="display: ${game.mode === 'max_first' ? 'block' : 'none'};">
                <label>분석 범위 (최근 회차)</label>
                <select id="game_analysis_${index}" ${!isActive ? 'disabled' : ''}>
                    <option value="10" ${game.analysis_range == 10 ? 'selected' : ''}>최근 10회</option>
                    <option value="50" ${game.analysis_range == 50 ? 'selected' : ''}>최근 50회</option>
                    <option value="100" ${game.analysis_range == 100 ? 'selected' : ''}>최근 100회</option>
                    <option value="200" ${game.analysis_range == 200 ? 'selected' : ''}>최근 200회</option>
                    <option value="all" ${game.analysis_range == 'all' ? 'selected' : ''}>전체</option>
                </select>
            </div>
            <div class="numbers-input" id="game_numbers_div_${index}" style="display: ${['manual', 'semi_auto'].includes(game.mode) ? 'block' : 'none'};">
                <input type="text" id="game_numbers_${index}" value="${game.numbers || ''}" placeholder="1, 2, 3, 4, 5, 6 (쉼표로 구분)" ${!isActive ? 'disabled' : ''}>
            </div>
        `;
        container.appendChild(slot);

        // 이벤트 리스너 추가 (체크박스 변경 시 입력창 활성/비활성)
        const checkbox = slot.querySelector(`#game_active_${index}`);
        checkbox.addEventListener('change', function () {
            const inputs = slot.querySelectorAll('select, input[type="text"]');
            inputs.forEach(input => input.disabled = !this.checked);
            slot.style.opacity = this.checked ? '1' : '0.5';
        });

        // 초기 투명도 설정
        slot.style.opacity = isActive ? '1' : '0.5';
    });
}

function getSlotClass(mode) {
    if (['manual', 'semi_auto'].includes(mode)) return 'manual';
    if (mode === 'max_first') return 'analysis';
    return '';
}

function toggleInputs(selectElem, index) {
    const mode = selectElem.value;
    const numbersDiv = document.getElementById(`game_numbers_div_${index}`);
    const analysisDiv = document.getElementById(`game_analysis_div_${index}`);

    // Toggle Numbers Input
    if (['manual', 'semi_auto'].includes(mode)) {
        numbersDiv.style.display = 'block';
    } else {
        numbersDiv.style.display = 'none';
    }

    // Toggle Analysis Input
    if (mode === 'max_first') {
        analysisDiv.style.display = 'block';
    } else {
        analysisDiv.style.display = 'none';
    }
}

// Setup Form Submit
document.getElementById('setup-form').addEventListener('submit', function (e) {
    e.preventDefault();
    saveSetupConfig();
});


function loadConfig() {
    const loadingScreen = document.getElementById('loading-screen');
    const statusText = loadingScreen ? loadingScreen.querySelector('p') : null;

    if (statusText) statusText.textContent = "서버에 연결 중입니다...";

    // 5초 타임아웃 설정
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    fetch('/api/config', { signal: controller.signal })
        .then(response => {
            if (statusText) statusText.textContent = "데이터 수신 중...";
            return response.json();
        })
        .then(config => {
            clearTimeout(timeoutId);
            if (statusText) statusText.textContent = "화면 구성 중...";

            // Hide Loading Screen
            if (loadingScreen) loadingScreen.style.display = 'none';

            // Check if account is configured
            const userId = config.account ? config.account.user_id : '';

            if (!userId) {
                // Show Setup Wizard
                document.getElementById('setup-wizard').style.display = 'block';
                document.getElementById('main-dashboard').style.display = 'none';
            } else {
                // Show Main Dashboard
                document.getElementById('setup-wizard').style.display = 'none';
                document.getElementById('main-dashboard').style.display = 'block';

                // Populate Dashboard Fields
                populateDashboard(config);
            }
        })
        .catch(error => {
            console.error('Error loading config:', error);
            // Show error on loading screen
            if (loadingScreen) {
                let errorMsg = "서버와 통신할 수 없습니다.";
                if (error.name === 'AbortError') {
                    errorMsg = "연결 시간이 초과되었습니다. (Timeout)";
                }
                loadingScreen.innerHTML = `
                    <h2 style="color: #ff5555;">❌ 연결 실패</h2>
                    <p>${errorMsg}</p>
                    <p style="font-size: 0.8em; color: #666;">${error.message}</p>
                    <button onclick="location.reload()" class="btn btn-primary" style="margin-top: 20px;">다시 시도</button>
                `;
            }
        });
}

function populateDashboard(config) {
    // Account
    if (config.account) {
        document.getElementById('user_id').value = config.account.user_id || '';
        // Passwords are masked/empty from server, so we don't set them unless user wants to change
    }

    // Games
    if (config.games) {
        renderGameSlots(config.games);
    }

    // Deposit
    if (config.deposit) {
        document.getElementById('deposit_threshold').value = config.deposit.threshold || 5000;
        document.getElementById('deposit_amount').value = config.deposit.amount || 20000;
    }

    // Schedule
    if (config.schedule) {
        document.getElementById('deposit_day').value = config.schedule.deposit_day || 'Friday';
        document.getElementById('deposit_time').value = config.schedule.deposit_time || '18:00';
        document.getElementById('buy_day').value = config.schedule.buy_day || 'Saturday';
        document.getElementById('buy_time').value = config.schedule.buy_time || '10:00';
        document.getElementById('check_day').value = config.schedule.check_day || 'Saturday';
        document.getElementById('check_time').value = config.schedule.check_time || '23:00';
    }

    // System
    if (config.system) {
        document.getElementById('discord_webhook').value = config.system.discord_webhook || '';
    }
}

function saveSetupConfig() {
    const userId = document.getElementById('setup_user_id').value;
    const userPw = document.getElementById('setup_user_pw').value;
    const payPw = document.getElementById('setup_pay_pw').value;

    if (!userId || !userPw || !payPw) {
        alert("모든 필드를 입력해주세요.");
        return;
    }

    // Create initial config structure
    // We need to fetch current config first to preserve other defaults? 
    // Or just overwrite account section.

    fetch('/api/config')
        .then(response => response.json())
        .then(currentConfig => {
            currentConfig.account = {
                user_id: userId,
                user_pw: userPw,
                pay_pw: payPw
            };

            // Save
            fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(currentConfig)
            })
                .then(response => response.json())
                .then(data => {
                    alert("설정이 완료되었습니다! 대시보드로 이동합니다.");
                    // Reload to switch view
                    loadConfig();
                });
        });
}

function saveConfig(source) {
    // Collect Games Data
    const games = [];
    for (let i = 0; i < 5; i++) {
        const modeElem = document.getElementById(`game_mode_${i}`);
        const numbersElem = document.getElementById(`game_numbers_${i}`);
        const analysisElem = document.getElementById(`game_analysis_${i}`);
        const activeElem = document.getElementById(`game_active_${i}`);

        if (modeElem) {
            games.push({
                id: i + 1,
                active: activeElem ? activeElem.checked : true,
                mode: modeElem.value,
                numbers: numbersElem ? numbersElem.value : '',
                analysis_range: analysisElem ? analysisElem.value : 50
            });
        }
    }

    const config = {
        account: {
            user_id: document.getElementById('user_id').value,
            user_pw: document.getElementById('user_pw').value,
            pay_pw: document.getElementById('pay_pw').value
        },
        games: games,
        deposit: {
            threshold: parseInt(document.getElementById('deposit_threshold').value) || 5000,
            amount: parseInt(document.getElementById('deposit_amount').value) || 20000
        },
        schedule: {
            deposit_day: document.getElementById('deposit_day').value,
            deposit_time: document.getElementById('deposit_time').value,
            buy_day: document.getElementById('buy_day').value,
            buy_time: document.getElementById('buy_time').value,
            check_day: document.getElementById('check_day').value,
            check_time: document.getElementById('check_time').value
        },
        system: {
            discord_webhook: document.getElementById('discord_webhook').value
        }
    };

    // Time Validation (Only if saving schedule)
    if (source === 'schedule') {
        const buyTime = config.schedule.buy_time;
        const [hours, minutes] = buyTime.split(':').map(Number);
        if (hours < 6) {
            alert("구매 시간은 오전 6시부터 자정(24:00) 사이로만 설정 가능합니다.");
            return;
        }
    }

    fetch('/api/config', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(config)
    })
        .then(response => response.json())
        .then(data => {
            alert(data.message);
        })
        .catch(error => {
            console.error('Error saving config:', error);
            alert('설정 저장 중 오류가 발생했습니다.');
        });
}

function updateStatus() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            document.getElementById('balance-display').textContent = data.balance.toLocaleString() + '원';
            document.getElementById('bot-status').textContent = data.status === 'running' ? 'Running' : 'Stopped';

            const dot = document.querySelector('.status-indicator .dot');
            if (data.status === 'running') {
                dot.classList.remove('stopped');
                dot.classList.add('running');
                document.querySelector('.status-indicator').innerHTML = '<span class="dot running"></span> Bot Running';
            } else {
                dot.classList.remove('running');
                dot.classList.add('stopped');
                document.querySelector('.status-indicator').innerHTML = '<span class="dot stopped"></span> Bot Stopped';
            }

            // Update latest result text
            const resultText = document.getElementById('latest-result-text');
            if (resultText && data.latest_result) {
                resultText.textContent = data.latest_result;

                // Optional: Color coding
                if (data.latest_result.includes('당첨')) {
                    resultText.style.color = '#9ece6a'; // Green
                } else if (data.latest_result.includes('낙첨')) {
                    resultText.style.color = '#f7768e'; // Red
                } else {
                    resultText.style.color = '#fff'; // White
                }
            }
        })
        .catch(error => console.error('Error updating status:', error));
}

function updateLogs() {
    fetch('/api/logs')
        .then(response => response.json())
        .then(data => {
            const logContainer = document.querySelector('.log-viewer');
            if (logContainer && data.logs) {
                logContainer.innerHTML = data.logs.join('<br>');
                logContainer.scrollTop = logContainer.scrollHeight;
            }
        })
        .catch(error => console.error('Error updating logs:', error));
}
