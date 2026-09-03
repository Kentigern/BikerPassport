(function () {
  'use strict';

  var campaignId = document.getElementById('campaign_id').value;
  var status = document.getElementById('initial_status').value;

  var progressBar = document.getElementById('progress-bar');
  var statusLabel = document.getElementById('status-label');
  var sentCountEl = document.getElementById('sent-count');
  var failedCountEl = document.getElementById('failed-count');
  var recipientCountEl = document.getElementById('recipient-count');
  var resumeForm = document.getElementById('resume-form');

  var STATUS_LABELS = { draft: 'Draft', sending: 'Sending', sent: 'Sent' };

  function render(data) {
    var total = data.recipient_count || 1;
    var done = data.sent_count + data.failed_count;
    progressBar.style.width = Math.round((done / total) * 100) + '%';
    statusLabel.textContent = STATUS_LABELS[data.status] || data.status;
    sentCountEl.textContent = data.sent_count;
    failedCountEl.textContent = data.failed_count;
    recipientCountEl.textContent = data.recipient_count;
    resumeForm.style.display = data.status === 'sending' ? 'block' : 'none';
  }

  function poll() {
    fetch('/passports/emails/' + campaignId + '/status.json')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        render(data);
        if (data.status === 'sending') {
          setTimeout(poll, 1500);
        }
      });
  }

  if (status === 'sending') {
    poll();
  } else {
    resumeForm.style.display = 'none';
  }
})();
