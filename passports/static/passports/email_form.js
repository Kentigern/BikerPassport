(function () {
  'use strict';

  var csrfToken = document.getElementById('csrf_token').value;
  var campaignIdField = document.getElementById('campaign_id');

  var subjectInput = document.getElementById('id_subject');
  var purposeSelect = document.getElementById('id_purpose');
  var recipientCount = document.getElementById('recipient-count');
  var saveBtn = document.getElementById('save-btn');
  var saveStatus = document.getElementById('save-status');
  var subjectErrors = document.getElementById('subject-errors');
  var purposeErrors = document.getElementById('purpose-errors');

  var viewEditBtn = document.getElementById('view-edit-btn');
  var viewPreviewBtn = document.getElementById('view-preview-btn');
  var editorPane = document.getElementById('editor-pane');
  var previewPane = document.getElementById('preview-pane');
  var previewFrame = document.getElementById('preview-frame');

  var quill = new Quill('#editor', { theme: 'snow' });

  function refreshRecipientCount() {
    var purpose = purposeSelect.value;
    if (!purpose) {
      recipientCount.textContent = '';
      return;
    }
    fetch('/passports/emails/recipient-count/?purpose=' + encodeURIComponent(purpose))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        recipientCount.textContent = data.count + (data.count === 1 ? ' recipient' : ' recipients');
      });
  }

  purposeSelect.addEventListener('change', refreshRecipientCount);
  refreshRecipientCount();

  function setView(view) {
    var isPreview = view === 'preview';
    editorPane.style.display = isPreview ? 'none' : 'block';
    previewPane.style.display = isPreview ? 'block' : 'none';
    viewEditBtn.classList.toggle('active', !isPreview);
    viewPreviewBtn.classList.toggle('active', isPreview);
    if (isPreview && campaignIdField.value) {
      previewFrame.src = '/passports/emails/' + campaignIdField.value + '/preview/?t=' + Date.now();
    }
  }

  viewEditBtn.addEventListener('click', function () { setView('edit'); });
  viewPreviewBtn.addEventListener('click', function () {
    if (viewPreviewBtn.disabled) return;
    setView('preview');
  });

  saveBtn.addEventListener('click', function () {
    subjectErrors.textContent = '';
    purposeErrors.textContent = '';
    saveStatus.textContent = 'Saving…';
    saveStatus.className = '';

    var url = campaignIdField.value
      ? '/passports/emails/' + campaignIdField.value + '/edit/'
      : '/passports/emails/new/';

    var body = new URLSearchParams();
    body.append('subject', subjectInput.value);
    body.append('purpose', purposeSelect.value);
    body.append('body_html', quill.root.innerHTML);

    fetch(url, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    })
      .then(function (r) { return r.json().then(function (data) { return { status: r.status, data: data }; }); })
      .then(function (result) {
        if (!result.data.ok) {
          saveStatus.textContent = 'Please fix the errors above.';
          saveStatus.className = 'status-error';
          Object.keys(result.data.errors || {}).forEach(function (field) {
            var el = document.getElementById(field + '-errors');
            if (el) el.textContent = result.data.errors[field].join(' ');
          });
          return;
        }
        var wasNew = !campaignIdField.value;
        saveStatus.textContent = 'Saved.';
        saveStatus.className = 'status-ok';
        if (wasNew) {
          // A brand-new campaign needs a real pk before Preview/Send exist
          // — move to the edit URL for it now that one does.
          window.location = '/passports/emails/' + result.data.campaign_id + '/edit/';
          return;
        }
        viewPreviewBtn.disabled = false;
        viewPreviewBtn.removeAttribute('title');
      })
      .catch(function () {
        saveStatus.textContent = 'Could not reach the server — please try again.';
        saveStatus.className = 'status-error';
      });
  });
})();
