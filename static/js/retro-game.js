/**
 * retro-game.js — 무한 러너 (구글 공룡 게임 스타일)
 * <div id="retro-game"></div> + <script src="/static/js/retro-game.js"></script>
 * 전역 오염 없음, 모듈 패턴.
 */
const RetroGame = (function() {
  'use strict';

  /* ── 상수 ── */
  var H = 140;                       // 캔버스 높이 고정
  var GRAVITY    = 0.55;
  var JUMP_VEL   = -8.5;
  var BASE_SPEED = 3;
  var SPEED_INCR = 0.004;            // 점수당 속도 증가
  var MIN_OBS_H  = 18;
  var MAX_OBS_H  = 36;
  var OBS_W      = 14;
  var GAP_MIN    = 0.35;             // screen width fraction
  var GAP_MAX    = 0.65;
  var COIN_R     = 5;                // 동전 반지름
  var COIN_SCORE = 10;              // 동전당 점수
  var COIN_Y_BOT = 8;               // 동전 최저 높이 (GROUND_Y 기준, 아래)
  var COIN_Y_TOP = 65;              // 동전 최고 높이 (더블점프 피크)

  /* ── 상태 ── */
  var canvas, ctx, W;
  var GROUND_Y, BOT_W = 16, BOT_H = 24;
  var state = 'idle';                // idle | running | gameover
  var score = 0, highScore = 0;
  var speed = BASE_SPEED;
  var frame = 0;
  var bot = {};
  var obstacles = [];
  var obstacleTimer = 0;
  var coins = [];
  var coinTimer = 0;
  var coinCount = 0;
  var animId = null;
  var containerEl = null;

  /* ── 초기화 ── */
  function init(container) {
    containerEl = container;
    canvas = document.createElement('canvas');
    container.appendChild(canvas);
    ctx = canvas.getContext('2d');
    resize();
    bot.x = 60;
    resetBotState();
    loadHighScore();
    bindEvents();
    loop();
  }

  function resize() {
    W = canvas.width = containerEl.clientWidth || 600;
    canvas.height = H;
    GROUND_Y = H - 28;
  }

  function resetBotState() {
    bot.y = GROUND_Y;
    bot.vy = 0;
    bot.grounded = true;
    bot.ducking = false;
    bot.canDouble = false;
  }

  function resetGame() {
    state = 'idle';
    score = 0;
    speed = BASE_SPEED;
    frame = 0;
    obstacles = [];
    obstacleTimer = 0;
    coins = [];
    coinTimer = 0;
    coinCount = 0;
    resetBotState();
  }

  function loadHighScore() {
    try {
      var v = localStorage.getItem('retro_game_high');
      highScore = v ? parseInt(v, 10) : 0;
    } catch (_) { highScore = 0; }
  }

  function saveHighScore() {
    try { localStorage.setItem('retro_game_high', highScore); } catch (_) {}
  }

  /* ── 이벤트 ── */
  function bindEvents() {
    document.addEventListener('keydown', function(e) {
      var spc = e.key === ' ' || e.key === 'Spacebar' || e.code === 'Space';
      var up  = e.key === 'ArrowUp'    || e.code === 'ArrowUp';
      var dn  = e.key === 'ArrowDown'  || e.code === 'ArrowDown';

      // 게임 컨테이너가 보일 때만 스크롤 방지
      if (spc || up || dn) {
        var el = document.getElementById('retro-game');
        if (el && el.offsetParent !== null) e.preventDefault();
      }

      if (state === 'idle' && (spc || up)) {
        startGame();
        return;
      }
      if (state === 'gameover' && (spc || up)) {
        resetGame();
        startGame();
        return;
      }
      if (state === 'running') {
        if ((spc || up) && (bot.grounded || bot.canDouble)) {
          doJump();
        }
        if (dn) bot.ducking = true;
      }
    });

    document.addEventListener('keyup', function(e) {
      if (e.key === 'ArrowDown' || e.code === 'ArrowDown') bot.ducking = false;
    });

    window.addEventListener('resize', resize);
  }

  function startGame() {
    state = 'running';
    resetBotState();
    doJump();  // 첫 Space로 시작 + 점프 동시에
  }

  function doJump() {
    bot.vy = JUMP_VEL;
    bot.grounded = false;
    bot.canDouble = !bot.canDouble;  // 첫 점프→true(더블기회), 더블→false
  }

  /* ── 업데이트 ── */
  function update() {
    if (state !== 'running') return;
    frame++;

    // 점수 & 속도
    if (frame % 3 === 0) {
      score++;
      speed = BASE_SPEED + score * SPEED_INCR;
    }

    // 수직 물리
    if (!bot.grounded) {
      bot.vy += GRAVITY;
      bot.y += bot.vy;
      if (bot.y >= GROUND_Y) {
        bot.y = GROUND_Y;
        bot.vy = 0;
        bot.grounded = true;
        bot.canDouble = false;
      }
    }

    // 장애물 생성
    obstacleTimer--;
    if (obstacleTimer <= 0) {
      spawnObstacle();
      var gap = W * (GAP_MIN + Math.random() * (GAP_MAX - GAP_MIN));
      obstacleTimer = Math.max(30, Math.floor(gap / speed));
    }

    // 장애물 이동 (좌우로 흔들리는 장애물 포함)
    for (var i = obstacles.length - 1; i >= 0; i--) {
      var o = obstacles[i];
      o.x -= speed;
      if (o.oscAmp > 0) {
        o.y = o.baseY + Math.sin(frame * 0.045 + o.oscPhase) * o.oscAmp;
      }
      if (o.x + OBS_W < 0) {
        obstacles.splice(i, 1);
      }
    }

    // 동전 생성
    coinTimer--;
    if (coinTimer <= 0) {
      spawnCoin();
      coinTimer = 18 + Math.floor(Math.random() * 35);
    }

    // 동전 이동
    for (var ci = coins.length - 1; ci >= 0; ci--) {
      coins[ci].x -= speed;
      if (coins[ci].x + COIN_R * 2 < 0) {
        coins.splice(ci, 1);
      }
    }

    // 충돌 검사 (bot.y 기준)
    var bw = bot.ducking ? BOT_W + 6 : BOT_W;
    var bh = bot.ducking ? BOT_H * 0.45 : BOT_H;
    var bx = bot.x;
    var by = bot.y - bh;             // 봇 상단 (bot.y 기준)
    var bBottom = bot.y;             // 봇 하단 = 발 위치

    for (var j = 0; j < obstacles.length; j++) {
      var o = obstacles[j];
      // AABB — 수평 겹침
      if (bx + bw > o.x && bx < o.x + OBS_W) {
        // 수직 겹침: 봇 하단 > 장애물 상단 && 봇 상단 < 장애물 하단
        if (bBottom > o.y && by < o.y + o.h) {
          gameOver();
          return;
        }
      }
    }

    // 동전 수집
    var collectR = COIN_R + 4;  // 여유 있는 수집 범위
    for (var ci = coins.length - 1; ci >= 0; ci--) {
      var c = coins[ci];
      var dx = (bot.x + BOT_W / 2) - c.x;
      var dy = (bot.y - BOT_H / 2) - c.y;
      if (Math.abs(dx) < collectR + BOT_W / 2 && Math.abs(dy) < collectR + BOT_H / 2) {
        score += COIN_SCORE;
        coinCount++;
        coins.splice(ci, 1);
      }
    }
  }

  function spawnObstacle() {
    var h = MIN_OBS_H + Math.random() * (MAX_OBS_H - MIN_OBS_H);
    var isMoving = Math.random() < 0.45;
    obstacles.push({
      x: W,
      baseY: GROUND_Y - h,
      y: GROUND_Y - h,
      h: h,
      oscAmp: isMoving ? 8 + Math.random() * 12 : 0,
      oscPhase: Math.random() * Math.PI * 2
    });
  }

  function spawnCoin() {
    var count = Math.random() < 0.35 ? 2 + Math.floor(Math.random() * 2) : 1;
    for (var i = 0; i < count; i++) {
      var cy = GROUND_Y - (COIN_Y_BOT + Math.random() * (COIN_Y_TOP - COIN_Y_BOT));
      coins.push({
        x: W + 10 + i * 22,
        y: cy
      });
    }
  }

  function gameOver() {
    state = 'gameover';
    if (score > highScore) {
      highScore = score;
      saveHighScore();
    }
  }

  /* ── 렌더링 ── */
  function draw() {
    ctx.clearRect(0, 0, W, H);

    // 바닥
    ctx.strokeStyle = '#21262d';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, GROUND_Y);
    ctx.lineTo(W, GROUND_Y);
    ctx.stroke();

    // 바닥 도트 (주행감)
    ctx.fillStyle = '#161b22';
    for (var i = 0; i < W; i += 18) {
      var ox = (i + frame * speed * 0.6) % (W + 30) - 15;
      ctx.fillRect(ox, GROUND_Y + 5, 2, 2);
      ctx.fillRect(ox + 9, GROUND_Y + 13, 2, 2);
    }

    // 동전
    var pulse = Math.sin(frame * 0.08) * 0.25 + 0.75;
    for (var ci = 0; ci < coins.length; ci++) {
      var c = coins[ci];
      // 외부 광택
      ctx.beginPath();
      ctx.arc(c.x, c.y, COIN_R + 2, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,215,0,0.12)';
      ctx.fill();
      // 동전 본체
      ctx.beginPath();
      ctx.arc(c.x, c.y, COIN_R, 0, Math.PI * 2);
      var glow = Math.floor(200 + 55 * pulse);
      ctx.fillStyle = 'rgb(255,' + glow + ',0)';
      ctx.fill();
      // 내부 하이라이트
      ctx.beginPath();
      ctx.arc(c.x - 1, c.y - 1, COIN_R * 0.45, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,255,200,0.5)';
      ctx.fill();
    }

    // 장애물
    for (var j = 0; j < obstacles.length; j++) {
      var o = obstacles[j];
      var moving = o.oscAmp > 0;
      ctx.fillStyle = moving ? '#d29922' : '#2f81f7';
      ctx.fillRect(o.x, o.y, OBS_W, o.h);
      // 하이라이트
      ctx.fillStyle = moving ? 'rgba(210,153,34,0.25)' : 'rgba(47,129,247,0.25)';
      ctx.fillRect(o.x + 2, o.y + 3, OBS_W - 4, Math.max(2, o.h * 0.12));
      if (moving) {
        // 움직이는 장애물 표시 (화살표)
        var arrowY = o.y + o.h * 0.2;
        ctx.fillStyle = 'rgba(210,153,34,0.5)';
        ctx.fillRect(o.x + 4, arrowY, OBS_W - 8, 2);
        ctx.fillRect(o.x + 4, arrowY + 4, OBS_W - 8, 2);
      }
    }

    // 봇
    drawBot();

    // 점수
    if (state === 'running' || state === 'gameover') {
      ctx.fillStyle = '#8b949e';
      ctx.font = '11px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      ctx.fillText('SCORE ' + score, W - 12, 18);
      // 동전 아이콘 + 점수
      ctx.fillStyle = '#ffd700';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText('🪙', 10, 17);
      ctx.fillStyle = '#ffd700';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.fillText('x' + coinCount, 24, 17);
    }

    // 상태 오버레이
    if (state === 'idle') {
      ctx.fillStyle = 'rgba(47,129,247,0.85)';
      ctx.font = '15px "Noto Sans KR", sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('▶  SPACE to start', W / 2, H / 2 + 4);
      ctx.fillStyle = '#8b949e';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.fillText('Space / ↑  jump  ·  ↓  duck', W / 2, H / 2 + 26);
    }

    if (state === 'gameover') {
      ctx.fillStyle = '#f85149';
      ctx.font = 'bold 18px "Noto Sans KR", sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('GAME OVER', W / 2, H / 2 - 10);

      ctx.fillStyle = '#8b949e';
      ctx.font = '12px "Noto Sans KR", sans-serif';
      ctx.fillText('SPACE to restart', W / 2, H / 2 + 16);

      if (highScore > 0) {
        ctx.fillStyle = '#3fb950';
        ctx.font = '10px "IBM Plex Mono", monospace';
        ctx.fillText('BEST ' + highScore, W / 2, H / 2 + 38);
      }
    }
  }

  function drawBot() {
    var x = bot.x, y = bot.y, c = '#2f81f7';
    var running = state === 'running';

    if (bot.ducking) {
      // 덕킹: 낮고 넓게
      ctx.fillStyle = c;
      ctx.fillRect(x, y - 10, BOT_W + 6, 10);
      ctx.fillStyle = 'rgba(47,129,247,0.5)';
      ctx.fillRect(x + 4, y - 8, 3, 3);
      ctx.fillRect(x + BOT_W - 1, y - 8, 3, 3);
      return;
    }

    // 안테나
    ctx.fillStyle = 'rgba(47,129,247,0.6)';
    ctx.fillRect(x + 7, y - 28, 2, 4);

    // 머리
    ctx.fillStyle = c;
    ctx.fillRect(x, y - 24, BOT_W, 8);

    // 눈
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(x + 3, y - 22, 3, 3);
    ctx.fillRect(x + 10, y - 22, 3, 3);
    // 눈 광택
    ctx.fillStyle = 'rgba(47,129,247,0.7)';
    ctx.fillRect(x + 3, y - 22, 3, 1);
    ctx.fillRect(x + 10, y - 22, 3, 1);

    // 몸통
    ctx.fillStyle = c;
    ctx.fillRect(x + 3, y - 16, BOT_W - 6, 8);

    // 다리 (running 시 교차 애니메이션)
    var legPhase = running && (Math.floor(frame / 5) % 2 === 0);
    var leftLegY  = legPhase ? y - 9 : y - 6;
    var rightLegY = legPhase ? y - 6 : y - 9;
    ctx.fillRect(x + 2, leftLegY, 5, 6);
    ctx.fillRect(x + BOT_W - 7, rightLegY, 5, 6);

    // 발
    ctx.fillStyle = 'rgba(47,129,247,0.5)';
    ctx.fillRect(x + 1, y - 2, 6, 2);
    ctx.fillRect(x + BOT_W - 7, y - 2, 6, 2);
  }

  /* ── 루프 ── */
  function loop() {
    update();
    draw();
    animId = requestAnimationFrame(loop);
  }

  /* ── 자동 초기화 ── */
  document.addEventListener('DOMContentLoaded', function() {
    var el = document.getElementById('retro-game');
    if (!el) return;
    init(el);
  });

  return { init: init };
})();
