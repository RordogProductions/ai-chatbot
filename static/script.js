const chatWindow = document.getElementById('chat-window');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const plusBtn = document.getElementById('plus-btn');
const plusMenu = document.getElementById('plus-menu');
const photoInput = document.getElementById('photo-input');
const fileInput = document.getElementById('file-input');
const attachmentPreview = document.getElementById('attachment-preview');
const attachmentName = document.getElementById('attachment-name');
const removeAttachment = document.getElementById('remove-attachment');
const authModal = document.getElementById('auth-modal');
const headerUser = document.getElementById('header-user');
const authUsername = document.getElementById('auth-username');
const authPassword = document.getElementById('auth-password');
const authError = document.getElementById('auth-error');
const authSubmit = document.getElementById('auth-submit');

let selectedFile = null;
let currentUser = null;
let authMode = 'signin';

// --- Auth modal ---

function showAuthModal() {
    authModal.classList.add('visible');
    authUsername.value = '';
    authPassword.value = '';
    authError.textContent = '';
    setTimeout(() => authUsername.focus(), 50);
}

function hideAuthModal() {
    authModal.classList.remove('visible');
}

function setLoggedIn(username) {
    currentUser = username;
    headerUser.innerHTML = `
        <span class="user-greeting">👤 ${escapeHtml(username)}</span>
        <button class="sign-out-btn" id="sign-out-btn">Sign Out</button>
    `;
    document.getElementById('sign-out-btn').addEventListener('click', signOut);
    hideAuthModal();
}

async function signOut() {
    await fetch('/logout', { method: 'POST' });
    currentUser = null;
    headerUser.innerHTML = '<button class="sign-in-btn" id="open-auth-btn">Sign In</button>';
    document.getElementById('open-auth-btn').addEventListener('click', showAuthModal);
}

document.getElementById('open-auth-btn').addEventListener('click', showAuthModal);
document.getElementById('modal-close').addEventListener('click', hideAuthModal);
document.getElementById('auth-guest').addEventListener('click', hideAuthModal);

authModal.addEventListener('click', (e) => {
    if (e.target === authModal) hideAuthModal();
});

document.getElementById('tab-signin').addEventListener('click', () => {
    authMode = 'signin';
    document.getElementById('tab-signin').classList.add('active');
    document.getElementById('tab-signup').classList.remove('active');
    authSubmit.textContent = 'Sign In';
    authError.textContent = '';
});

document.getElementById('tab-signup').addEventListener('click', () => {
    authMode = 'signup';
    document.getElementById('tab-signup').classList.add('active');
    document.getElementById('tab-signin').classList.remove('active');
    authSubmit.textContent = 'Create Account';
    authError.textContent = '';
});

authSubmit.addEventListener('click', async () => {
    const username = authUsername.value.trim();
    const password = authPassword.value.trim();
    authError.textContent = '';
    authSubmit.disabled = true;

    const endpoint = authMode === 'signin' ? '/login' : '/register';
    try {
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await res.json();
        if (data.error) {
            authError.textContent = data.error;
        } else {
            setLoggedIn(data.username);
            if (authMode === 'signup') {
                appendAIMessage(`Welcome, ${escapeHtml(data.username)}! Your account has been created. I'll remember our conversations from now on! 🎉`);
            } else {
                loadHistory(data.username);
            }
        }
    } catch {
        authError.textContent = 'Could not connect. Is the server running?';
    }
    authSubmit.disabled = false;
});

authUsername.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') authPassword.focus();
});
authPassword.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') authSubmit.click();
});

async function loadHistory(username) {
    try {
        const res = await fetch('/history');
        const data = await res.json();
        if (data.messages && data.messages.length > 0) {
            chatWindow.innerHTML = '';
            const sep = document.createElement('div');
            sep.className = 'history-separator';
            sep.textContent = '— Previous conversation —';
            chatWindow.appendChild(sep);
            const recent = data.messages.slice(-10);
            recent.forEach(msg => {
                if (msg.role === 'user') {
                    appendUserMessage(msg.content, null);
                } else {
                    appendAIMessage(msg.content);
                }
            });
            appendAIMessage(`Welcome back, ${escapeHtml(username)}! How can I help you today?`);
        } else {
            appendAIMessage(`Welcome back, ${escapeHtml(username)}! Great to see you again.`);
        }
    } catch {}
}

async function checkAuth() {
    try {
        const res = await fetch('/me');
        const data = await res.json();
        if (data.logged_in) {
            setLoggedIn(data.username);
        }
    } catch {}
}

checkAuth();

// --- Plus button menu ---

plusBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    plusMenu.classList.toggle('visible');
});

document.addEventListener('click', () => plusMenu.classList.remove('visible'));
plusMenu.addEventListener('click', (e) => e.stopPropagation());

document.getElementById('menu-photo').addEventListener('click', () => {
    photoInput.click();
    plusMenu.classList.remove('visible');
});

document.getElementById('menu-file').addEventListener('click', () => {
    fileInput.click();
    plusMenu.classList.remove('visible');
});

photoInput.addEventListener('change', () => handleFileSelect(photoInput));
fileInput.addEventListener('change', () => handleFileSelect(fileInput));

function handleFileSelect(input) {
    if (!input.files || !input.files[0]) return;
    selectedFile = input.files[0];
    attachmentName.textContent = selectedFile.name;
    attachmentPreview.classList.add('visible');
    input.value = '';
}

removeAttachment.addEventListener('click', () => {
    selectedFile = null;
    attachmentPreview.classList.remove('visible');
});

// --- Sending messages ---

sendBtn.addEventListener('click', sendMessage);
userInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

