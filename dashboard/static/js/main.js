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
        saveConfig();
    });

    // 구매 설정 저장
    document.querySelector('#purchase-form button[type="submit"]').addEventListener('click', function (e) {
        e.preventDefault();
        saveConfig();
    });

    // 스케줄 설정 저장
    document.querySelector('#schedule-form button[type="submit"]').addEventListener('click', function (e) {
        e.preventDefault();
        saveConfig();
    });

    // 시스템 설정 저장
    document.querySelector('#system-form button[type="submit"]').addEventListener('click', function (e) {
        e.preventDefault();
        saveConfig();
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

function loadConfig() {
    fetch('/api/config')
        .then(response => response.json())
        .then(config => {
            // Account
            if (config.account) {
                document.getElementById('user_id').value = config.account.user_id || '';
                document.getElementById('user_pw').value = config.account.user_pw || '';
                document.getElementById('pay_pw').value = config.account.pay_pw || '';
            }

            // Games
            if (config.games) {
                renderGameSlots(config.games);
            }

            // Schedule
            if (config.schedule) {
                document.getElementById('deposit_day').value = config.schedule.deposit_day || 'Friday';
                document.getElementById('deposit_time').value = config.schedule.deposit_time || '18:00';
                document.getElementById('buy_day').value = config.schedule.buy_day || 'Saturday';
                document.getElementById('buy_time').value = config.schedule.buy_time || '10:00';
            }

            // System
            if (config.system) {
                document.getElementById('discord_webhook').value = config.system.discord_webhook || '';
            }
        })
        .catch(error => console.error('Error loading config:', error));
}

function saveConfig() {
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
        schedule: {
            deposit_day: document.getElementById('deposit_day').value,
            deposit_time: document.getElementById('deposit_time').value,
            buy_day: document.getElementById('buy_day').value,
            buy_time: document.getElementById('buy_time').value
        },
        system: {
            discord_webhook: document.getElementById('discord_webhook').value
        }
    };

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
