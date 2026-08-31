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

  // --- Venue filter ---------------------------------------------------
  var filterInput = document.getElementById('venue-filter');
  var venueRows = document.querySelectorAll('.venue-row');

  filterInput.addEventListener('keyup', function () {
    var q = filterInput.value.trim().toLowerCase();
    venueRows.forEach(function (row) {
      row.style.display = row.dataset.search.indexOf(q) === -1 ? 'none' : '';
    });
  });

  // --- Live stamp count / raffle tickets ------------------------------
  var venueList = document.getElementById('venue-list');
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
      return;
    }
    results.forEach(function (bearer) {
      var row = document.createElement('div');
      var detail = [bearer.phone, bearer.email].filter(Boolean).join(' · ');
      var text = bearer.name + (detail ? ' (' + detail + ')' : '');
      if (bearer.submission_id) {
        text += ' — already has a submission this season';
      }
      row.textContent = text;
      row.addEventListener('click', function () { pickBearer(bearer); });
      resultsBox.appendChild(row);
    });
    resultsBox.style.display = 'block';
  }

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
        bearerSaveStatus.className = 'status-error';
        bearerSaveStatus.textContent = 'Could not save bearer — check the fields above.';
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
