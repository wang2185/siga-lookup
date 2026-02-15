// Juso.go.kr 주소 자동완성
(function() {
  const input = document.getElementById('addressInput');
  const list = document.getElementById('autocompleteList');
  const hiddenField = document.getElementById('jusoData');
  const selectedDisplay = document.getElementById('selectedAddress');
  let debounceTimer = null;

  if (!input) return;

  input.addEventListener('input', function() {
    clearTimeout(debounceTimer);
    const q = this.value.trim();
    if (q.length < 2) { list.classList.remove('show'); return; }
    debounceTimer = setTimeout(() => fetchAddresses(q), 300);
  });

  input.addEventListener('focus', function() {
    if (list.children.length > 0) list.classList.add('show');
  });

  document.addEventListener('click', function(e) {
    if (!input.contains(e.target) && !list.contains(e.target)) {
      list.classList.remove('show');
    }
  });

  async function fetchAddresses(keyword) {
    try {
      const resp = await fetch('/api/address/search?q=' + encodeURIComponent(keyword));
      const data = await resp.json();
      renderResults(data.items || []);
    } catch (e) {
      console.error('주소 검색 오류:', e);
    }
  }

  function renderResults(items) {
    list.innerHTML = '';
    if (items.length === 0) {
      list.classList.remove('show');
      return;
    }
    items.forEach(item => {
      const div = document.createElement('div');
      div.className = 'autocomplete-item';
      div.innerHTML = '<div class="road-addr">' + escapeHtml(item.roadAddr || '') + '</div>'
                    + '<div class="jibun-addr">' + escapeHtml(item.jibunAddr || '') + '</div>';
      div.addEventListener('click', () => selectItem(item));
      list.appendChild(div);
    });
    list.classList.add('show');
  }

  function selectItem(item) {
    input.value = item.jibunAddr || item.roadAddr || '';
    hiddenField.value = JSON.stringify(item);
    list.classList.remove('show');
    if (selectedDisplay) {
      selectedDisplay.textContent = item.roadAddr || '';
      selectedDisplay.style.display = 'block';
    }
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }
})();
