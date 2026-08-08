const $ = (selector) => document.querySelector(selector);
let current = null;

const headers = () => ({"Content-Type":"application/json","X-User-Id":"demo-user","X-Role":$("#role").value,"X-Region":"south_china"});
async function api(path, options={}) {
  const response = await fetch(`/api/v1${path}`, {...options, headers:{...headers(),...(options.headers||{})}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || data.error || "请求失败");
  return data;
}
function toast(message, error=false){const el=$("#toast");el.textContent=message;el.className=`toast show${error?" error":""}`;setTimeout(()=>el.className="toast",2600)}
function statusIndex(status){return ["reported","triaged","diagnosing","waiting_expert","diagnosis_confirmed","fulfilling","ready_for_service","in_service","waiting_close_approval","closed"].indexOf(status)}
function card(title, body, score=""){return `<div class="card"><b>${title}</b>${body}${score?`<span class="score">${score}</span>`:""}</div>`}

function render(order){
  current=order;$("#empty").hidden=true;$("#work-order").hidden=false;$("#order-id").textContent=`THREAD ${order.thread_id} · V${order.task_plan?.plan_version||1}`;
  $("#order-title").textContent=`${order.vehicle.brand} / ${order.vehicle.model} · ${order.dtc_codes.join(",")||"待读取 DTC"}`;$("#status").textContent=order.status.toUpperCase();
  const idx=statusIndex(order.status);$("#progress").innerHTML=Array.from({length:6},(_,i)=>`<i class="${i<=Math.floor(idx/1.7)?"on":""}"></i>`).join("");
  const buttons=[];
  if(["triaged","rediagnosis_required"].includes(order.status)) buttons.push(["运行证据诊断","diagnose",true]);
  if(order.status==="waiting_expert") buttons.push(["专家确认初诊","confirm",true]);
  if(order.status==="fulfilling"){if(!order.selected_resource_id)buttons.push(["审批并预占资源","dispatch",false]);if(!order.reserved_part_codes.length)buttons.push(["预占候选配件","parts",false]);}
  if(order.status==="ready_for_service")buttons.push(["现场开工","start",true]);
  if(["fulfilling","ready_for_service","in_service"].includes(order.status))buttons.push(["模拟现场改诊","mismatch",false]);
  if(order.status==="in_service")buttons.push(["提交结案","close",true]);
  $("#actions").innerHTML=buttons.map(([label,action,hot])=>`<button data-action="${action}" class="${hot?"hot":""}">${label}</button>`).join("");
  $("#actions").querySelectorAll("button").forEach(button=>button.addEventListener("click",()=>act(button.dataset.action)));
  $("#evidence").innerHTML=order.diagnosis?.evidence?.length?order.diagnosis.evidence.map(e=>card(e.title,`${e.section}<br>${e.excerpt}`,`RRF+RERANK ${e.score}`)).join(""):card("尚无证据","运行诊断后展示品牌/车型/版本过滤后的证据链。");
  const fulfillment=[];
  order.dispatch_candidates?.slice(0,2).forEach(r=>fulfillment.push(card(r.display_name,`ETA ${r.eta_minutes} 分钟 · 负载 ${r.workload}`,`SCORE ${r.score}`)));
  order.parts_candidates?.slice(0,3).forEach(p=>fulfillment.push(card(`${p.name} · ${p.part_code}`,`${p.source} · 库存 ${p.stock} · ¥${p.unit_price}`,p.is_oem?"OEM":"AFTERMARKET")));
  $("#fulfillment").innerHTML=fulfillment.join("")||card("等待专家确认","确诊后，调度与配件工作流会并行扇出并 Join。");$("#m-plan").textContent=order.task_plan?.plan_version||1;refreshTelemetry();
}

async function act(action){
  try{
    let order=current;
    if(action==="diagnose")order=await api(`/work-orders/${order.service_request_id}/diagnose`,{method:"POST"});
    if(action==="confirm"){const diagnosis=order.diagnosis;order=await api(`/work-orders/${order.service_request_id}/expert-confirm`,{method:"POST",body:JSON.stringify({diagnosis_id:diagnosis.diagnosis_id,approved:true,confirmed_code:diagnosis.hypotheses[0].code,comment:"证据与专检结果一致"})});}
    if(action==="dispatch"){const approval=order.approvals.find(a=>a.action==="dispatch.assign"&&a.status==="pending");order=await api(`/work-orders/${order.service_request_id}/dispatch/approve`,{method:"POST",body:JSON.stringify({resource_id:order.dispatch_candidates[0].resource_id,approval_token:approval.token})});}
    if(action==="parts")order=await api(`/work-orders/${order.service_request_id}/parts/reserve`,{method:"POST",body:JSON.stringify({part_codes:[order.parts_candidates[0].part_code],bring_both:true})});
    if(action==="start")order=await api(`/work-orders/${order.service_request_id}/service/start`,{method:"POST"});
    if(action==="mismatch")order=await api(`/work-orders/${order.service_request_id}/mismatch`,{method:"POST",body:JSON.stringify({actual_code:"P204F",evidence:"现场喷射量测试与远程假设不一致"})});
    if(action==="close")order=await api(`/work-orders/${order.service_request_id}/close`,{method:"POST",body:JSON.stringify({resolution:"更换下游 NOx 传感器，完成自适应学习与路试，故障未复现。",actual_part_codes:order.reserved_part_codes,customer_rating:5})});
    render(order);toast("动作已完成并写入工单时间线");
  }catch(error){toast(error.message,true)}
}

$("#create-form").addEventListener("submit",async event=>{event.preventDefault();const form=new FormData(event.currentTarget);const ev=form.get("preset")==="ev";const payload=ev?{reporter_name:"张师傅",reporter_phone:"13800000000",vehicle:{vin:"LDPGBCDC0PA000101",brand:"deepway",model:"深向星辰",power_type:"electric",model_year:2025,configuration_code:"DW-HV-600"},symptom:form.get("symptom"),dtc_codes:["P0AA6"],telemetry:{insulation_kohm:82,battery_soc:61},service_mode:"fleet_service",location:"佛山顺德"}:{reporter_name:"王队长",reporter_phone:"13900000000",vehicle:{vin:"LVBV6PDC8SM000901",brand:"foton_auman",model:"银河 9",power_type:"diesel",model_year:2025,configuration_code:"AUM-G9-YC6"},symptom:form.get("symptom"),dtc_codes:["P20EE"],telemetry:{upstream_nox_ppm:410,downstream_nox_ppm:355,exhaust_temp_c:312},service_mode:"oem_authorized",location:"佛山顺德"};try{render(await api("/work-orders",{method:"POST",body:JSON.stringify(payload)}));toast("服务请求已创建：一工单一线程") }catch(error){toast(error.message,true)}});
$("#ops-form").addEventListener("submit",async event=>{event.preventDefault();const form=new FormData(event.currentTarget);try{$("#ops-result").textContent=JSON.stringify(await api("/operations/query",{method:"POST",body:JSON.stringify({question:form.get("question"),scenario_delta:Number(form.get("delta"))})}),null,2)}catch(error){toast(error.message,true)}});
$("#role").addEventListener("change",async()=>{if(current){try{render(await api(`/work-orders/${current.service_request_id}`))}catch(error){toast(error.message,true)}}});
async function refreshTelemetry(){try{const [orders,traces,tools]=await Promise.all([api("/work-orders"),api(`/traces${current?`?service_request_id=${current.service_request_id}`:""}`),api("/tools")]);$("#m-orders").textContent=orders.length;$("#m-spans").textContent=traces.length;$("#m-tools").textContent=tools.length;$("#trace-list").innerHTML=traces.slice(-12).map(t=>`<div class="trace"><b>${t.kind.toUpperCase()}</b>${t.name}<br>${t.status} · ${t.span_id}</div>`).join("")||"<p>暂无调用。</p>"}catch(error){console.warn(error)}}
window.addEventListener("load",()=>{setTimeout(()=>$("#boot").classList.add("done"),450);document.querySelectorAll(".reveal").forEach((el,i)=>setTimeout(()=>el.classList.add("visible"),180+i*120));refreshTelemetry()});
let lastY=0;window.addEventListener("scroll",()=>{const y=window.scrollY;document.querySelector(".topbar").classList.toggle("hidden",y>lastY&&y>140);lastY=y},{passive:true});

