/* Login + registration (UI only). FLASK LATER: POST to /api/login and /api/register. */
const alertBox=(t,m)=>$('#msg').innerHTML=`<div class="alert alert-${t}">${esc(m)}</div>`;
const HOME={admin:'admin',ngo:'ngo',volunteer:'volunteer',donor:'donor'};
if($('#loginForm'))$('#loginForm').addEventListener('submit',e=>{e.preventDefault();
 if(!valid(e.target))return alertBox('danger','Please fix the highlighted fields.');
 const d=db(),email=$('#email').value.trim().toLowerCase();
 let u=d.users.find(x=>x.email===email);
 if(!u){u={id:nid(d.users),name:email.split('@')[0],email,role:$('#role').value,status:'Active'};d.users.push(u);save(d)}
 if(u.status==='Blocked')return alertBox('danger','This account is blocked. Contact the admin.');
 if(u.status==='Pending')return alertBox('warning','Your account is waiting for admin approval.');
 const s=JSON.stringify({name:u.name,email:u.email,role:u.role});
 ($('#remember').checked?localStorage:sessionStorage).setItem('hh_session',s);if($('#remember').checked===false)localStorage.removeItem('hh_session');
 alertBox('success','Logged in. Redirecting…');setTimeout(()=>location.href=`${u.role}/dashboard.html`,600)});
/* Registration: fields change with the chosen role */
const EXTRA={admin:[['Admin access code','text','Any code (demo)']],ngo:[['Registration number','text','e.g. TN/2020/1234'],['Focus area','text','e.g. Education'],['City','text','']],volunteer:[['Phone','tel','10-digit number'],['City','text',''],['Skills','text','e.g. Teaching, First aid']],donor:[['Phone','tel','10-digit number'],['City','text','']]};
const ROLES=[['volunteer','people'],['donor','gift'],['ngo','building'],['admin','shield-check']];
if($('#regForm')){let role=new URLSearchParams(location.search).get('role')||'volunteer';
 const draw=()=>{$('#roles').innerHTML=ROLES.map(r=>`<div class="col-6 col-md-3"><div class="role-opt ${r[0]===role?'active':''}" data-r="${r[0]}"><i class="bi bi-${r[1]}"></i>${r[0]==='ngo'?'NGO':r[0][0].toUpperCase()+r[0].slice(1)}</div></div>`).join('');
  $('#fields').innerHTML=`<div class="col-md-6"><label class="form-label">${role==='ngo'?'Organisation name':'Full name'}</label><input class="form-control" id="rname" required minlength="3"><div class="invalid-feedback">Enter at least 3 characters.</div></div>
  <div class="col-md-6"><label class="form-label">Email</label><input type="email" class="form-control" id="remail" required><div class="invalid-feedback">Enter a valid email.</div></div>
  ${EXTRA[role].map(f=>`<div class="col-md-6"><label class="form-label">${f[0]}</label><input type="${f[1]}" class="form-control" placeholder="${f[2]}" required ${f[1]==='tel'?'pattern="[0-9]{10}"':''}><div class="invalid-feedback">Required${f[1]==='tel'?': 10 digits':''}.</div></div>`).join('')}
  <div class="col-md-6"><label class="form-label">Password</label><div class="input-group"><input type="password" class="form-control" id="rpass" minlength="6" required><button type="button" class="btn btn-outline-secondary toggle-pw" aria-label="Show password"><i class="bi bi-eye"></i></button><div class="invalid-feedback">At least 6 characters.</div></div></div>
  <div class="col-md-6"><label class="form-label">Confirm password</label><input type="password" class="form-control" id="rpass2" required><div class="invalid-feedback">Passwords must match.</div></div>`;
  document.querySelectorAll('.role-opt').forEach(o=>o.onclick=()=>{role=o.dataset.r;draw()})};draw();
 $('#regForm').addEventListener('submit',e=>{e.preventDefault();let ok=valid(e.target);
  if($('#rpass').value!==$('#rpass2').value){$('#rpass2').classList.add('is-invalid');ok=false}
  if(!ok)return alertBox('danger','Please fix the highlighted fields.');
  const d=db(),email=$('#remail').value.trim().toLowerCase();
  if(d.users.some(u=>u.email===email))return alertBox('danger','That email is already registered.');
  d.users.push({id:nid(d.users),name:$('#rname').value.trim(),email,role,status:role==='ngo'?'Pending':'Active'});save(d);
  alertBox('success',role==='ngo'?'Registered. An admin must approve your NGO before you can log in.':'Account created. Redirecting to login…');
  setTimeout(()=>location.href='login.html',1800)})}
