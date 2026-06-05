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

let selectedFile = null;

// Plus button menu toggle
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

// Sending messages
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
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatText(str) {
    return escapeHtml(str).replace(/\n/g, '<br>');
}
