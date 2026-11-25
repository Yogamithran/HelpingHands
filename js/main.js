/* HelpingHands – shared helpers + localStorage "database".
   FLASK LATER: replace db()/save() with fetch('/api/...') calls. */
const SEED={
 users:[{id:1,name:'Admin User',email:'admin@helpinghands.test',role:'admin',status:'Active'},
  {id:2,name:'Green Earth Trust',email:'ngo@helpinghands.test',role:'ngo',status:'Active'},
  {id:3,name:'Annam Food Bank',email:'annam@helpinghands.test',role:'ngo',status:'Pending'},
  {id:4,name:'Anitha R',email:'volunteer@helpinghands.test',role:'volunteer',status:'Active'},
  {id:5,name:'Karthik S',email:'donor@helpinghands.test',role:'donor',status:'Active'}],
 activities:[
  {id:1,title:'Beach Clean-up Drive',desc:'Collect plastic waste along the shoreline with gloves and bags provided.',date:'2026-12-06',location:'Marina Beach, Chennai',slots:30,ngo:'Green Earth Trust'},
  {id:2,title:'Community Meal Packing',desc:'Pack 500 meal kits for families in need.',date:'2026-12-12',location:'Salem',slots:20,ngo:'Annam Food Bank'},
  {id:3,title:'Book Donation Camp',desc:'Sort and distribute books to government school libraries.',date:'2026-12-20',location:'Coimbatore',slots:25,ngo:'Green Earth Trust'}],
 requests:[{id:1,actId:1,volunteer:'Anitha R',status:'Approved'},{id:2,actId:2,volunteer:'Anitha R',status:'Pending'},{id:3,actId:3,volunteer:'Rahul M',status:'Pending'},{id:4,actId:3,volunteer:'Anitha R',status:'Rejected'}],
 donations:[{id:1,donor:'Karthik S',type:'Food',qty:'40 meal packs',ngo:'Annam Food Bank',note:'Vegetarian',status:'Received'},{id:2,donor:'Karthik S',type:'Books',qty:'60 books',ngo:'Green Earth Trust',note:'Class 6-10',status:'Pending'}],
 needs:[{type:'Food',item:'Rice & lentils (25 kg)',ngo:'Annam Food Bank',icon:'basket'},{type:'Clothes',item:'Winter blankets',ngo:'Green Earth Trust',icon:'handbag'},{type:'Books',item:'School textbooks',ngo:'Green Earth Trust',icon:'book'},{type:'Other',item:'Water bottles',ngo:'Annam Food Bank',icon:'box-seam'}]};
