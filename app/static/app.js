/* 레시피 믹스 화면 동작. 자바스크립트가 없어도 기본 기능(등록·검색·저장)은 폼으로 동작하고,
   여기서는 화면을 다시 불러오지 않는 편의 기능만 더한다. 사용자 글은 항상 textContent 로 넣는다(XSS 방지). */
(function () {
  'use strict';
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  // ---------- 알림 ----------
  var toastTimer;
  function toast(message) {
    var t = $('#rm-toast');
    if (!t) return;
    t.textContent = message;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, 3500);
  }
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-dismiss]');
    if (btn) btn.closest('.rm-alert').remove();
    var close = e.target.closest('[data-close]');
    if (close) close.closest('dialog').close();
    var open = e.target.closest('[data-open-dialog]');
    if (open) document.getElementById(open.dataset.openDialog).showModal();
  });

  // ---------- 삭제처럼 되돌릴 수 없는 작업은 한 번 더 묻기 ----------
  $$('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (e) { if (!window.confirm(form.dataset.confirm)) e.preventDefault(); });
  });

  // ---------- 필터 선택을 바꾸면 바로 적용 ----------
  $$('form[data-autosubmit] select').forEach(function (s) { s.addEventListener('change', function () { s.form.submit(); }); });

  // ---------- 비밀번호 보기 ----------
  $$('[data-pw-toggle]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var input = document.getElementById(btn.dataset.pwToggle);
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.textContent = show ? '숨기기' : '보기';
      btn.setAttribute('aria-label', show ? '비밀번호 숨기기' : '비밀번호 보기');
      btn.setAttribute('aria-pressed', String(show));
    });
  });

  // ---------- AI 호출처럼 오래 걸리는 폼: 두 번 누르지 않게 ----------
  $$('form[data-loading-form]').forEach(function (form) {
    form.addEventListener('submit', function () {
      $$('button:not([type=button])', form.closest('.rm-workgrid') || form).forEach(function (b) {
        b.classList.add('is-loading');
        setTimeout(function () { b.disabled = true; }, 0); // 제출이 끝난 뒤 비활성화
      });
      var status = $('[data-loading-status]');
      if (status) status.textContent = 'AI가 두 레시피를 분석하고 있어요. 화면을 닫지 말고 기다려 주세요.';
    });
  });

  // ---------- [− 2인분 +] ----------
  function setStepper(el, value) {
    var min = Number(el.dataset.min), max = Number(el.dataset.max);
    value = Math.min(max, Math.max(min, value));
    el.dataset.value = value;
    $('output', el).textContent = value + '인분';
    $('[data-step="-1"]', el).disabled = value <= min;
    $('[data-step="1"]', el).disabled = value >= max;
    var hidden = $('input[type=hidden]', el);
    if (hidden) hidden.value = value;
    el.dispatchEvent(new CustomEvent('stepper:change', {detail: value, bubbles: true}));
  }
  $$('[data-stepper]').forEach(function (el) {
    $$('[data-step]', el).forEach(function (b) {
      b.addEventListener('click', function () { setStepper(el, Number(el.dataset.value) + Number(b.dataset.step)); });
    });
  });

  // ---------- 재료량 표시 (app/recipe_util.py 의 format_quantity 와 같은 규칙) ----------
  var WHOLE = ['개', '알', '마리', '모', '캔', '봉', '봉지'];
  var HALF = ['공기', '대', '장', '쪽', '송이', '줄기', '컵', '큰술', '작은술', '줌'];
  function plain(v) { v = Math.round(v * 1000) / 1000; return v === 0.5 ? '1/2' : String(v); }
  function rmQuantity(q, unit, factor) {
    if (q === '' || q === null || isNaN(q)) return '';
    q = Number(q);
    if (factor === 1) return plain(q);
    var v = Math.round(q * factor * 1000) / 1000;
    if (WHOLE.indexOf(unit) >= 0) {
      if (Number.isInteger(v)) return String(v);
      var lo = Math.max(1, Math.floor(v)), hi = Math.floor(v) + 1;
      return lo === hi ? String(hi) : lo + '~' + hi;
    }
    if (HALF.indexOf(unit) >= 0) return plain(Math.max(0.5, Math.round(v * 2) / 2));
    if (unit === 'g' || unit === 'ml') return String(Math.max(1, Math.round(v)));
    return String(Math.round(v * 10) / 10);
  }
  var detailStepper = $('#detail-servings');
  if (detailStepper) {
    var base = Number(detailStepper.dataset.value);
    detailStepper.addEventListener('stepper:change', function (e) {
      $$('#detail-ingredients [data-qty]').forEach(function (td) {
        td.textContent = rmQuantity(td.dataset.qty, td.dataset.unit, e.detail / base) + td.dataset.unit;
      });
    });
  }

  // ---------- 상세: 조리 모드 · 텍스트 복사 ----------
  var recipeData = $('#recipe-data') ? JSON.parse($('#recipe-data').textContent) : null;
  var cookIndex = 0;
  function renderCook() {
    $('#cook-title').textContent = '조리 모드 · ' + (cookIndex + 1) + ' / ' + recipeData.steps.length;
    $('#cook-step').textContent = recipeData.steps[cookIndex];
    $('#cook-prev').disabled = cookIndex === 0;
    $('#cook-next').textContent = cookIndex === recipeData.steps.length - 1 ? '조리 마치기' : '다음 단계';
  }
  if (recipeData) {
    $('[data-cook]').addEventListener('click', function () { cookIndex = 0; renderCook(); $('#cook-dialog').showModal(); });
    $('#cook-prev').addEventListener('click', function () { cookIndex--; renderCook(); });
    $('#cook-next').addEventListener('click', function () {
      if (cookIndex === recipeData.steps.length - 1) { $('#cook-dialog').close(); toast('모든 조리 단계를 확인했어요.'); }
      else { cookIndex++; renderCook(); }
    });
    $('[data-copy-recipe]').addEventListener('click', function () {
      var servings = detailStepper ? Number(detailStepper.dataset.value) : recipeData.servings;
      var lines = $$('#detail-ingredients tr').map(function (tr) { return '- ' + tr.cells[0].innerText.trim() + ' ' + tr.cells[1].innerText.trim(); });
      copyText(recipeData.title + '\n' + servings + '인분 · ' + recipeData.cook_time_min + '분\n\n재료\n' + lines.join('\n') +
        '\n\n조리 순서\n' + recipeData.steps.map(function (s, i) { return (i + 1) + '. ' + s; }).join('\n') +
        '\n\n작성자: ' + recipeData.author + ' · 레시피 믹스');
    });
  }
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { toast('클립보드에 복사했어요.'); }, function () { window.prompt('아래 내용을 복사해 주세요.', text); });
    } else {
      window.prompt('아래 내용을 복사해 주세요.', text);
    }
  }
  $$('[data-copy-text]').forEach(function (b) { b.addEventListener('click', function () { copyText(b.dataset.copyText); }); });

  // ---------- 좋아요 · 즐겨찾기: 화면을 다시 불러오지 않고 켜고 끄기 ----------
  $$('form[data-ajax-toggle]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (!window.fetch) return;
      e.preventDefault();
      var btn = $('button', form);
      btn.disabled = true;
      fetch(form.action, {method: 'POST', body: new FormData(form), headers: {'Accept': 'application/json'}, credentials: 'same-origin'})
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (data) {
          btn.setAttribute('aria-pressed', String(data.on));
          if (form.dataset.ajaxToggle === 'bookmark') {
            if (btn.classList.contains('rm-card-bookmark')) btn.textContent = data.on ? '★' : '☆';
            else btn.textContent = data.on ? '★ 즐겨찾기 해제' : '☆ 즐겨찾기';
          } else {
            $('[data-like-icon]', btn).textContent = data.on ? '♥' : '♡';
            $$('[data-like-count]').forEach(function (el) { el.textContent = data.count; });
            $$('.rm-meta-item.liked, .rm-meta-item:has([data-like-count])').forEach(function (el) { el.classList.toggle('liked', data.on); });
          }
          toast(data.message);
        })
        .catch(function () { form.submit(); }) // 실패하면 일반 제출로 다시 시도
        .finally(function () { btn.disabled = false; });
    });
  });

  // ---------- 레시피 등록·수정: 재료·단계 줄 추가/삭제/이동 ----------
  function renumberSteps() {
    $$('#step-rows [data-step-row]').forEach(function (row, i, all) {
      var label = $('[data-step-label]', row), area = $('textarea', row);
      area.id = 'step-' + (i + 1);
      label.htmlFor = area.id;
      label.textContent = '단계 ' + (i + 1);
      $('[data-move="-1"]', row).disabled = i === 0;
      $('[data-move="1"]', row).disabled = i === all.length - 1;
    });
  }
  function addFromTemplate(templateId, containerId) {
    var node = document.getElementById(templateId).content.firstElementChild.cloneNode(true);
    document.getElementById(containerId).appendChild(node);
    var first = $('input, textarea', node);
    if (first) first.focus();
    renumberSteps();
  }
  if ($('#ingredient-rows')) {
    $('[data-add-ingredient]').addEventListener('click', function () { addFromTemplate('ingredient-template', 'ingredient-rows'); });
    $('[data-add-step]').addEventListener('click', function () { addFromTemplate('step-template', 'step-rows'); });
    document.addEventListener('click', function (e) {
      var remove = e.target.closest('[data-remove-row]');
      if (remove) {
        var row = remove.closest('[data-ingredient-row], [data-step-row]');
        var siblings = row.parentNode.children.length;
        if (siblings > 1) row.remove(); else $$('input, textarea', row).forEach(function (i) { i.value = ''; });
        renumberSteps();
      }
      var move = e.target.closest('[data-move]');
      if (move) {
        var step = move.closest('[data-step-row]');
        if (move.dataset.move === '-1' && step.previousElementSibling) step.parentNode.insertBefore(step, step.previousElementSibling);
        if (move.dataset.move === '1' && step.nextElementSibling) step.parentNode.insertBefore(step.nextElementSibling, step);
        renumberSteps();
        move.focus();
      }
    });
    renumberSteps();
  }

  // ---------- AI 믹스: 원본 고르기 · 목표 예시 · 분량 요약 ----------
  $$('[data-pick]').forEach(function (b) {
    b.addEventListener('click', function () {
      var kind = b.dataset.pick;
      $('#' + kind + '-id').value = b.dataset.id;
      $('#' + kind + '-name').textContent = b.dataset.title;
      $('#' + kind + '-meta').textContent = b.dataset.meta;
      $('#summary-' + kind).textContent = b.dataset.title;
      $$('[data-pick="' + kind + '"]').forEach(function (x) { x.setAttribute('aria-current', String(x === b)); });
      b.closest('dialog').close();
    });
  });
  $$('[data-goal]').forEach(function (b) {
    b.addEventListener('click', function () {
      $('#goal').value = b.dataset.goal;
      $$('[data-goal]').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
    });
  });
  var mixStepper = $('#mix-servings');
  if (mixStepper) mixStepper.addEventListener('stepper:change', function (e) { $('#summary-servings').textContent = e.detail + '인분'; });

  // ---------- 원본과 비교: 유형 필터 · 강조 켜고 끄기 ----------
  $$('[data-change-filter]').forEach(function (b) {
    b.addEventListener('click', function () {
      var f = b.dataset.changeFilter, count = 0;
      $$('[data-change]').forEach(function (c) {
        c.hidden = !(f === 'all' || (f === 'changed' && c.dataset.change !== 'keep') || c.dataset.change === f);
        if (!c.hidden) count++;
      });
      $$('[data-change-filter]').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
      $('[data-change-count]').textContent = (f === 'all' ? '유지 항목을 포함해 ' : '') + count + '개 항목 표시';
    });
  });
  var hl = $('[data-highlight-toggle]');
  if (hl) hl.addEventListener('change', function () { $('#comparison-board').classList.toggle('rm-no-highlights', !hl.checked); });

  // ---------- 보유 재료: 칩 + 자동완성 ----------
  var input = $('#ingredient-input');
  if (input) {
    var list = $('#ingredient-suggestions'), chips = $('#ingredient-chips'), error = $('#ingredient-error');
    var options = [], active = -1, timer = null, seq = 0;
    var ALIAS = {'계란': '달걀', '에그': '달걀'};
    var norm = function (s) { s = s.replace(/\s+/g, ''); return ALIAS[s] || s; };
    var haveNames = function () { return $$('input[name=have]', chips).map(function (i) { return i.value; }); };

    function addChip(name) {
      name = name.trim().replace(/\s+/g, ' ').slice(0, 40);
      if (!name) { error.textContent = '재료 이름을 입력해 주세요.'; return false; }
      name = ALIAS[name.replace(/\s+/g, '')] || name;
      if (haveNames().some(function (h) { return norm(h) === norm(name); })) { error.textContent = '이미 추가한 재료예요.'; return false; }
      var chip = document.createElement('span');
      chip.className = 'rm-chip rm-static';
      chip.dataset.chip = '';
      var text = document.createElement('span'); text.textContent = name;
      var hidden = document.createElement('input'); hidden.type = 'hidden'; hidden.name = 'have'; hidden.value = name;
      var del = document.createElement('button'); del.type = 'button'; del.textContent = '×'; del.dataset.removeChip = '';
      del.setAttribute('aria-label', name + ' 삭제');
      chip.append(text, hidden, del);
      chips.appendChild(chip);
      error.textContent = '';
      return true;
    }
    function addTyped(value) {
      var ok = false;
      value.split(/[,、]/).forEach(function (part) { if (part.trim()) ok = addChip(part) || ok; });
      if (ok) { input.value = ''; hide(); input.focus(); }
    }
    function hide() { list.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); active = -1; }
    function mark(index) {
      active = index;
      $$('[role=option]', list).forEach(function (o, i) { o.setAttribute('aria-selected', String(i === index)); });
      if (index >= 0) { input.setAttribute('aria-activedescendant', 'suggest-' + index); var el = $('#suggest-' + index); if (el) el.scrollIntoView({block: 'nearest'}); }
    }
    function render(query, items) {
      var have = haveNames().map(norm);
      options = items.map(function (o) { return {name: o.name, alias: o.alias, disabled: have.indexOf(norm(o.name)) >= 0}; });
      if (!items.some(function (o) { return norm(o.name) === norm(query); })) options.push({name: query, custom: true, disabled: have.indexOf(norm(query)) >= 0});
      list.replaceChildren();
      options.forEach(function (o, i) {
        var li = document.createElement('li');
        li.id = 'suggest-' + i; li.setAttribute('role', 'option'); li.setAttribute('aria-selected', 'false'); li.setAttribute('aria-disabled', String(o.disabled));
        var left = document.createElement('span');
        if (o.custom) { left.textContent = '＋ “' + o.name + '” 직접 추가'; }
        else {
          var at = o.name.indexOf(query);
          if (at >= 0) { var m = document.createElement('mark'); m.textContent = query; left.append(o.name.slice(0, at), m, o.name.slice(at + query.length)); }
          else left.textContent = o.name;
          if (o.alias) { var small = document.createElement('small'); small.textContent = '다른 이름: ' + o.alias; left.appendChild(small); }
        }
        var right = document.createElement('span'); right.className = 'rm-note-right';
        right.textContent = o.disabled ? '이미 추가됨' : (o.custom ? '새 재료' : '추가');
        li.append(left, right);
        li.addEventListener('pointerdown', function (e) { e.preventDefault(); });
        li.addEventListener('click', function () { if (o.disabled) { error.textContent = '이미 추가한 재료예요.'; return; } if (addChip(o.name)) { input.value = ''; hide(); input.focus(); } });
        list.appendChild(li);
      });
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      mark(options.findIndex(function (o) { return !o.disabled; }));
    }
    function suggest() {
      var q = input.value.trim();
      if (!q || /[,、]/.test(q)) { hide(); return; }
      var my = ++seq;
      fetch(input.dataset.suggestUrl + '?q=' + encodeURIComponent(q), {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.ok ? r.json() : []; })
        .catch(function () { return []; })
        .then(function (items) { if (my === seq && input.value.trim() === q) render(q, items); });
    }
    input.addEventListener('input', function () { error.textContent = ''; clearTimeout(timer); timer = setTimeout(suggest, 150); });
    input.addEventListener('focus', suggest);
    input.addEventListener('blur', function () { setTimeout(hide, 120); });
    input.addEventListener('keydown', function (e) {
      if (e.isComposing) return; // 한글 조합 중에는 Enter·방향키를 처리하지 않는다
      if (e.key === 'Escape') { hide(); return; }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        var enabled = options.map(function (o, i) { return o.disabled ? -1 : i; }).filter(function (i) { return i >= 0; });
        if (!enabled.length || list.hidden) return;
        var cur = enabled.indexOf(active);
        mark(enabled[(cur + (e.key === 'ArrowDown' ? 1 : -1) + enabled.length) % enabled.length]);
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        var o = !list.hidden && active >= 0 ? options[active] : null;
        if (o && !o.disabled && addChip(o.name)) { input.value = ''; hide(); } else if (!o) addTyped(input.value);
      }
    });
    $('#ingredient-add').addEventListener('click', function () { addTyped(input.value); });
    chips.addEventListener('click', function (e) { var b = e.target.closest('[data-remove-chip]'); if (b) b.closest('[data-chip]').remove(); });
    $('#pantry-form').addEventListener('submit', function (e) {
      if (input.value.trim()) addTyped(input.value);
      if (!haveNames().length) { e.preventDefault(); error.textContent = '재료를 한 개 이상 추가해 주세요.'; input.focus(); return; }
      input.disabled = true; // 칩으로 옮긴 재료가 add= 로 한 번 더 전송되지 않게
    });
  }
})();
