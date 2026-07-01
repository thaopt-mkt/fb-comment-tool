let currentPageId = null;

// Navigation
function navigate(viewId, navItem) {
  // Update sidebar
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  if (navItem) navItem.classList.add('active');

  // Update view
  document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
  document.getElementById(`view-${viewId}`).classList.add('active');

  // Load data based on view
  if (viewId === 'dashboard') {
    loadPages();
  } else if (viewId === 'global-logs') {
    loadGlobalLogs();
  }
}

// Tabs
function switchTab(tabId, tabEl) {
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  tabEl.classList.add('active');

  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.getElementById(`tab-${tabId}`).classList.add('active');

  if (tabId === 'posts') {
    loadPagePosts(currentPageId);
  } else if (tabId === 'logs') {
    loadPageLogs(currentPageId);
  }
}

// Modal
function toggleAddPageModal() {
  const modal = document.getElementById('addPageModal');
  if (modal.classList.contains('active')) {
    modal.classList.remove('active');
  } else {
    modal.classList.add('active');
    document.getElementById('addMsg').className = 'alert hidden';
  }
}

// Format Date
function formatDate(isoString) {
  if (!isoString) return '-';
  const d = new Date(isoString);
  return d.toLocaleString('vi-VN');
}

// API Calls
async function loadPages() {
  const box = document.getElementById('pagesList');
  try {
    const res = await fetch('/api/pages');
    const data = await res.json();
    const pages = data.pages || [];
    
    if (pages.length === 0) {
      box.innerHTML = '<div class="empty-state">Chưa có Page nào được thêm.</div>';
      return;
    }
    
    let html = '';
    for (const p of pages) {
      html += `
        <div class="page-card" onclick="openPageDetails('${p.page_id}', '${p.name.replace(/'/g, "\\'")}')">
          <h3>${p.name}</h3>
          <p>ID: ${p.page_id}</p>
          <span class="owner"><i class="fa-solid fa-user"></i> ${p.owner}</span>
          <div class="actions">
            <button class="btn btn-icon btn-danger" onclick="event.stopPropagation(); delPage(${p.id})">
              <i class="fa-solid fa-trash"></i>
            </button>
          </div>
        </div>
      `;
    }
    box.innerHTML = html;
  } catch (e) {
    box.innerHTML = `<div class="empty-state">Lỗi tải danh sách: ${e}</div>`;
  }
}

async function addPage() {
  const btn = document.getElementById('savePageBtn');
  const msg = document.getElementById('addMsg');
  const owner = document.getElementById('ownerInput').value.trim();
  const token = document.getElementById('tokenInput').value.trim();
  
  msg.className = 'alert hidden';
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Đang thêm...';
  
  try {
    const res = await fetch('/api/pages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ owner: owner, token: token })
    });
    const data = await res.json();
    
    if (data.error) {
      msg.className = 'alert error';
      msg.textContent = data.error;
    } else {
      msg.className = 'alert success';
      msg.textContent = `Đã thêm Page: ${data.name}`;
      document.getElementById('ownerInput').value = '';
      document.getElementById('tokenInput').value = '';
      setTimeout(() => {
        toggleAddPageModal();
        loadPages();
      }, 1000);
    }
  } catch (e) {
    msg.className = 'alert error';
    msg.textContent = `Lỗi mạng: ${e}`;
  }
  
  btn.disabled = false;
  btn.innerHTML = 'Lưu Page';
}

async function delPage(id) {
  if (!confirm('Bạn có chắc chắn muốn xóa Page này khỏi hệ thống?')) return;
  await fetch('/api/pages/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: id })
  });
  loadPages();
}

function openPageDetails(pageId, pageName) {
  currentPageId = pageId;
  document.getElementById('detailPageName').textContent = pageName;
  document.getElementById('detailPageId').textContent = `ID: ${pageId}`;
  
  // Navigate to view without changing sidebar active item
  document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
  document.getElementById('view-page-details').classList.add('active');
  
  // Default to Posts tab
  switchTab('posts', document.querySelector('.tab:first-child'));
}