const B=document.body.dataset.base||'';
const $=(s,r=document)=>r.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function db(){let d=JSON.parse(localStorage.getItem('hh_db')||'null');if(!d){d=structuredClone(SEED);localStorage.setItem('hh_db',JSON.stringify(d))}return d}
const save=d=>localStorage.setItem('hh_db',JSON.stringify(d));
const nid=a=>Math.max(0,...a.map(x=>x.id))+1;
const session=()=>JSON.parse(localStorage.getItem('hh_session')||sessionStorage.getItem('hh_session')||'null');
const badge=s=>`<span class="badge-s ${s.toLowerCase()}">${esc(s)}</span>`;
const actName=(d,id)=>(d.activities.find(a=>a.id===id)||{title:'(deleted activity)'}).title;
function toast(msg,type='success'){const t=document.createElement('div');t.className=`toast align-items-center text-bg-${type} border-0`;t.innerHTML=`<div class="d-flex"><div class="toast-body">${esc(msg)}</div><button class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;$('#toasts').appendChild(t);new bootstrap.Toast(t,{delay:3000}).show()}
/* One reusable modal. onSave(modalEl) returns false to stay open (validation failed). */
function modal(title,body,onSave,btn='Save'){let m=$('#hhModal');if(!m){m=document.createElement('div');m.id='hhModal';m.className='modal fade';m.innerHTML='<div class="modal-dialog modal-dialog-centered"><div class="modal-content"><div class="modal-header"><h5 class="modal-title"></h5><button class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body"></div><div class="modal-footer"><button class="btn btn-light" data-bs-dismiss="modal">Close</button><button class="btn btn-hh" id="mSave"></button></div></div></div>';document.body.appendChild(m)}
 $('.modal-title',m).textContent=title;$('.modal-body',m).innerHTML=body;const s=$('#mSave',m);s.textContent=btn;s.style.display=onSave?'':'none';
 const inst=bootstrap.Modal.getOrCreateInstance(m);s.onclick=()=>{if(onSave&&onSave(m)===false)return;inst.hide()};inst.show()}
/* Validates every [required] field inside a container; shows Bootstrap feedback. */
function valid(root){let ok=true;root.querySelectorAll('input,select,textarea').forEach(f=>{const g=f.checkValidity();f.classList.toggle('is-invalid',!g);if(!g)ok=false});return ok}
function logout(){localStorage.removeItem('hh_session');sessionStorage.removeItem('hh_session');location.href=B+'login.html'}
/* Password show/hide buttons (login + register) */
document.addEventListener('click',e=>{const b=e.target.closest('.toggle-pw');if(!b)return;const i=b.parentElement.querySelector('input');i.type=i.type==='password'?'text':'password';b.firstElementChild.className='bi bi-eye'+(i.type==='text'?'-slash':'')});
/* Dashboard shell: role guard, sidebar, topbar, profile dropdown. render(tab, el) draws each tab. */
function shell(role,tabs,render){const u=session();if(!u||u.role!==role){location.href=B+'login.html';return}
 $('#app').innerHTML=`<div class="app"><aside class="side" id="side"><a class="brand" href="${B}index.html"><i class="bi bi-hand-thumbs-up-fill"></i> HelpingHands</a>${tabs.map(t=>`<button data-tab="${t[0]}"><i class="bi bi-${t[1]}"></i>${t[2]}</button>`).join('')}</aside>
 <div class="main"><div class="topbar"><button class="btn btn-light d-lg-none" id="menu" aria-label="Menu"><i class="bi bi-list"></i></button><h1 class="h5 fw-bold mb-0 text-capitalize">${role} dashboard</h1>
 <div class="dropdown"><button class="btn d-flex align-items-center gap-2" data-bs-toggle="dropdown"><span class="avatar">${esc(u.name[0].toUpperCase())}</span><span class="d-none d-md-inline">${esc(u.name)}</span></button><ul class="dropdown-menu dropdown-menu-end"><li><button class="dropdown-item" id="prof">My profile</button></li><li><button class="dropdown-item" onclick="logout()"><i class="bi bi-box-arrow-right me-2"></i>Log out</button></li></ul></div></div><div class="content" id="content"></div></div></div>`;
 const go=t=>{document.querySelectorAll('.side button').forEach(b=>b.classList.toggle('active',b.dataset.tab===t));$('#side').classList.remove('open');render(t,$('#content'))};
 window.go=go;document.querySelectorAll('.side button').forEach(b=>b.onclick=()=>go(b.dataset.tab));
 $('#menu').onclick=()=>$('#side').classList.toggle('open');$('#prof').onclick=()=>go(tabs[0][0]);go(tabs[0][0])}
const profileCard=u=>`<div class="panel d-flex gap-3 align-items-center"><span class="avatar" style="width:56px;height:56px;font-size:1.4rem">${esc(u.name[0])}</span><div><b>${esc(u.name)}</b><div class="text-muted small">${esc(u.email)}</div>${badge('Active')}</div></div>`;
const statCard=(i,n,l)=>`<div class="col-6 col-xl-3"><div class="panel stat"><span class="ico"><i class="bi bi-${i}"></i></span><div><b>${n}</b><small class="text-muted">${l}</small></div></div></div>`;