async function sendMessage() {
    const text = userInput.value.trim();
    if (!text && !selectedFile) return;

    const file = selectedFile;
    selectedFile = null;
    attachmentPreview.classList.remove('visible');
    userInput.value = '';

    appendUserMessage(text, file);

    sendBtn.disabled = true;
    userInput.disabled = true;

    const thinking = appendThinking();

    const formData = new FormData();
    formData.append('message', text);
    if (file) formData.append('file', file);

    try {
        const res = await fetch('/chat', { method: 'POST', body: formData });
        const data = await res.json();
        thinking.remove();

        if (data.job_id) {
            pollImageJob(data.job_id);
        } else if (data.image_url) {
            appendAIImage(data.image_url, data.reply || 'Here\'s your image!');
        } else if (data.edited_file) {
            appendAIFileEdit(data.edited_file, data.filename, data.reply);
        } else if (data.reply) {
            appendAIMessage(data.reply);
        } else {
            appendAIMessage('Error: ' + (data.error || 'Something went wrong.'));
        }
    } catch {
        thinking.remove();
        appendAIMessage('Could not reach the server. Is it running?');
    }

    sendBtn.disabled = false;
    userInput.disabled = false;
    userInput.focus();
}

// --- Message rendering ---

function appendUserMessage(text, file) {
    const div = document.createElement('div');
    div.className = 'message user-message';

    let inner = '';
    if (file && file.type.startsWith('image/')) {
        const url = URL.createObjectURL(file);
        inner += `<img src="${url}" class="msg-image" alt="uploaded image">`;
    } else if (file) {
        inner += `<div class="file-chip">📄 ${escapeHtml(file.name)}</div>`;
    }
    if (text) inner += `<p>${escapeHtml(text)}</p>`;

    div.innerHTML = `
        <div class="bubble-wrap user-wrap">
            <div class="bubble user-bubble">${inner}</div>
            <div class="avatar user-avatar">👤</div>
        </div>`;
    chatWindow.appendChild(div);
    scrollBottom();
}

function appendAIMessage(text) {
    const div = document.createElement('div');
    div.className = 'message ai-message';
    div.innerHTML = `
        <div class="bubble-wrap ai-wrap">
            <div class="avatar ai-avatar">🤖</div>
            <div class="bubble ai-bubble"><p>${formatText(text)}</p></div>
        </div>`;
    chatWindow.appendChild(div);
    scrollBottom();
}

function appendAIFileEdit(content, filename, caption) {
    const div = document.createElement('div');
    div.className = 'message ai-message';
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    div.innerHTML = `
        <div class="bubble-wrap ai-wrap">
            <div class="avatar ai-avatar">🤖</div>
            <div class="bubble ai-bubble">
                <p>${escapeHtml(caption || 'Here\'s your edited file!')}</p>
                <a href="${url}" download="${escapeHtml(filename || 'edited_file.txt')}" class="download-btn">⬇️ Download ${escapeHtml(filename || 'edited file')}</a>
            </div>
        </div>`;
    chatWindow.appendChild(div);
    scrollBottom();
}

async function pollImageJob(jobId) {
    const statusDiv = appendGeneratingMessage();
    for (let i = 0; i < 60; i++) {
        await new Promise(r => setTimeout(r, 2000));
        try {
            const res = await fetch(`/image-status/${jobId}`);
            const data = await res.json();
            if (data.status === 'done') {
                statusDiv.remove();
                appendAIImage(data.data, 'Here\'s your image!');
                return;
            } else if (data.status === 'error') {
                statusDiv.remove();
                appendAIMessage('Error: ' + data.message);
                return;
            }
        } catch {}
    }
    statusDiv.remove();
    appendAIMessage('Image generation timed out. Please try again.');
}

function appendGeneratingMessage() {
    const div = document.createElement('div');
    div.className = 'message ai-message';
    div.innerHTML = `
        <div class="bubble-wrap ai-wrap">
            <div class="avatar ai-avatar">🤖</div>
            <div class="bubble ai-bubble"><p>🎨 Generating image, please wait...</p></div>
        </div>`;
    chatWindow.appendChild(div);
    scrollBottom();
    return div;
}

function appendAIImage(imageUrl, caption) {
    const div = document.createElement('div');
    div.className = 'message ai-message';

    const bubble = document.createElement('div');
    bubble.className = 'bubble ai-bubble';

    const status = document.createElement('p');
    status.textContent = '🎨 Generating image, please wait...';
    bubble.appendChild(status);

    const img = document.createElement('img');
    img.className = 'msg-image generated-image';
    img.alt = 'generated image';
    img.style.display = 'none';
    img.onload = () => {
        status.textContent = caption;
        img.style.display = 'block';
        scrollBottom();
    };
    img.onerror = () => {
        status.textContent = '❌ Could not generate image. Please try again.';
    };
    img.src = imageUrl;
    bubble.appendChild(img);

    const wrap = document.createElement('div');
    wrap.className = 'bubble-wrap ai-wrap';
    const avatar = document.createElement('div');
    avatar.className = 'avatar ai-avatar';
    avatar.textContent = '🤖';
    wrap.appendChild(avatar);
    wrap.appendChild(bubble);
    div.appendChild(wrap);

    chatWindow.appendChild(div);
    scrollBottom();
}

function appendThinking() {
    const div = document.createElement('div');
    div.className = 'message ai-message thinking';
    div.innerHTML = `
        <div class="bubble-wrap ai-wrap">
            <div class="avatar ai-avatar">🤖</div>
            <div class="bubble ai-bubble"><p>Thinking...</p></div>
        </div>`;
    chatWindow.appendChild(div);
    scrollBottom();
    return div;
}

function scrollBottom() {
    chatWindow.scrollTop = chatWindow.scrollHeight;
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatText(str) {
    return escapeHtml(str).replace(/\n/g, '<br>');
}
