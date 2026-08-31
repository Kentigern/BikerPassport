(function () {
  'use strict';

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
  var bearerIdField = document.getElementById('bearer_id');
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
      row.textContent = bearer.name + (detail ? ' (' + detail + ')' : '');
      row.addEventListener('click', function () { pickBearer(bearer); });
      resultsBox.appendChild(row);
    });
    resultsBox.style.display = 'block';
  }

  function pickBearer(bearer) {
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
})();
