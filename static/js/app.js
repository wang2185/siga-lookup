// 메인 앱 JS
(function() {
  // 부동산 유형 선택
  document.querySelectorAll('.type-card').forEach(card => {
    card.addEventListener('click', function() {
      const radio = this.querySelector('input[type="radio"]');
      const wasSelected = this.classList.contains('selected');

      // 이미 선택된 카드를 다시 클릭하면 선택 해제
      if (wasSelected) {
        this.classList.remove('selected');
        if (radio) radio.checked = false;
        const extraFields = document.getElementById('extraFields');
        const etaxFields = document.getElementById('etaxFields');
        if (extraFields) extraFields.className = 'extra-fields show';
        if (etaxFields) etaxFields.className = 'extra-fields';
        return;
      }

      document.querySelectorAll('.type-card').forEach(c => c.classList.remove('selected'));
      this.classList.add('selected');
      if (radio) radio.checked = true;

      // 건물류일 때 동/호 필드 표시
      const extraFields = document.getElementById('extraFields');
      const etaxFields = document.getElementById('etaxFields');
      const type = radio ? radio.value : '';
      const needsDongHo = ['building', 'factory', 'commercial', 'apartment'].includes(type);
      const needsEtax = type === 'building';

      if (extraFields) extraFields.className = needsDongHo ? 'extra-fields show' : 'extra-fields';
      if (etaxFields) etaxFields.className = needsEtax ? 'extra-fields show' : 'extra-fields';
    });
  });

  // 폼 제출 로딩 상태
  const form = document.getElementById('searchForm');
  if (form) {
    form.addEventListener('submit', function() {
      const btn = this.querySelector('button[type="submit"]');
      if (btn) {
        btn.disabled = true;
        btn.classList.add('loading');
      }
    });
  }
})();
