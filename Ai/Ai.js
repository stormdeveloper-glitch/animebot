// ══ UZGPT-4 AI Chat JavaScript Controller ══

const chatMessages = document.getElementById('chatMessages');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const chatArea = document.getElementById('chatArea');

let isWaitingResponse = false;
let isAdminPasswordMode = false;

// Event Listeners
sendBtn.addEventListener('click', sendMessage);
messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        sendMessage();
    }
});

// Focus input on load
window.addEventListener('DOMContentLoaded', () => {
    messageInput.focus();
});

// Send message logic
async function sendMessage() {
    const text = messageInput.value.trim();
    if (!text || isWaitingResponse) return;

    // Add user message to UI
    const visibleMsg = isAdminPasswordMode ? '••••••' : text;
    appendMessage(visibleMsg, 'user');
    messageInput.value = '';
    messageInput.focus();

    // Show typing indicator
    showTypingIndicator();
    isWaitingResponse = true;

    try {
        const response = await fetch('/api/ai/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ message: text, admin_password_mode: isAdminPasswordMode })
        });

        const data = await response.json();
        removeTypingIndicator();

        isAdminPasswordMode = !!data.admin_password_required;
        if (isAdminPasswordMode) {
            messageInput.placeholder = "Admin parolini kiriting...";
            messageInput.type = "password";
        } else {
            messageInput.placeholder = "Xabaringizni kiriting...";
            messageInput.type = "text";
        }

        if (response.ok && data.ok) {
            appendMessage(data.reply, 'bot');
            if (data.admin_ok) {
                if (data.admin_token) {
                    localStorage.setItem('az_admin_token', data.admin_token);
                }
                setTimeout(() => {
                    window.location.href = data.admin_url || '/admin';
                }, 500);
            }
        } else {
            const errText = data.error || 'Serverga ulanib bo\'lmadi.';
            appendMessage(`⚠️ Xatolik yuz berdi: ${errText}`, 'bot');
        }
    } catch (err) {
        removeTypingIndicator();
        appendMessage('⚠️ Tarmoq xatosi. Iltimos, keyinroq qayta urinib ko\'ring.', 'bot');
    } finally {
        isWaitingResponse = false;
    }
}

// Click suggestion pill
function sendSuggestion(text) {
    if (isWaitingResponse) return;
    messageInput.value = text;
    sendMessage();
}
window.sendSuggestion = sendSuggestion;

// Append message element to window
function appendMessage(text, sender) {
    const msgRow = document.createElement('div');
    msgRow.className = `msg-row ${sender}`;

    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    if (sender === 'user') {
        avatar.textContent = '👤';
    } else {
        const img = document.createElement('img');
        img.src = '/Ai/Ai.png';
        img.alt = 'AI';
        avatar.appendChild(img);
    }
    msgRow.appendChild(avatar);

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    
    if (sender === 'bot') {
        // Parse custom anime cards
        const parsed = parseAnimeCards(text);
        bubble.innerHTML = formatMarkdown(parsed.cleanText);
        msgRow.appendChild(bubble);

        // If there are anime cards, inject them
        if (parsed.cards.length > 0) {
            const container = document.createElement('div');
            container.style.display = 'flex';
            container.style.flexDirection = 'column';
            container.style.gap = '8px';
            container.style.marginTop = '10px';
            container.style.width = '100%';

            parsed.cards.forEach(card => {
                const cardEl = document.createElement('div');
                cardEl.className = 'ai-card';
                cardEl.innerHTML = `
                    <img src="${card.cover}" onerror="this.src='./Ai/Ai.png'">
                    <div class="ai-card-info">
                        <a class="ai-card-title" href="/poster/${card.id}" target="_blank">${card.name}</a>
                        <a class="ai-card-btn" href="/poster/${card.id}" target="_blank">Batafsil</a>
                    </div>
                `;
                container.appendChild(cardEl);
            });
            bubble.appendChild(container);
        }
    } else {
        bubble.textContent = text;
        msgRow.appendChild(bubble);
    }

    chatMessages.appendChild(msgRow);
    scrollToBottom();
}

// Scroll to chat bottom
function scrollToBottom() {
    chatArea.scrollTo({
        top: chatArea.scrollHeight,
        behavior: 'smooth'
    });
}

// Show typing loader
function showTypingIndicator() {
    const indicator = document.createElement('div');
    indicator.className = 'msg-row bot';
    indicator.id = 'typingIndicator';
    indicator.innerHTML = `
        <div class="msg-avatar"><img src="/Ai/Ai.png" alt="AI"></div>
        <div class="msg-bubble">
            <div class="typing-dots">
                <span></span>
                <span></span>
                <span></span>
            </div>
        </div>
    `;
    chatMessages.appendChild(indicator);
    scrollToBottom();
}

// Remove typing loader
function removeTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) {
        indicator.remove();
    }
}

// Parse custom [ANIME_CARD:ID|Nom|RasmURL] tags
function parseAnimeCards(text) {
    const regex = /\[ANIME_CARD:([0-9]+)\|([^|]+)\|([^\]]+)\]/g;
    const cards = [];
    let cleanText = text.replace(regex, (match, id, name, cover) => {
        cards.push({ id, name, cover });
        return ''; // remove card tag from text flow
    });
    return { cleanText: cleanText.trim(), cards };
}

// Simple markdown formatter (bold/italic/breaks)
function formatMarkdown(text) {
    let formatted = text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code>$1</code>')
        .replace(/\n/g, '<br>');
    return formatted;
}
