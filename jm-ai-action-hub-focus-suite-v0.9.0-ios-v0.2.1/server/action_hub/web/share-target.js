(() => {
  const payload = document.getElementById('sharedPayload');
  try {
    const sharedText = JSON.parse(payload?.textContent || '""');
    if (sharedText) sessionStorage.setItem('actionHubSharedText', String(sharedText));
  } catch {
    sessionStorage.removeItem('actionHubSharedText');
  }
  window.location.replace('/');
})();
