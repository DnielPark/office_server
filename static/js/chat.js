/**
 * AI Chat Widget — devnote.html 전용
 * 플로팅 채팅 버블, 셀프 컨테이닝 (의존성 없음)
 */
(function () {
  'use strict';

  /* ── 설정 ── */
  var API_URL = '/api/chat';
  var WELCOME_MSG = '안녕하세요! 👋 무엇을 도와드릴까요?\n\n"도움말"이라고 입력하시면 제가 할 수 있는 일을 알려드려요!';

  /* ── 상태 ── */
  var open = false;

  /* ── DOM ── */
  var root = document.createElement('div');
  root.id = 'ai-chat-root';

  var shadow = root.attachShadow({ mode: 'open' });

  /* ── 스타일 ── */
  shadow.innerHTML =
    /* CSS */
    '<style>' +
    ':host { all: initial; display: block; }' +
    '#chat-toggle {' +
    '  position: fixed; bottom: 28px; right: 28px; z-index: 9999;' +
    '  width: 56px; height: 56px; border-radius: 50%; border: none;' +
    '  background: linear-gradient(135deg, #2f81f7, #388bfd);' +
    '  color: #fff; font-size: 26px; cursor: pointer;' +
    '  box-shadow: 0 4px 16px rgba(47,129,247,0.4);' +
    '  transition: transform .2s, box-shadow .2s;' +
    '  display: flex; align-items: center; justify-content: center;' +
    '  line-height: 1;' +
    '}' +
    '#chat-toggle:hover {' +
    '  transform: scale(1.08); box-shadow: 0 6px 24px rgba(47,129,247,0.55);' +
    '}' +
    '#chat-toggle:active { transform: scale(0.95); }' +
    '#chat-panel {' +
    '  position: fixed; bottom: 96px; right: 28px; z-index: 9998;' +
    '  width: 360px; height: 500px; max-height: calc(100vh - 140px);' +
    '  background: #161b22; border: 1px solid #30363d; border-radius: 16px;' +
    '  display: flex; flex-direction: column;' +
    '  box-shadow: 0 12px 48px rgba(0,0,0,0.5);' +
    '  transform-origin: bottom right;' +
    '  transition: opacity .25s, transform .25s;' +
    '  overflow: hidden;' +
    '}' +
    '#chat-panel.closed {' +
    '  opacity: 0; transform: scale(0.8); pointer-events: none;' +
    '}' +
    '#chat-header {' +
    '  display: flex; align-items: center; gap: 10px;' +
    '  padding: 16px 18px; border-bottom: 1px solid #30363d;' +
    '  background: linear-gradient(135deg, #1c2333, #161b22);' +
    '  flex-shrink: 0;' +
    '}' +
    '#chat-header .avatar {' +
    '  width: 32px; height: 32px; border-radius: 50%;' +
    '  background: linear-gradient(135deg, #2f81f7, #58a6ff);' +
    '  display: flex; align-items: center; justify-content: center;' +
    '  font-size: 16px;' +
    '}' +
    '#chat-header .title {' +
    '  flex: 1; font-size: 14px; font-weight: 600; color: #e6edf3;' +
    '  font-family: "Noto Sans KR", -apple-system, sans-serif;' +
    '}' +
    '#chat-header .close-btn {' +
    '  background: none; border: none; color: #8b949e; cursor: pointer;' +
    '  font-size: 18px; padding: 4px; line-height: 1; border-radius: 4px;' +
    '  transition: color .15s;' +
    '}' +
    '#chat-header .close-btn:hover { color: #e6edf3; }' +
    '#chat-messages {' +
    '  flex: 1; overflow-y: auto; padding: 16px;' +
    '  display: flex; flex-direction: column; gap: 10px;' +
    '  scroll-behavior: smooth;' +
    '}' +
    '.msg {' +
    '  max-width: 85%; padding: 10px 14px; border-radius: 12px;' +
    '  font-size: 13px; line-height: 1.55; white-space: pre-wrap; word-wrap: break-word;' +
    '  font-family: "Noto Sans KR", -apple-system, sans-serif;' +
    '  animation: msgIn .2s ease-out;' +
    '}' +
    '@keyframes msgIn {' +
    '  from { opacity: 0; transform: translateY(8px); }' +
    '  to { opacity: 1; transform: translateY(0); }' +
    '}' +
    '.msg.bot {' +
    '  align-self: flex-start;' +
    '  background: #1c2333; border: 1px solid #30363d;' +
    '  color: #e6edf3; border-radius: 12px 12px 12px 4px;' +
    '}' +
    '.msg.user {' +
    '  align-self: flex-end;' +
    '  background: #2f81f7; color: #fff;' +
    '  border-radius: 12px 12px 4px 12px;' +
    '}' +
    '.typing {' +
    '  align-self: flex-start; display: flex; gap: 4px;' +
    '  padding: 12px 16px;' +
    '  background: #1c2333; border: 1px solid #30363d;' +
    '  border-radius: 12px 12px 12px 4px;' +
    '}' +
    '.typing span {' +
    '  width: 6px; height: 6px; border-radius: 50%;' +
    '  background: #8b949e; animation: dotBounce 1.2s infinite;' +
    '}' +
    '.typing span:nth-child(2) { animation-delay: .2s; }' +
    '.typing span:nth-child(3) { animation-delay: .4s; }' +
    '@keyframes dotBounce {' +
    '  0%,60%,100% { transform: translateY(0); }' +
    '  30% { transform: translateY(-6px); }' +
    '}' +
    '#chat-input-area {' +
    '  display: flex; gap: 8px; padding: 12px 16px;' +
    '  border-top: 1px solid #30363d; flex-shrink: 0;' +
    '}' +
    '#chat-input {' +
    '  flex: 1; padding: 9px 14px; border-radius: 8px; border: 1px solid #30363d;' +
    '  background: #0d1117; color: #e6edf3; font-size: 13px; outline: none;' +
    '  font-family: "Noto Sans KR", -apple-system, sans-serif;' +
    '  transition: border-color .15s;' +
    '}' +
    '#chat-input:focus { border-color: #2f81f7; }' +
    '#chat-input::placeholder { color: #484f58; }' +
    '#chat-send {' +
    '  width: 38px; height: 38px; border-radius: 8px; border: none;' +
    '  background: #2f81f7; color: #fff; font-size: 16px; cursor: pointer;' +
    '  display: flex; align-items: center; justify-content: center;' +
    '  transition: background .15s; flex-shrink: 0;' +
    '}' +
    '#chat-send:hover { background: #388bfd; }' +
    '#chat-send:active { background: #1f6feb; }' +
    '/* 스크롤바 */' +
    '#chat-messages::-webkit-scrollbar { width: 5px; }' +
    '#chat-messages::-webkit-scrollbar-track { background: transparent; }' +
    '#chat-messages::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }' +
    '</style>';

  /* ── HTML ── */
  var toggle = document.createElement('button');
  toggle.id = 'chat-toggle';
  toggle.setAttribute('aria-label', 'AI 채팅 열기');
  toggle.textContent = '💬';

  var panel = document.createElement('div');
  panel.id = 'chat-panel';
  panel.className = 'closed';

  panel.innerHTML =
    '<div id="chat-header">' +
    '  <div class="avatar">🤖</div>' +
    '  <div class="title">AI 도우미</div>' +
    '  <button class="close-btn" aria-label="닫기">✕</button>' +
    '</div>' +
    '<div id="chat-messages"></div>' +
    '<div id="chat-input-area">' +
    '  <input id="chat-input" type="text" placeholder="메시지를 입력하세요..." autocomplete="off">' +
    '  <button id="chat-send" aria-label="전송">➤</button>' +
    '</div>';

  shadow.appendChild(toggle);
  shadow.appendChild(panel);

  document.body.appendChild(root);

  /* ── DOM refs ── */
  var messagesEl = shadow.getElementById('chat-messages');
  var inputEl = shadow.getElementById('chat-input');
  var sendBtn = shadow.getElementById('chat-send');
  var closeBtn = panel.querySelector('.close-btn');

  /* ── 유틸 ── */
  function scrollBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function addMessage(text, role) {
    var div = document.createElement('div');
    div.className = 'msg ' + role;
    div.textContent = text;
    messagesEl.appendChild(div);
    scrollBottom();
  }

  function showTyping() {
    var div = document.createElement('div');
    div.className = 'typing';
    div.id = 'typing-indicator';
    div.innerHTML = '<span></span><span></span><span></span>';
    messagesEl.appendChild(div);
    scrollBottom();
  }

  function hideTyping() {
    var el = shadow.getElementById('typing-indicator');
    if (el) el.remove();
  }

  function toggleChat() {
    open = !open;
    panel.classList.toggle('closed', !open);
    toggle.textContent = open ? '✕' : '💬';
    if (open) {
      inputEl.focus();
    }
  }

  /* ── 초기 메시지 ── */
  var initialized = false;
  function ensureWelcome() {
    if (!initialized && messagesEl.children.length === 0) {
      addMessage(WELCOME_MSG, 'bot');
      initialized = true;
    }
  }

  /* ── API 호출 ── */
  function sendMessage() {
    var text = inputEl.value.trim();
    if (!text) return;
    inputEl.value = '';

    addMessage(text, 'user');

    showTyping();
    inputEl.disabled = true;
    sendBtn.disabled = true;

    var xhr = new XMLHttpRequest();
    xhr.open('POST', API_URL, true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onload = function () {
      hideTyping();
      inputEl.disabled = false;
      sendBtn.disabled = false;
      inputEl.focus();
      if (xhr.status === 200) {
        try {
          var data = JSON.parse(xhr.responseText);
          addMessage(data.reply || '...', 'bot');
        } catch (e) {
          addMessage('응답을 처리할 수 없습니다. 😅', 'bot');
        }
      } else {
        addMessage('서버 통신 오류가 발생했습니다. (' + xhr.status + ')', 'bot');
      }
    };
    xhr.onerror = function () {
      hideTyping();
      inputEl.disabled = false;
      sendBtn.disabled = false;
      addMessage('네트워크 오류가 발생했습니다. 😅', 'bot');
    };
    xhr.send(JSON.stringify({ message: text }));
  }

  /* ── 이벤트 ── */
  toggle.addEventListener('click', function () {
    toggleChat();
    ensureWelcome();
  });

  closeBtn.addEventListener('click', function () {
    toggleChat();
  });

  sendBtn.addEventListener('click', sendMessage);

  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      sendMessage();
    }
  });

  /* ── 외부 클릭으로 닫기 (패널 밖) ── */
  document.addEventListener('click', function (e) {
    if (!open) return;
    if (!root.contains(e.target)) {
      toggleChat();
    }
  });
})();
