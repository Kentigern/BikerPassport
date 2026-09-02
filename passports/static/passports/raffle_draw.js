(function () {
  'use strict';

  var csrfToken = document.getElementById('csrf_token').value;
  var spinUrl = document.getElementById('spin-url').value;
  var remaining = parseInt(document.getElementById('pool-count').value, 10) || 0;

  var wheelSvg = document.getElementById('wheel');
  var wheelGroup = document.getElementById('wheel-g');
  var wheelWrap = document.getElementById('wheel-wrap');
  var slotWrap = document.getElementById('slot-wrap');
  var viewWheelBtn = document.getElementById('view-wheel-btn');
  var viewSlotBtn = document.getElementById('view-slot-btn');
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
  var revealTicketNumber = document.getElementById('reveal-ticket-number');
  var remainingLabel = document.getElementById('remaining-label');

  var spinning = false;

  // --- View toggle: Wheel vs Slot Machine (remembered per browser, same
  // pattern as the intake form's List/Book view toggle) -------------------
  var currentMode = 'wheel';

  function setMode(mode) {
    currentMode = mode;
    var isSlot = mode === 'slot';
    wheelWrap.style.display = isSlot ? 'none' : 'block';
    slotWrap.style.display = isSlot ? 'flex' : 'none';
    viewWheelBtn.classList.toggle('active', !isSlot);
    viewSlotBtn.classList.toggle('active', isSlot);
    try { localStorage.setItem('bikenbrew_raffle_view', mode); } catch (e) { /* ignore */ }
  }

  viewWheelBtn.addEventListener('click', function () { setMode('wheel'); });
  viewSlotBtn.addEventListener('click', function () { setMode('slot'); });

  var savedMode = 'wheel';
  try { savedMode = localStorage.getItem('bikenbrew_raffle_view') || 'wheel'; } catch (e) { /* ignore */ }
  setMode(savedMode);

  // --- Roulette wheel — purely decorative, fixed pocket count (like a
  // real roulette wheel, which has 37/38 pockets no matter how many people
  // are playing). With potentially thousands of entrants, one slice per
  // bearer would be illegible (and meaningless — a fraction-of-a-degree
  // sliver conveys nothing) long before reaching that scale, so the
  // wheel's pockets are completely decoupled from who's actually eligible.
  // The real pick happens entirely server-side (raffle_draw_spin_view)
  // before either animation even starts; both are just the show. --------
  var POCKET_COUNT = 24;
  var POCKET_COLORS = ['#9e2a2b', '#2B2727']; // red / black, classic roulette
  var CX = 200, CY = 200, R = 190;
  var currentRotation = 0;

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
    var sweep = 360 / POCKET_COUNT;
    for (var i = 0; i < POCKET_COUNT; i++) {
      var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', wedgePath(i * sweep, (i + 1) * sweep));
      path.setAttribute('fill', POCKET_COLORS[i % POCKET_COLORS.length]);
      path.setAttribute('stroke', '#efdaa4');
      path.setAttribute('stroke-width', '1');
      wheelGroup.appendChild(path);
    }
  }

  function spinWheel(onDone) {
    // The stopping point is purely theatrical (see POCKET_COUNT above) —
    // the winner was already decided server-side, so just spin to
    // somewhere unpredictable-looking. Rotation keeps accumulating rather
    // than resetting between spins (large rotate() values are fine — no
    // practical limit — and it looks more like a wheel that keeps
    // spinning than one that silently snaps back each time).
    var extraTurns = 6 + Math.floor(Math.random() * 3);
    currentRotation += extraTurns * 360 + Math.random() * 360;
    wheelSvg.style.transform = 'rotate(' + currentRotation + 'deg)';

    wheelSvg.addEventListener('transitionend', function onEnd() {
      wheelSvg.removeEventListener('transitionend', onEnd);
      onDone();
    });
  }

  // --- Slot machine — 5 reels, each cycling 0-9, revealing the winner's
  // ticket number one digit at a time, left reel to right. -------------
  var DIGIT_CYCLES = 20; // repeated 0-9 sequences built into each reel strip
  var reelStrips = Array.prototype.slice.call(document.querySelectorAll('.reel-strip'));

  reelStrips.forEach(function (strip) {
    for (var c = 0; c < DIGIT_CYCLES; c++) {
      for (var d = 0; d <= 9; d++) {
        var digitEl = document.createElement('div');
        digitEl.className = 'digit';
        digitEl.textContent = d;
        strip.appendChild(digitEl);
      }
    }
  });

  function resetReelsInstant() {
    reelStrips.forEach(function (strip) {
      strip.style.transition = 'none';
      strip.style.transform = 'translateY(0)';
    });
    slotWrap.offsetHeight; // force reflow so the next transform re-enables transitions
  }

  function spinSlot(ticketNumber, onDone) {
    resetReelsInstant();
    var digitHeight = reelStrips[0].parentElement.getBoundingClientRect().height;
    var lastIndex = reelStrips.length - 1;

    reelStrips.forEach(function (strip, i) {
      var targetDigit = parseInt(ticketNumber[i], 10);
      var cycles = 8 + i * 2; // later reels travel further -> stop later
      var steps = cycles * 10 + targetDigit;
      var duration = 1.8 + i * 0.7; // seconds — staggered left-to-right stop

      requestAnimationFrame(function () {
        strip.style.transition = 'transform ' + duration + 's cubic-bezier(.15, .85, .35, 1)';
        strip.style.transform = 'translateY(-' + (steps * digitHeight) + 'px)';
      });

      if (i === lastIndex) {
        strip.addEventListener('transitionend', function onEnd() {
          strip.removeEventListener('transitionend', onEnd);
          onDone();
        });
      }
    });
  }

  // --- Shared draw flow --------------------------------------------------
  function refreshAvailability() {
    remainingLabel.textContent = remaining + (remaining === 1 ? ' entrant' : ' entrants');
    if (remaining <= 0) {
      stage.style.display = 'none';
      emptyState.style.display = 'block';
    } else {
      stage.style.display = 'flex';
      emptyState.style.display = 'none';
    }
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
    revealTicketNumber.textContent = 'Ticket #' + winner.ticket_number;
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

  function onDrawSettled(winner) {
    showReveal(winner);
    addToWinnersList(winner);
    remaining -= 1;
    prizeInput.value = '';
    spinning = false;
    spinBtn.disabled = false;
    refreshAvailability();
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
    if (spinning || remaining <= 0) return;
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
      if (currentMode === 'slot') {
        spinSlot(winner.ticket_number, function () { onDrawSettled(winner); });
      } else {
        spinWheel(function () { onDrawSettled(winner); });
      }
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
  refreshAvailability();
})();
