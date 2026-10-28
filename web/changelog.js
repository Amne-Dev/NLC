(function(){
  const owner = 'Amne-Dev';
  const repo = 'NLC';
  const api = `https://api.github.com/repos/${owner}/${repo}/releases`;

  const listEl = document.getElementById('list');
  const statusEl = document.getElementById('status');
  const refreshBtn = document.getElementById('refreshBtn');

  function esc(s){
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function nl2br(s){
    return esc(s).replace(/\r?\n/g,'<br>');
  }

  async function fetchReleases(){
    statusEl.innerHTML = '<div class="card">Loading releases…</div>';
    listEl.innerHTML = '';
    try{
      const res = await fetch(api + '?per_page=50');
      if(!res.ok){
        const msg = `Failed to fetch releases: ${res.status} ${res.statusText}`;
        statusEl.innerHTML = `<div class="error">${esc(msg)}</div>`;
        return;
      }
      const releases = await res.json();
      statusEl.innerHTML = '';
      if(!releases || releases.length === 0){
        listEl.innerHTML = '<div class="card empty">No releases found.</div>';
        return;
      }

      releases.forEach(r => {
        const card = document.createElement('div');
        card.className = 'card';

        const title = document.createElement('div');
        title.className = 'release-title';
        title.innerHTML = `<strong>${esc(r.name || r.tag_name || 'Untitled release')}</strong> <span class="tag">${esc(r.tag_name||'')}</span>`;

        const meta = document.createElement('div');
        const date = r.published_at ? new Date(r.published_at).toLocaleString() : 'Unpublished';
        meta.className = 'meta';
        meta.textContent = `${date} • ${r.author ? r.author.login : 'unknown'}`;

        const body = document.createElement('div');
        body.className = 'body';
        body.innerHTML = nl2br(r.body || '');

        // Links row
        const links = document.createElement('div');
        links.className = 'meta';
        const htmlUrl = r.html_url ? `<a href="${r.html_url}" target="_blank">View on GitHub</a>` : '';
        const draftNote = r.draft ? ' (Draft)' : '';
        links.innerHTML = htmlUrl + draftNote;

        card.appendChild(title);
        card.appendChild(meta);
        if(r.body) card.appendChild(body);
        card.appendChild(links);

        listEl.appendChild(card);
      });

    }catch(err){
      statusEl.innerHTML = `<div class="error">Error: ${esc(err && err.message)}</div>`;
    }
  }

  refreshBtn.addEventListener('click', fetchReleases);
  // Auto-load on open
  fetchReleases();
})();