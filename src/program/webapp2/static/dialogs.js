/* One dialog style for the shell and its embedded automatic measurement page. */
(() => {
  let queue = Promise.resolve();

  function showDialog(message, title, confirmLabel, cancelLabel) {
    const result = queue.then(() => new Promise(resolve => {
      let dialog = document.getElementById('waypoint-safety-dialog');
      if (!dialog) {
        dialog = document.createElement('dialog');
        dialog.id = 'waypoint-safety-dialog';
        dialog.setAttribute('aria-labelledby', 'waypoint-safety-title');
        dialog.setAttribute('aria-describedby', 'waypoint-safety-message');
        dialog.innerHTML = '<h2 id="waypoint-safety-title"></h2><p id="waypoint-safety-message"></p>'
          + '<form method="dialog" class="actions"><button id="waypoint-safety-no" type="submit" value="no" autofocus></button>'
          + '<button type="submit" value="yes"></button></form>';
        document.body.appendChild(dialog);
      }
      document.getElementById('waypoint-safety-title').textContent = title;
      document.getElementById('waypoint-safety-message').textContent = message;
      const cancel = document.getElementById('waypoint-safety-no');
      const confirm = dialog.querySelector('button[value="yes"]');
      cancel.textContent = cancelLabel || '';
      cancel.hidden = !cancelLabel;
      confirm.textContent = confirmLabel;
      // Escape must always cancel, including after a previously accepted dialog.
      dialog.returnValue = 'no';
      dialog.addEventListener('close', () => resolve(dialog.returnValue === 'yes'), {once: true});
      dialog.showModal();
      (cancelLabel ? cancel : confirm).focus();
    }));
    queue = result.catch(() => {});
    return result;
  }

  window.confirmAppAction = (message, title = 'Confirm action', confirmLabel = 'Continue', cancelLabel = 'Cancel') => {
    if (window.parent !== window && typeof window.parent.confirmAppAction === 'function') {
      return window.parent.confirmAppAction(message, title, confirmLabel, cancelLabel);
    }
    return showDialog(message, title, confirmLabel, cancelLabel);
  };

  window.showAppMessage = message => {
    if (window.parent !== window && typeof window.parent.showBlockingError === 'function') {
      window.parent.showBlockingError(message);
      return;
    }
    return showDialog(message, 'Error', 'OK', null);
  };
})();
