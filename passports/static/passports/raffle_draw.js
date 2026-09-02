(function () {
  'use strict';

  var csrfToken = document.getElementById('csrf_token').value;
  var spinUrl = document.getElementById('spin-url').value;
  var pool = JSON.parse(document.getElementById('pool-data').textContent);

  var wheelSvg = document.getElementById('wheel');
  var wheelGroup = document.getElementById('wheel-g');
  var stage = document.getElementById('stage');
  var emptyState = document.getElementById('empty-state');
  var spinBtn = document.getElementById('spin-btn');
  var prizeInput = document.getElementById('prize-input');
  var spinStatus = document.getElementById('spin-status');
  var winnersList = document.getElementById('winners-list');
  var revealOverlay = document.getElementById('reveal-overlay');
  var revealName = document.getElementById('reveal-name');
  var revealPrize = document.getElementById('reveal-prize');
  var revealTickets = document.getElementById('reveal-tickets');

  var SLICE_COLORS = ['#efdaa4', '#c9b998', '#a68a5b', '#8a6b47'];
  var CX = 200, CY = 200, R = 190;

  var currentSlices = []; // [{id, name, tickets, start, end}], angles in degrees, 0 = top, clockwise
  var spinning = false;

  function shuffled(arr) {
    var copy = arr.slice();
    for (var i = copy.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = copy[i]; copy[i] = copy[j]; copy[j] = tmp;
    }
    return copy;
  }

  function polarPoint(angleDeg, radius) {
    var rad = (angleDeg - 90) * Math.PI / 180; // shift so 0deg = top (SVG 0deg is 3 o'clock)
    return [CX + radius * Math.cos(rad), CY + radius * Math.sin(rad)];
  }

  function wedgePath(startDeg, endDeg) {
    var p1 = polarPoint(startDeg, R);
    var p2 = polarPoint(endDeg, R);
    var largeArc = (endDeg - startDeg) > 180 ? 1 : 0;
    return 'M ' + CX + ',' + CY + ' L ' + p1[0] + ',' + p1[1] + ' A ' + R + ',' + R + ' 0 ' + largeArc + ' 1 ' + p2[0] + ',' + p2[1] + ' Z';
  }

  function buildWheel() {
    wheelGroup.innerHTML = '';
    currentSlices = [];

    if (!pool.length) {
      stage.style.display = 'none';
      emptyState.style.display = 'block';
      return;
    }
    stage.style.display = 'flex';
    emptyState.style.display = 'none';

    var arranged = shuffled(pool);
    var total = arranged.reduce(function (sum, e) { return sum + e.tickets; }, 0);
    var angle = 0;
    // With a big event's worth of entrants (thousands of bearers, not just
    // tickets), per-slice name labels are unreadable no matter the size
    // threshold — the wheel is a pure colored spinner, and the winner's
    // name only ever appears on the big reveal overlay after it stops.
    // Outlining every slice also stops helping (and starts looking like a
    // solid grid of borders) once there are hundreds of them.
    var showStroke = arranged.length <= 150;

    arranged.forEach(function (entry, i) {
      var sweep = (entry.tickets / total) * 360;
      var start = angle, end = angle + sweep;

      var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', wedgePath(start, end));
      path.setAttribute('fill', SLICE_COLORS[i % SLICE_COLORS.length]);
      if (showStroke) {
        path.setAttribute('stroke', '#2B2727');
        path.setAttribute('stroke-width', '1');
      }
      wheelGroup.appendChild(path);

      currentSlices.push({ id: entry.id, name: entry.name, tickets: entry.tickets, start: start, end: end });
      angle = end;
    });

    wheelSvg.style.transition = 'none';
    wheelSvg.style.transform = 'rotate(0deg)';
    wheelSvg.offsetHeight; // force reflow so the next transform re-enables transitions
    wheelSvg.style.transition = '';
  }

  function spawnConfetti() {
    var colors = ['#efdaa4', '#c9b998', '#ffffff', '#e6a3a3', '#a3c9e6'];
    for (var i = 0; i < 70; i++) {
      var piece = document.createElement('div');
      piece.className = 'confetti-piece';
      piece.style.left = Math.random() * 100 + 'vw';
      piece.style.background = colors[Math.floor(Math.random() * colors.length)];
      piece.style.animationDuration = (2.5 + Math.random() * 1.5) + 's';
      piece.style.animationDelay = (Math.random() * 0.4) + 's';
      document.body.appendChild(piece);
      piece.addEventListener('animationend', function () {
        this.remove();
      });
    }
  }

  function showReveal(winner) {
    revealName.textContent = winner.name;
    revealPrize.textContent = winner.prize ? winner.prize : '';
    revealTickets.textContent = winner.tickets + (winner.tickets === 1 ? ' ticket' : ' tickets');
    revealOverlay.style.display = 'flex';
    spawnConfetti();
  }

  function hideReveal() {
    revealOverlay.style.display = 'none';
  }

  function addToWinnersList(winner) {
    var li = document.createElement('li');
    li.textContent = winner.name + (winner.prize ? ' — ' + winner.prize : '');
    winnersList.insertBefore(li, winnersList.firstChild);
  }

  function postSpin(prize) {
    var body = new URLSearchParams();
    body.append('prize', prize);
    return fetch(spinUrl, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    }).then(function (r) { return r.json().then(function (data) { return { status: r.status, data: data }; }); });
  }

  function doSpin() {
    if (spinning || !currentSlices.length) return;
    spinning = true;
    hideReveal();
    spinBtn.disabled = true;
    spinStatus.textContent = '';

    var prize = prizeInput.value.trim();

    postSpin(prize).then(function (result) {
      if (!result.data.ok) {
        spinning = false;
        spinBtn.disabled = false;
        var messages = [];
        Object.keys(result.data.errors || {}).forEach(function (field) {
          result.data.errors[field].forEach(function (msg) { messages.push(msg); });
        });
        spinStatus.textContent = messages.length ? messages.join(' ') : 'Could not draw a winner — please try again.';
        return;
      }

      var winner = result.data.winner;
      var slice = currentSlices.find(function (s) { return s.id === winner.id; });
      if (!slice) {
        // Shouldn't happen — the server and client pools should agree — but
        // fail safe rather than animate toward nothing.
        spinning = false;
        spinBtn.disabled = false;
        spinStatus.textContent = 'Winner drawn but not found on the wheel — please refresh.';
        return;
      }

      // Land somewhere inside the winning slice, not always dead-center.
      // The wheel is always at rotate(0deg) at the start of a spin (buildWheel
      // resets it after every draw), so no need to account for prior rotation.
      var margin = Math.min((slice.end - slice.start) * 0.15, 3);
      var targetAngle = slice.start + margin + Math.random() * Math.max(slice.end - slice.start - 2 * margin, 0.01);
      var extraTurns = 6 + Math.floor(Math.random() * 3);
      var finalRotation = extraTurns * 360 + (360 - targetAngle);

      wheelSvg.style.transform = 'rotate(' + finalRotation + 'deg)';

      wheelSvg.addEventListener('transitionend', function onEnd() {
        wheelSvg.removeEventListener('transitionend', onEnd);
        showReveal(winner);
        addToWinnersList(winner);
        pool = pool.filter(function (e) { return e.id !== winner.id; });
        prizeInput.value = '';
        spinning = false;
        spinBtn.disabled = false;
        buildWheel();
      });
    }).catch(function () {
      spinning = false;
      spinBtn.disabled = false;
      spinStatus.textContent = 'Could not reach the server — please try again.';
    });
  }

  spinBtn.addEventListener('click', doSpin);

  document.addEventListener('keydown', function (e) {
    if (document.activeElement === prizeInput) return;
    if (e.code === 'Space' || e.code === 'Enter') {
      e.preventDefault();
      doSpin();
    }
  });

  buildWheel();
})();
