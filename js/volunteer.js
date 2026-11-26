
/* Volunteer Dashboard */
const me = session();

shell(
  'volunteer',
  [
    ['home', 'person-circle', 'Overview'],
    ['profile', 'person', 'My Profile'],
    ['acts', 'search', 'Activities'],
    ['reqs', 'list-check', 'My requests'],
    ['hist', 'clock-history', 'History']
  ],
  (tab, el) => {
    const d = db();
    const profile = d.users.find(u => u.email === me.email) || me;
    const mine = d.requests.filter(r => r.volunteer === profile.name);

    // OVERVIEW
    if (tab === 'home') {
      el.innerHTML = `
        <h2 class="h4 fw-bold mb-3">
          Welcome, ${esc(profile.name)}
        </h2>
        <div class="row g-3 mb-3">
          ${statCard('hourglass-split', mine.filter(r => r.status === 'Pending').length, 'Pending')}
          ${statCard('check-circle', mine.filter(r => r.status === 'Approved').length, 'Approved')}
          ${statCard('x-circle', mine.filter(r => r.status === 'Rejected').length, 'Rejected')}
          ${statCard('calendar-event', d.activities.length, 'Open activities')}
        </div>
        ${profileCard(profile)}
      `;
    }

    // MY PROFILE
    if (tab === 'profile') {
      el.innerHTML = `
        <div class="panel">
          <div class="d-flex justify-content-between align-items-center mb-3">
            <h5 class="mb-0">My Profile</h5>
            <button class="btn btn-green btn-sm" id="editProfile">
              <i class="bi bi-pencil"></i> Edit Profile
            </button>
          </div>

          <div class="row g-3">
            <div class="col-md-6">
              <label class="text-muted small">Full Name</label>
              <p class="fw-semibold">${esc(profile.name || 'Not added')}</p>
            </div>

            <div class="col-md-6">
              <label class="text-muted small">Email</label>
              <p class="fw-semibold">${esc(profile.email || 'Not added')}</p>
            </div>

            <div class="col-md-6">
              <label class="text-muted small">Phone</label>
              <p class="fw-semibold">${esc(profile.phone || 'Not added')}</p>
            </div>

            <div class="col-md-6">
              <label class="text-muted small">City</label>
              <p class="fw-semibold">${esc(profile.city || 'Not added')}</p>
            </div>

            <div class="col-12">
              <label class="text-muted small">Skills</label>
              <p class="fw-semibold">${esc(profile.skills || 'Not added')}</p>
            </div>
          </div>
        </div>
      `;

      $('#editProfile').onclick = () => {
        modal(
          'Edit Volunteer Profile',
          `
            <div class="mb-3">
              <label class="form-label">Full Name</label>
              <input class="form-control" id="pname"
                value="${esc(profile.name || '')}" required minlength="3">
            </div>

            <div class="mb-3">
              <label class="form-label">Email</label>
              <input class="form-control" value="${esc(profile.email || '')}" disabled>
            </div>

            <div class="mb-3">
              <label class="form-label">Phone</label>
              <input class="form-control" id="pphone"
                type="tel" value="${esc(profile.phone || '')}"
                required pattern="[0-9]{10}" maxlength="10">
              <small class="text-muted">Enter a 10-digit phone number.</small>
            </div>

            <div class="mb-3">
              <label class="form-label">City</label>
              <input class="form-control" id="pcity"
                value="${esc(profile.city || '')}" required>
            </div>

            <div class="mb-3">
              <label class="form-label">Skills</label>
              <textarea class="form-control" id="pskills"
                rows="3" required>${esc(profile.skills || '')}</textarea>
            </div>
          `,
          m => {
            const name = $('#pname', m).value.trim();
            const phone = $('#pphone', m).value.trim();
            const city = $('#pcity', m).value.trim();
            const skills = $('#pskills', m).value.trim();

            if (name.length < 3) {
              toast('Name must contain at least 3 characters.');
              return false;
            }

            if (!/^[0-9]{10}$/.test(phone)) {
              toast('Enter a valid 10-digit phone number.');
              return false;
            }

            if (!city || !skills) {
              toast('Please fill in all profile fields.');
              return false;
            }

            const x = db();
            const user = x.users.find(u => u.email === me.email);

            if (!user) {
              toast('User profile not found.');
              return false;
            }

            const oldName = user.name;

            user.name = name;
            user.phone = phone;
            user.city = city;
            user.skills = skills;

            // Keep existing requests linked to the updated name
            x.requests.forEach(r => {
              if (r.volunteer === oldName) {
                r.volunteer = name;
              }
            });

            save(x);

            // Update the current login session
            const sessionData = JSON.parse(
              localStorage.getItem('hh_session') ||
              sessionStorage.getItem('hh_session') ||
              'null'
            );

            if (sessionData) {
              sessionData.name = name;

              if (localStorage.getItem('hh_session')) {
                localStorage.setItem('hh_session', JSON.stringify(sessionData));
              } else {
                sessionStorage.setItem('hh_session', JSON.stringify(sessionData));
              }
            }

            toast('Profile updated successfully!');
            go('profile');
          }
        );
      };
    }

    // ACTIVITIES
    if (tab === 'acts') {
      el.innerHTML = `
        <div class="row g-2 mb-3">
          <div class="col-md-7">
            <input id="q" class="form-control"
              placeholder="Search by title, location or NGO">
          </div>
          <div class="col-md-5">
            <select id="f" class="form-select">
              <option value="">All locations</option>
              ${[...new Set(d.activities.map(a => a.location))]
                .map(l => `<option>${esc(l)}</option>`).join('')}
            </select>
          </div>
        </div>
        <div class="row g-3" id="list"></div>
      `;

      const draw = () => {
        const q = $('#q').value.toLowerCase();
        const f = $('#f').value;

        const activities = d.activities.filter(a =>
          [a.title, a.location, a.ngo].some(value => String(value || "").toLowerCase().includes(q)) &&
          (!f || a.location === f)
        );

        $('#list').innerHTML = activities.length
          ? activities.map(a => {
              const joined = mine.some(r => r.actId === a.id);

              return `
                <div class="col-md-6 col-xl-4">
                  <div class="panel h-100">
                    <h5>${esc(a.title)}</h5>
                    <p class="text-muted small">${esc(a.ngo)}</p>
                    <p class="small">
                      <i class="bi bi-calendar"></i> ${esc(a.date)}<br>
                      <i class="bi bi-geo-alt"></i> ${esc(a.location)}<br>
                      <i class="bi bi-people"></i> ${a.slots} slots
                    </p>
                    <button class="btn btn-sm btn-outline-hh" data-d="${a.id}">
                      Details
                    </button>
                    <button class="btn btn-sm btn-green"
                      data-j="${a.id}" ${joined ? 'disabled' : ''}>
                      ${joined ? 'Requested' : 'Join activity'}
                    </button>
                  </div>
                </div>
              `;
            }).join('')
          : '<p class="text-muted">No activities match. Try clearing the filters.</p>';
      };

      draw();
      $('#q').oninput = draw;
      $('#f').onchange = draw;

      el.onclick = e => {
        const j = e.target.closest('[data-j]');
        const i = e.target.closest('[data-d]');

        if (j) {
          const x = db();
          const activityId = Number(j.dataset.j);
          const activity = x.activities.find(a => a.id === activityId);

          if (!activity) {
            toast('This activity is no longer available.', 'danger');
            go('acts');
            return;
          }

          const alreadyRequested = x.requests.some(r =>
            r.actId === activityId && r.volunteer === profile.name
          );

          if (alreadyRequested) {
            toast('You have already requested this activity.', 'warning');
            go('acts');
            return;
          }

          x.requests.push({
            id: nid(x.requests),
            actId: activityId,
            volunteer: profile.name,
            status: 'Pending'
          });

          save(x);
          toast('Request sent. The NGO will review it.');
          go('acts');
        }

        if (i) {
          const a = d.activities.find(a => a.id == i.dataset.d);

          modal(
            a.title,
            `
              <p>${esc(a.desc)}</p>
              <p class="mb-0">
                <b>NGO:</b> ${esc(a.ngo)}<br>
                <b>Date:</b> ${esc(a.date)}<br>
                <b>Location:</b> ${esc(a.location)}<br>
                <b>Slots:</b> ${a.slots}
              </p>
            `
          );
        }
      };
    }

    // MY REQUESTS
    if (tab === 'reqs') {
      const renderRequests = status => {
        const filtered = status === 'All'
          ? mine
          : mine.filter(r => r.status === status);

        const emptyMessage = status === 'All'
          ? "You haven't submitted any requests yet."
          : `No ${status.toLowerCase()} requests found.`;

        el.innerHTML = `
          <div class="panel">
            <h5 class="mb-3">My requests</h5>
            <div class="d-flex flex-wrap gap-2 mb-3">
              ${['All', 'Pending', 'Approved', 'Rejected'].map(value => `
                <button type="button"
                  class="btn btn-sm ${status === value ? 'btn-green' : 'btn-outline-hh'}"
                  data-request-filter="${value}">
                  ${value}
                </button>
              `).join('')}
            </div>
            ${tbl(filtered, emptyMessage)}
          </div>
        `;
      };

      renderRequests('All');

      el.onclick = e => {
        const filter = e.target.closest('[data-request-filter]');
        if (filter) {
          renderRequests(filter.dataset.requestFilter);
        }
      };
    }

    // HISTORY
    if (tab === 'hist') {
      el.innerHTML = `
        <div class="panel">
          <h5 class="mb-3">Participation history</h5>
          ${tbl(mine.filter(r => r.status === 'Approved'))}
        </div>
      `;
    }

    // REQUEST TABLE
    function tbl(rows, emptyMessage = 'Nothing here yet. Join an activity to get started.') {
      return rows.length
        ? `
          <div class="table-responsive">
            <table class="table">
              <thead>
                <tr><th>Activity</th><th>Status</th></tr>
              </thead>
              <tbody>
                ${rows.map(r => `
                  <tr>
                    <td>${esc(actName(d, r.actId))}</td>
                    <td>${badge(r.status)}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `
        : `<p class="text-muted mb-0">${esc(emptyMessage)}</p>`;
    }
  }
);