async function loadPagePosts(pageId) {
  const box = document.getElementById('postsList');
  box.innerHTML = '<div class="empty-state"><i class="fa-solid fa-spinner fa-spin"></i> Đang tải bài viết từ Facebook...</div>';
  
  try {
    const res = await fetch(`/api/pages/${pageId}/posts`);
    const data = await res.json();
    
    if (data.error) {
      box.innerHTML = `<div class="empty-state error">Lỗi: ${data.error}</div>`;
      return;
    }
    
    const posts = data.posts || [];
    if (posts.length === 0) {
      box.innerHTML = '<div class="empty-state">Page chưa có bài viết nào hoặc không thể lấy dữ liệu.</div>';
      return;
    }
    
    let html = '';
    for (const post of posts) {
      const img = post.full_picture ? `<img src="${post.full_picture}" class="post-img">` : '';
      const msg = post.message ? escapeHtml(post.message) : '<i>(Không có nội dung chữ)</i>';
      const time = formatDate(post.created_time);
      const commentsCount = post.comments?.summary?.total_count || 0;
      
      html += `
        <div class="post-card">
          ${img}
          <div class="post-content">
            <div class="post-message">${msg}</div>
            <div class="post-meta">
              <span><i class="fa-regular fa-clock"></i> ${time}</span>
              <span><i class="fa-regular fa-comment"></i> ${commentsCount}</span>
            </div>
          </div>
        </div>
      `;
    }
    box.innerHTML = html;
  } catch (e) {
    box.innerHTML = `<div class="empty-state error">Lỗi mạng: ${e}</div>`;
  }
}

async function loadPageLogs(pageId) {
  const tbody = document.getElementById('pageLogsList');
  tbody.innerHTML = '<tr><td colspan="5" class="empty-state"><i class="fa-solid fa-spinner fa-spin"></i> Đang tải lịch sử...</td></tr>';
  
  try {
    const res = await fetch(`/api/pages/${pageId}/logs`);
    const data = await res.json();
    renderLogsTable(tbody, data.logs, false);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-state error">Lỗi mạng: ${e}</td></tr>`;
  }
}

async function loadGlobalLogs() {
  const tbody = document.getElementById('globalLogsList');
  tbody.innerHTML = '<tr><td colspan="6" class="empty-state"><i class="fa-solid fa-spinner fa-spin"></i> Đang tải lịch sử toàn hệ thống...</td></tr>';
  
  try {
    const res = await fetch(`/api/logs`);
    const data = await res.json();
    renderLogsTable(tbody, data.logs, true);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state error">Lỗi mạng: ${e}</td></tr>`;
  }
}

function renderLogsTable(tbody, logs, showPageId = false) {
  if (!logs || logs.length === 0) {
    const colspan = showPageId ? 6 : 5;
    tbody.innerHTML = `<tr><td colspan="${colspan}" class="empty-state">Chưa có lịch sử AI trả lời.</td></tr>`;
    return;
  }
  
  let html = '';
  for (const log of logs) {
    const statusClass = (log.status && log.status.includes('Thành công')) ? 'status-success' : 'status-error';
    
    html += '<tr>';
    if (showPageId) {
      html += `<td><code>${escapeHtml(log.page_id || '')}</code></td>`;
    }
    html += `
      <td>${formatDate(log.replied_at)}</td>
      <td><strong>${escapeHtml(log.customer_name || 'Khách')}</strong></td>
      <td>${escapeHtml(log.comment_text || '')}</td>
      <td>${escapeHtml(log.ai_reply_text || '')}</td>
      <td><span class="status-badge ${statusClass}">${escapeHtml(log.status || '')}</span></td>
    </tr>`;
  }
  tbody.innerHTML = html;
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, function(c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

// Init
window.onload = () => {
  navigate('dashboard', document.querySelector('.nav-item.active'));
};
