
/* HelpingHands - Flask API Authentication */

const alertBox = (type, message) => {
    const box = $('#msg');
    if (box) {
        box.innerHTML = `<div class="alert alert-${type}">${esc(message)}</div>`;
    }
};

const HOME = {
    admin: 'admin',
    ngo: 'ngo',
    volunteer: 'volunteer',
    donor: 'donor'
};

// Send requests to Flask backend.
async function apiPost(url, payload) {
    const response = await fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    });

    const data = await response.json();
    return { response, data };
}

// LOGIN
const loginForm = $('#loginForm');

if (loginForm) {
    loginForm.addEventListener('submit', async e => {
        e.preventDefault();

        if (!valid(e.target)) {
            return alertBox('danger', 'Please fix the highlighted fields.');
        }

        const button = loginForm.querySelector('button[type="submit"], button:not([type])');
        if (button) button.disabled = true;

        try {
            const email = $('#email').value.trim().toLowerCase();
            const password = $('#password').value;

            const { response, data } = await apiPost('/api/login', {
                email,
                password
            });

            if (!response.ok) {
                const type = response.status === 403 ? 'warning' : 'danger';
                return alertBox(type, data.message || 'Login failed.');
            }

            const user = data.user;

            if (!user || !HOME[user.role]) {
                return alertBox('danger', 'Invalid user role received.');
            }

            alertBox('success', 'Login successful. Redirecting...');

            location.href = `${HOME[user.role]}/dashboard.html`;

        } catch (error) {
            console.error('Login error:', error);
            alertBox('danger', 'Unable to connect to the server. Please try again.');
        } finally {
            if (button) button.disabled = false;
        }
    });
}


// REGISTRATION
const EXTRA = {
    ngo: [
        ['registration_number', 'Registration number', 'text', 'e.g. TN/2020/1234'],
        ['focus_area', 'Focus area', 'text', 'e.g. Education'],
        ['city', 'City', 'text', '']
    ],

    volunteer: [
        ['phone', 'Phone', 'tel', '10-digit number'],
        ['city', 'City', 'text', ''],
        ['skills', 'Skills', 'text', 'e.g. Teaching, First aid']
    ],

    donor: [
        ['phone', 'Phone', 'tel', '10-digit number'],
        ['city', 'City', 'text', '']
    ]
};

// Admin is intentionally excluded.
const ROLES = [
    ['volunteer', 'people'],
    ['donor', 'gift'],
    ['ngo', 'building']
];

const regForm = $('#regForm');

if (regForm) {
    const requestedRole = new URLSearchParams(location.search).get('role');

    let role = ROLES.some(r => r[0] === requestedRole)
        ? requestedRole
        : 'volunteer';

    const draw = () => {
        $('#roles').innerHTML = ROLES.map(r => `
            <div class="col-6 col-md-3">
                <div class="role-opt ${r[0] === role ? 'active' : ''}" data-r="${r[0]}">
                    <i class="bi bi-${r[1]}"></i>
                    ${r[0] === 'ngo' ? 'NGO' : r[0][0].toUpperCase() + r[0].slice(1)}
                </div>
            </div>
        `).join('');

        $('#fields').innerHTML = `
            <div class="col-md-6">
                <label class="form-label">
                    ${role === 'ngo' ? 'Organisation name' : 'Full name'}
                </label>
                <input class="form-control" id="rname" required minlength="3">
                <div class="invalid-feedback">Enter at least 3 characters.</div>
            </div>

            <div class="col-md-6">
                <label class="form-label">Email</label>
                <input type="email" class="form-control" id="remail" required>
                <div class="invalid-feedback">Enter a valid email.</div>
            </div>

            ${EXTRA[role].map(f => `
                <div class="col-md-6">
                    <label class="form-label">${f[1]}</label>
                    <input
                        type="${f[2]}"
                        class="form-control"
                        data-profile-key="${f[0]}"
                        placeholder="${f[3]}"
                        required
                        ${f[2] === 'tel' ? 'pattern="[0-9]{10}"' : ''}
                    >
                    <div class="invalid-feedback">
                        Required${f[2] === 'tel' ? ': 10 digits' : ''}.
                    </div>
                </div>
            `).join('')}

            <div class="col-md-6">
                <label class="form-label">Password</label>
                <div class="input-group">
                    <input type="password" class="form-control"
                        id="rpass" minlength="6" required>
                    <button type="button"
                        class="btn btn-outline-secondary toggle-pw"
                        aria-label="Show password">
                        <i class="bi bi-eye"></i>
                    </button>
                    <div class="invalid-feedback">At least 6 characters.</div>
                </div>
            </div>

            <div class="col-md-6">
                <label class="form-label">Confirm password</label>
                <input type="password" class="form-control"
                    id="rpass2" required>
                <div class="invalid-feedback">Passwords must match.</div>
            </div>
        `;

        document.querySelectorAll('.role-opt').forEach(option => {
            option.onclick = () => {
                role = option.dataset.r;
                draw();
            };
        });
    };

    draw();

    regForm.addEventListener('submit', async e => {
        e.preventDefault();

        let ok = valid(e.target);

        if ($('#rpass').value !== $('#rpass2').value) {
            $('#rpass2').classList.add('is-invalid');
            ok = false;
        }

        if (!ok) {
            return alertBox('danger', 'Please fix the highlighted fields.');
        }

        const button = regForm.querySelector('button[type="submit"], button:not([type])');
        if (button) button.disabled = true;

        try {
            const profile = {};

            document.querySelectorAll('[data-profile-key]').forEach(field => {
                profile[field.dataset.profileKey] = field.value.trim();
            });

            const payload = {
                name: $('#rname').value.trim(),
                email: $('#remail').value.trim().toLowerCase(),
                password: $('#rpass').value,
                role: role,
                profile: profile
            };

            const { response, data } = await apiPost('/api/register', payload);

            if (!response.ok) {
                return alertBox('danger', data.message || 'Registration failed.');
            }

            alertBox(
                'success',
                role === 'ngo'
                    ? 'Registration successful. Your NGO account is waiting for admin approval.'
                    : 'Account created successfully. Redirecting to login...'
            );

            setTimeout(() => {
                location.href = 'login.html';
            }, 1800);

        } catch (error) {
            console.error('Registration error:', error);
            alertBox('danger', 'Unable to connect to the server. Please try again.');
        } finally {
            if (button) button.disabled = false;
        }
    });
}
