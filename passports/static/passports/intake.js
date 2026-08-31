(function () {
  'use strict';

  var csrfToken = document.getElementById('csrf_token').value;
  var bearerIdField = document.getElementById('bearer_id');
  var submissionIdField = document.getElementById('submission_id');

  function postForm(url, data) {
    var body = new URLSearchParams();
    Object.keys(data).forEach(function (key) {
      var value = data[key];
      if (Array.isArray(value)) {
        value.forEach(function (v) { body.append(key, v); });
      } else {
        body.append(key, value);
      }
    });
    return fetch(url, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    }).then(function (r) { return r.json().then(function (data) { return { status: r.status, data: data }; }); });
  }

  // --- Venue filter (list view only) -----------------------------------
  var venueList = document.getElementById('venue-list');
  var filterInput = document.getElementById('venue-filter');
  var filterLabel = document.getElementById('venue-filter-label');
  var venueRows = Array.prototype.slice.call(document.querySelectorAll('.venue-row'));

  function applyFilter() {
    var q = filterInput.value.trim().toLowerCase();
    venueRows.forEach(function (row) {
      row.style.display = row.dataset.search.indexOf(q) === -1 ? 'none' : '';
    });
  }

  filterInput.addEventListener('keyup', applyFilter);

  // --- View toggle: List vs Book (Book echoes the physical passport's page layout) ---
  var listBtn = document.getElementById('view-list-btn');
  var bookBtn = document.getElementById('view-book-btn');
  var pagination = document.getElementById('book-pagination');
  var prevBtn = document.getElementById('book-prev-btn');
  var nextBtn = document.getElementById('book-next-btn');
  var pageIndicator = document.getElementById('book-page-indicator');

  var VENUES_PER_PAGE = 12;
  var totalPages = Math.max(1, Math.ceil(venueRows.length / VENUES_PER_PAGE));
  var currentPage = 0;

  function renderBookPage() {
    var start = currentPage * VENUES_PER_PAGE;
    var end = start + VENUES_PER_PAGE;
    venueRows.forEach(function (row, i) {
      row.classList.toggle('book-visible', i >= start && i < end);
    });
    pageIndicator.textContent = 'Page ' + (currentPage + 1) + ' of ' + totalPages;
    prevBtn.disabled = currentPage === 0;
    nextBtn.disabled = currentPage === totalPages - 1;
  }

  prevBtn.addEventListener('click', function () {
    if (currentPage > 0) { currentPage--; renderBookPage(); }
  });
  nextBtn.addEventListener('click', function () {
    if (currentPage < totalPages - 1) { currentPage++; renderBookPage(); }
  });

  function setView(view) {
    var isBook = view === 'book';
    venueList.classList.toggle('book-mode', isBook);
    pagination.style.display = isBook ? 'flex' : 'none';
    filterInput.style.display = isBook ? 'none' : '';
    filterLabel.style.display = isBook ? 'none' : '';
    listBtn.classList.toggle('active', !isBook);
    bookBtn.classList.toggle('active', isBook);
    if (isBook) {
      // Clear any inline display:none left by the list-view filter — it
      // has higher CSS specificity than the book-mode class rules below
      // and would otherwise keep filtered-out rows hidden on every page.
      venueRows.forEach(function (row) { row.style.display = ''; });
      renderBookPage();
    } else {
      applyFilter();
    }
    try { localStorage.setItem('bikenbrew_venue_view', view); } catch (e) { /* ignore */ }
  }

  listBtn.addEventListener('click', function () { setView('list'); });
  bookBtn.addEventListener('click', function () { setView('book'); });

  var savedView = 'list';
  try { savedView = localStorage.getItem('bikenbrew_venue_view') || 'list'; } catch (e) { /* ignore */ }
  setView(savedView);

  // --- Live stamp count / raffle tickets ------------------------------
  var stampCountEl = document.getElementById('stamp-count');
  var raffleTicketsEl = document.getElementById('raffle-tickets');
  var MAX_RAFFLE_TICKETS = 28;

  function updateStampSummary() {
    var checked = venueList.querySelectorAll('input[type=checkbox]:checked').length;
    stampCountEl.textContent = checked;
    raffleTicketsEl.textContent = Math.min(Math.floor(checked / 10), MAX_RAFFLE_TICKETS);
  }

  venueList.addEventListener('change', updateStampSummary);
  updateStampSummary();

  // --- Bearer search-and-match -----------------------------------------
  var searchInput = document.getElementById('bearer-search');
  var resultsBox = document.getElementById('bearer-search-results');
  var matchNote = document.getElementById('bearer-match-note');
  var phoneChallengeBox = document.getElementById('bearer-phone-challenge');
  var phoneChallengeInput = document.getElementById('bearer-phone-challenge-input');
  var phoneChallengeBtn = document.getElementById('bearer-phone-challenge-btn');
  var phoneChallengeStatus = document.getElementById('bearer-phone-challenge-status');
  var bearerFields = {
    name: document.getElementById('id_name'),
    email: document.getElementById('id_email'),
    phone: document.getElementById('id_phone'),
    mailing_address: document.getElementById('id_mailing_address'),
  };

  var searchTimer = null;

  searchInput.addEventListener('input', function () {
    clearTimeout(searchTimer);
    var q = searchInput.value.trim();
    phoneChallengeBox.style.display = 'none';
    if (!q) {
      resultsBox.style.display = 'none';
      resultsBox.innerHTML = '';
      return;
    }
    searchTimer = setTimeout(function () {
      fetch('/passports/bearers/search/?q=' + encodeURIComponent(q))
        .then(function (r) { return r.json(); })
        .then(function (data) { renderResults(data.results); });
    }, 250);
  });

  function renderResults(results) {
    resultsBox.innerHTML = '';
    if (!results.length) {
      resultsBox.style.display = 'none';
      phoneChallengeBox.style.display = 'none';
      return;
    }

    var anyNeedsPhone = results.some(function (b) { return b.needs_phone; });

    results.forEach(function (bearer) {
      var row = document.createElement('div');
      if (bearer.needs_phone) {
        row.textContent = bearer.name + ' — enter their phone number below to access this record';
      } else {
        var detail = [bearer.phone, bearer.email].filter(Boolean).join(' · ');
        var text = bearer.name + (detail ? ' (' + detail + ')' : '');
        if (bearer.submission_id) {
          text += ' — already has a submission this season';
        }
        row.textContent = text;
        row.addEventListener('click', function () { pickBearer(bearer); });
      }
      resultsBox.appendChild(row);
    });
    resultsBox.style.display = 'block';

    phoneChallengeStatus.textContent = '';
    phoneChallengeBox.style.display = anyNeedsPhone ? 'block' : 'none';
  }

  phoneChallengeBtn.addEventListener('click', function () {
    var phone = phoneChallengeInput.value.trim();
    if (!phone) return;
    fetch('/passports/bearers/search/?q=' + encodeURIComponent(phone))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var match = data.results.find(function (b) { return !b.needs_phone; });
        if (match) {
          pickBearer(match);
          phoneChallengeBox.style.display = 'none';
          phoneChallengeInput.value = '';
        } else {
          phoneChallengeStatus.className = 'status-error';
          phoneChallengeStatus.textContent = 'No bearer matches that phone number.';
        }
      });
  });

  function pickBearer(bearer) {
    if (bearer.submission_id) {
      window.location = '/passports/submissions/' + bearer.submission_id + '/edit/';
      return;
    }
    bearerFields.name.value = bearer.name;
    bearerFields.email.value = bearer.email;
    bearerFields.phone.value = bearer.phone;
    bearerFields.mailing_address.value = bearer.mailing_address;
    bearerIdField.value = bearer.id;
    matchNote.textContent = 'Matched existing bearer — saving will update their record.';
    matchNote.style.display = 'block';
    resultsBox.style.display = 'none';
    searchInput.value = '';
  }

  Object.keys(bearerFields).forEach(function (key) {
    bearerFields[key].addEventListener('input', function () {
      if (bearerIdField.value) {
        bearerIdField.value = '';
        matchNote.textContent = 'Details edited — this will be saved as a new bearer.';
        matchNote.style.display = 'block';
      }
    });
  });

  // --- Save bearer --------------------------------------------------
  var bearerSaveBtn = document.getElementById('bearer-save-btn');
  var bearerSaveStatus = document.getElementById('bearer-save-status');
  var venueSaveButtons = document.querySelectorAll('.venue-save-btn');
  var venueSaveStatuses = document.querySelectorAll('.venue-save-status');

  bearerSaveBtn.addEventListener('click', function () {
    postForm('/passports/bearers/save/', {
      bearer_id: bearerIdField.value,
      name: bearerFields.name.value,
      email: bearerFields.email.value,
      phone: bearerFields.phone.value,
      mailing_address: bearerFields.mailing_address.value,
    }).then(function (result) {
      if (result.data.ok) {
        bearerIdField.value = result.data.bearer.id;
        bearerSaveStatus.className = 'status-ok';
        bearerSaveStatus.textContent = 'Bearer saved.';
        venueSaveButtons.forEach(function (btn) { btn.disabled = false; });
      } else {
        var messages = [];
        Object.keys(result.data.errors || {}).forEach(function (field) {
          result.data.errors[field].forEach(function (msg) { messages.push(msg); });
        });
        bearerSaveStatus.className = 'status-error';
        bearerSaveStatus.textContent = messages.length ? messages.join(' ') : 'Could not save bearer — check the fields above.';
      }
    });
  });

  // --- Save venues (+ notes / date received) -------------------------
  var intakeReadout = document.getElementById('intake-readout');
  var dateReceivedField = document.getElementById('id_date_received');
  var notesField = document.getElementById('id_notes');

  function saveVenues(exit) {
    var checkedIds = Array.prototype.map.call(
      venueList.querySelectorAll('input[type=checkbox]:checked'),
      function (cb) { return cb.value; }
    );
    postForm('/passports/submissions/save/', {
      bearer_id: bearerIdField.value,
      submission_id: submissionIdField.value,
      venues_stamped: checkedIds,
      date_received: dateReceivedField.value,
      notes: notesField.value,
    }).then(function (result) {
      if (result.data.ok) {
        submissionIdField.value = result.data.submission_id;
        intakeReadout.textContent = 'Intake #' + result.data.intake_number + ' (' + result.data.season + ')';
        var msg = 'Saved — ' + result.data.stamp_count + ' stamps, ' + result.data.raffle_tickets + ' raffle tickets.';
        if (result.data.matched_existing) {
          msg = 'This bearer already had a submission this season — updated it instead of creating a new one. ' + msg;
        }
        venueSaveStatuses.forEach(function (el) {
          el.className = 'venue-save-status status-ok';
          el.textContent = msg;
        });
        if (exit) {
          window.location = '/passports/submissions/new/';
        }
      } else {
        venueSaveStatuses.forEach(function (el) {
          el.className = 'venue-save-status status-error';
          el.textContent = 'Could not save — please try again.';
        });
      }
    });
  }

  venueSaveButtons.forEach(function (btn) {
    btn.addEventListener('click', function () { saveVenues(btn.dataset.exit === 'true'); });
  });
})();
