// 密码验证模块

const PASSWORD = '2632643526';

function checkPassword() {
  const input = document.getElementById('password-input');
  const error = document.getElementById('password-error');
  
  if (input.value === PASSWORD) {
    document.getElementById('password-screen').style.display = 'none';
    document.getElementById('main-app').style.display = '';
    document.getElementById('chat-mode').style.display = '';
    document.getElementById('input-area').style.display = '';
    localStorage.setItem('osint_auth', '1');
    loadHistory();
  } else {
    error.textContent = '密码错误';
    input.value = '';
  }
}

// 检查是否已登录
function checkAuth() {
  if (localStorage.getItem('osint_auth') === '1') {
    document.getElementById('password-screen').style.display = 'none';
    document.getElementById('main-app').style.display = '';
    document.getElementById('chat-mode').style.display = '';
    document.getElementById('input-area').style.display = '';
    loadHistory();
  }
}
